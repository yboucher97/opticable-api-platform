"""Additive native CRM notification subscription, verified without secret output."""
from datetime import datetime, timedelta, timezone
import hmac
import os
import re
from urllib.parse import urlsplit

from ..desired_state import DesiredApplyResult, DesiredChange


class ZohoCrmNotificationReconciler:
    name = "zoho_crm.notification.v1"

    def __init__(self, client): self.client = client

    def configuration(self, resource):
        refs = resource.metadata.get("authentication", {})
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
        if resource.desired.get("events") != ["Leads.create", "Leads.edit"]:
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
        return {"channel_id": channel, "events": sorted(record.get("events") or []),
                "expiry": datetime.fromisoformat(record["channel_expiry"].replace("Z", "+00:00")).astimezone(timezone.utc).isoformat(), "authentication_matches": hmac.compare_digest(str(record.get("token", "")).encode(), credential.encode()),
                "destination_matches": record.get("notify_url") == destination,
                "related_actions": record.get("notify_on_related_action"),
                "field_values": record.get("return_affected_field_values")}

    def plan(self, resource):
        _, _, when, channel = self.configuration(resource)
        current = self.read(resource)
        desired = {"channel_id": channel, "events": sorted(resource.desired["events"]), "expiry": when.isoformat(),
                   "authentication_matches": True, "destination_matches": True, "related_actions": False, "field_values": False}
        action, reason, risk = "noop", "Native subscription matches", "low"
        if resource.lifecycle.get("ensure", "present") != "present":
            action, reason, risk = "blocked", "Subscription deletion requires separate human approval", "destructive"
        elif current is None:
            if not datetime.now(timezone.utc) < when <= datetime.now(timezone.utc) + timedelta(days=7):
                action, reason = "blocked", "Native notification expiry must be within seven days"
            else: action, reason = "create", "Add authenticated lead notification subscription"
        elif not current["authentication_matches"] or not current["destination_matches"]:
            action, reason, risk = "blocked", "Existing channel authentication/destination collision", "high"
        elif current != desired or datetime.fromisoformat(current["expiry"].replace("Z", "+00:00")) <= datetime.now(timezone.utc):
            action, reason, risk = "manual", "Subscription drift/expiry requires reviewed renewal; no blind write", "medium"
        return DesiredChange(resource_id=resource.id, provider=resource.provider, kind=resource.kind, name=resource.name,
                             action=action, reason=reason, current=current, desired=desired, risk=risk)

    def apply(self, resource, change):
        fresh = self.plan(resource)
        if change.action != "create" or (fresh.action, fresh.current, fresh.desired) != (change.action, change.current, change.desired):
            raise ValueError("Subscription creation changed before apply")
        destination, credential, when, channel = self.configuration(resource)
        response = self.client.request("zohoapis", "POST", "/crm/v8/actions/watch", body={"watch": [{
            "channel_id": channel, "events": resource.desired["events"], "notify_url": destination,
            "token": credential, "channel_expiry": when.isoformat(), "notify_on_related_action": False,
            "return_affected_field_values": False}]}, confirm=True, reason="Phase 5 authenticated lead notification intake")
        rows = (response.get("data") or {}).get("watch")
        accepted = response.get("ok") is True and response.get("status") in {200, 201} and isinstance(rows, list) and len(rows) == 1 and rows[0].get("status") == "success"
        verified = self.plan(resource).action == "noop" if accepted else False
        return DesiredApplyResult(resource_id=resource.id, action="create", status="completed" if verified else "manual", changed=accepted,
            result={"request_id": response.get("request_id"), "operation_id": channel if accepted else None, "verification": verified})
