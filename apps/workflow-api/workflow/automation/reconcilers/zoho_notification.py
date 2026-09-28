"""Exact reviewed CRM notification creation/renewal, without secret output."""
from datetime import datetime, timedelta, timezone
import hmac
import os
import re
from urllib.parse import urlsplit

from ..desired_state import DesiredApplyResult, DesiredChange
from ..event_schema import digest
from ..desired_journal import resource_key


class ZohoCrmNotificationReconciler:
    name = "zoho_crm.notification.v1"
    approved_channel = "5062683202609281"
    approved_references = {"destination_env": "OPTIBRAIN_PHASE5_CRM_NOTIFY_ENDPOINT",
                           "credential_env": "OPTIBRAIN_PHASE5_CRM_CHANNEL_CREDENTIAL",
                           "expiry_env": "OPTIBRAIN_PHASE5_CRM_CHANNEL_EXPIRY"}

    def __init__(self, client, *, clock=None):
        self.client, self.journal = client, None
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def bind_journal(self, journal):
        self.journal = journal

    def binding(self, resource):
        destination, credential, when, channel = self.configuration(resource)
        return digest([channel, destination, credential, when.isoformat()])

    def verified(self, resource):
        record = self.journal.last(resource_key(resource), ("native_verified",)) if self.journal else None
        if record and record["metadata"]["binding"] == self.binding(resource):
            return record["metadata"]["state"]
        return None

    def remember(self, resource, state):
        if self.journal:
            self.journal.record("native_verified", resource_key(resource),
                {"binding": self.binding(resource), "state": state, "verified_at": self.clock().isoformat()}, "native-notification-verifier")

    def intent_evidence(self, resource, change):
        return {"native_expected": change.desired, "native_binding": self.binding(resource)}

    def configuration(self, resource):
        if set(resource.identity) != {"channel_id"}:
            raise ValueError("Only the exact reviewed notification identity is allowed")
        refs = resource.metadata.get("authentication", {})
        if refs != self.approved_references:
            raise ValueError("Only reviewed native notification authentication references are allowed")
        if set(refs) != {"destination_env", "credential_env", "expiry_env"} or any(
                not isinstance(v, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{1,127}", v) for v in refs.values()):
            raise ValueError("Notification authentication environment references required")
        destination = os.getenv(refs["destination_env"], "")
        credential = os.getenv(refs["credential_env"], "")
        expiry = os.getenv(refs["expiry_env"], "")
        parts = urlsplit(destination)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or not 32 <= len(credential.encode()) <= 50:
            raise ValueError("Notification requires HTTPS and 32-50 byte verification token")
        when = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
        if when.tzinfo is None:
            raise ValueError("Notification expiry timezone required")
        channel = resource.identity.get("channel_id")
        if not isinstance(channel, str) or not channel.isdigit() or not 1 <= int(channel) <= 2**63 - 1:
            raise ValueError("Notification channel identity required")
        if channel != self.approved_channel:
            raise ValueError("Only the reviewed Phase 5 lead notification channel is allowed")
        if (resource.desired.get("events") != ["Leads.create", "Leads.edit"] or
                set(resource.desired) - {"events", "renewal_expiry"}):
            raise ValueError("Only lead create/edit subscriptions are approved")
        return destination, credential, when.astimezone(timezone.utc), channel

    def read(self, resource):
        destination, credential, _, channel = self.configuration(resource)
        response = self.client.request("zohoapis", "GET", "/crm/v8/actions/watch", query={"channel_id": channel, "per_page": 200})
        if response.get("ok") is True and response.get("status") == 204: return None
        data = response.get("data") or {}
        rows = data.get("watch")
        if response.get("ok") is not True or response.get("status") != 200 or not isinstance(rows, list) or len(rows) > 200 or (data.get("info") or {}).get("more_records"):
            raise ValueError("Notification read incomplete")
        matches = [r for r in rows if str(r.get("channel_id")) == channel]
        if not matches: return None
        if len(matches) != 1: raise ValueError("Notification channel collision")
        record = matches[0]
        expiry = datetime.fromisoformat(record["channel_expiry"].replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            raise ValueError("Provider expiry timezone required")
        return {"channel_id": channel, "events": sorted(record.get("events") or []),
                "configuration_hash": digest([record.get("notify_url"), record.get("token")]),
                "expiry": expiry.astimezone(timezone.utc).isoformat(), "authentication_matches": hmac.compare_digest(str(record.get("token", "")).encode(), credential.encode()),
                "destination_matches": record.get("notify_url") == destination,
                "related_actions": record.get("notify_on_related_action"),
                "field_values": record.get("return_affected_field_values"),
                "conditions_absent": not record.get("notification_condition") and not record.get("fields")}

    def plan(self, resource):
        destination, credential, when, channel = self.configuration(resource)
        current = self.read(resource)
        previous = self.verified(resource)
        if previous:
            when = datetime.fromisoformat(previous["expiry"])
        renewal = resource.desired.get("renewal_expiry")
        if renewal:
            when = datetime.fromisoformat(renewal)
            if when.tzinfo is None:
                raise ValueError("Renewal expiry timezone required")
            when = when.astimezone(timezone.utc)
        desired = {"channel_id": channel, "events": sorted(resource.desired["events"]), "expiry": when.isoformat(),
                   "configuration_hash": digest([destination, credential]),
                   "authentication_matches": True, "destination_matches": True, "related_actions": False, "field_values": False,
                   "conditions_absent": True}
        action, reason, risk = "noop", "Native subscription matches", "low"
        if resource.lifecycle.get("ensure", "present") != "present":
            action, reason, risk = "blocked", "Subscription deletion requires separate human approval", "destructive"
        elif current is None:
            if renewal or previous:
                action, reason, risk = "manual", "Missing reviewed channel; no automatic channel creation", "medium"
            elif not self.clock() < when <= self.clock() + timedelta(days=7):
                action, reason = "blocked", "Native notification expiry must be within seven days"
            else: action, reason = "create", "Add authenticated lead notification subscription"
        elif not current["authentication_matches"] or not current["destination_matches"]:
            action, reason, risk = "blocked", "Existing channel authentication/destination collision", "high"
        elif renewal and current != desired:
            if (previous == current and self.clock() < when <= self.clock() + timedelta(days=7)
                    and when > datetime.fromisoformat(current["expiry"])
                    and datetime.fromisoformat(current["expiry"]) - self.clock() <= timedelta(hours=24)
                    and {k: v for k, v in current.items() if k != "expiry"} == {k: v for k, v in desired.items() if k != "expiry"}):
                action, reason, risk = "update", "Renew only the verified Phase 5 channel expiry", "medium"
            else:
                action, reason, risk = "manual", "Renewal outside reviewed policy or provider drift", "medium"
        elif current != desired or datetime.fromisoformat(current["expiry"]) <= self.clock():
            action, reason, risk = "manual", "Subscription drift/expiry requires reviewed renewal; no blind write", "medium"
        return DesiredChange(resource_id=resource.id, provider=resource.provider, kind=resource.kind, name=resource.name,
                             action=action, reason=reason, current=current, desired=desired, risk=risk)

    def apply(self, resource, change):
        fresh = self.plan(resource)
        if change.action not in {"create", "update"} or (fresh.action, fresh.current, fresh.desired) != (change.action, change.current, change.desired):
            raise ValueError("Subscription plan changed before apply")
        destination, credential, when, channel = self.configuration(resource)
        if digest([destination, credential]) != change.desired["configuration_hash"]:
            raise ValueError("Subscription authentication changed before mutation")
        if change.action == "update":
            # PATCH preserves other channel settings. Exact full readback below
            # verifies that this operation changed only the reviewed expiry.
            when = datetime.fromisoformat(change.desired["expiry"])
        response = None
        exception_type = None
        try:
            response = self.client.request("zohoapis", "POST" if change.action == "create" else "PATCH", "/crm/v8/actions/watch", body={"watch": [{
                "channel_id": channel, "events": resource.desired["events"], "notify_url": destination,
                "token": credential, "channel_expiry": when.isoformat(), "notify_on_related_action": False,
                "return_affected_field_values": False}]}, confirm=True, reason="Phase 5 reviewed lead notification subscription/renewal")
        except Exception as exc:
            if change.action == "create":
                raise
            exception_type = type(exc).__name__
        response = response or {}
        rows = (response.get("data") or {}).get("watch")
        accepted = response.get("ok") is True and response.get("status") in {200, 201} and isinstance(rows, list) and len(rows) == 1 and rows[0].get("status") == "success"
        verified = False
        if accepted or change.action == "update":
            try:
                verified = self.read(resource) == change.desired
            except Exception as exc:
                exception_type = type(exc).__name__
        if verified:
            self.remember(resource, change.desired)
        return DesiredApplyResult(resource_id=resource.id, action=change.action, status="completed" if verified else "manual", changed=verified or accepted,
            result={"request_id": response.get("request_id"), "operation_id": channel if accepted else None, "verification": verified,
                    "reconciled_by_readback": verified and not accepted, "exception_type": exception_type})
