"""Reviewed native-channel lifecycle using the existing Desired State journal.

The renewal thread is independent of delta/run workers. It can only renew an
already verified channel, never create a channel or resolve unknown writes by
retrying. Durable evidence also distinguishes our own public delivery drills.
"""
from datetime import datetime, timedelta, timezone
import json
import os
import threading

from .desired_journal import ApplyConflict, DesiredJournal, resource_key
from .event_schema import digest

CHANNEL = "5062683202609281"
ORG = "5062683000000020005"
NATIVE_KEY = digest(["zoho_crm", "notification", None, CHANNEL])
ORIGIN_KEY = NATIVE_KEY + ".provider-origin"


def delivery_key(payload):
    return "synthetic-native." + digest([CHANNEL, payload["server_time"], payload["module"],
                                         payload["operation"], sorted(payload["ids"])])


def mark_synthetic(store, payload):
    # Committed before public HTTP delivery; survives process loss or restart.
    DesiredJournal(store).record("synthetic_delivery_intent", delivery_key(payload),
                                {"delivery_class": "synthetic"}, "phase5-public-delivery-drill")


def origin_evidence(store):
    found = DesiredJournal(store).last(ORIGIN_KEY, ("provider_origin_verified",))
    if found and found["metadata"]["configuration_hash"] != digest([
            os.getenv("OPTIBRAIN_PHASE5_CRM_NOTIFY_ENDPOINT", ""), os.getenv("OPTIBRAIN_PHASE5_CRM_CHANNEL_CREDENTIAL", "")]):
        found = None
    return {"provider_origin_delivery": "verified" if found else "pending",
            "provider_emitted_event_proven": bool(found),
            "authentication": "native_token; no independent payload signature claim",
            "evidence": found["metadata"] if found else None}


def capture_origin(conn, endpoint, event, event_id):
    if (endpoint.provider != "zoho_crm" or endpoint.channel_id != CHANNEL or
            endpoint.secret_env != "OPTIBRAIN_PHASE5_CRM_CHANNEL_CREDENTIAL" or
            endpoint.source_account != ORG or
            event.event_type not in {"zoho.crm.Leads.insert", "zoho.crm.Leads.update"}):
        return
    synthetic = conn.execute("SELECT 1 FROM automation_audit WHERE category='desired_state_v1' "
        "AND action='synthetic_delivery_intent' AND target=? LIMIT 1", (delivery_key(event.payload),)).fetchone()
    action = "synthetic_delivery_received" if synthetic else "provider_origin_verified"
    target = delivery_key(event.payload) if synthetic else ORIGIN_KEY
    conn.execute("INSERT INTO automation_audit(at,category,action,actor,target,success,metadata_json) "
        "VALUES(?,?,?,?,?,?,?)", (datetime.now(timezone.utc).isoformat(), "desired_state_v1", action,
        "authenticated-native-intake", target, 1, json.dumps({"event_id": event_id,
        "channel_id": CHANNEL, "delivery_class": "synthetic" if synthetic else "provider-origin",
        "configuration_hash": digest([os.getenv("OPTIBRAIN_PHASE5_CRM_NOTIFY_ENDPOINT", ""),
                                       os.getenv(endpoint.secret_env, "")])}, sort_keys=True)))


def binding():
    expiry = datetime.fromisoformat(os.environ["OPTIBRAIN_PHASE5_CRM_CHANNEL_EXPIRY"].replace("Z", "+00:00"))
    if expiry.tzinfo is None:
        raise ValueError("Native bootstrap expiry timezone required")
    return digest([CHANNEL, os.environ["OPTIBRAIN_PHASE5_CRM_NOTIFY_ENDPOINT"],
                   os.environ["OPTIBRAIN_PHASE5_CRM_CHANNEL_CREDENTIAL"], expiry.astimezone(timezone.utc).isoformat()])


def effective_endpoint(store, endpoint):
    """Only a verified matching renewal extends this exact callback's expiry."""
    if (endpoint.provider != "zoho_crm" or endpoint.channel_id != CHANNEL or
            endpoint.source_account != ORG or endpoint.secret_env != "OPTIBRAIN_PHASE5_CRM_CHANNEL_CREDENTIAL" or
            endpoint.allowed_event_types != ["zoho.crm.Leads.insert", "zoho.crm.Leads.update"]):
        return endpoint
    found = DesiredJournal(store).last(NATIVE_KEY, ("native_verified",))
    try:
        if found and found["metadata"]["binding"] == binding():
            return endpoint.model_copy(update={"expires_at": found["metadata"]["state"]["expiry"]})
    except (ValueError, KeyError):
        pass  # Original expiry/authentication policy still fails closed.
    return endpoint


def native_health(store, *, now=None):
    journal = DesiredJournal(store)
    now = now or datetime.now(timezone.utc)
    verified = journal.last(NATIVE_KEY, ("native_verified",))
    observation = journal.last(NATIVE_KEY, ("native_status",))
    intent = journal.last(NATIVE_KEY, ("started", "verified", "manual"))
    status = "pending_subscription" if os.getenv("OPTIBRAIN_CRM_DRIFT_ENABLED") == "true" else "unconfigured"
    expiry = None
    if verified:
        expiry = verified["metadata"]["state"]["expiry"]
        status = "verified"
        try:
            if verified["metadata"]["binding"] != binding():
                status = "configuration_drift"
        except (ValueError, KeyError):
            status = "configuration_drift"
    if status != "configuration_drift" and observation and (not verified or observation["at"] >= verified["at"]):
        status = observation["metadata"]["status"]
    if intent and intent["action"] != "verified":
        status = "human_action_required"
    remaining = int((datetime.fromisoformat(expiry) - now).total_seconds()) if expiry else None
    if remaining is not None and remaining <= 0 and status == "verified":
        status = "expired"
    verified_at = verified["metadata"].get("verified_at", verified["at"]) if verified else None
    if verified and (now - datetime.fromisoformat(verified_at)).total_seconds() > 86400 and status == "verified":
        status = "verification_stale"
    renewal = journal.last(NATIVE_KEY, ("native_renewal_result",))
    return {"native_subscription_status": status, "native_subscription_expires_at": expiry,
            "native_subscription_seconds_remaining": remaining,
            "native_subscription_renewal_required": remaining is not None and remaining <= 86400,
            "native_subscription_last_verified_at": verified_at,
            "native_subscription_last_renewal_result": renewal["metadata"] if renewal else None,
            **origin_evidence(store)}


class NativeNotificationWorker:
    def __init__(self, controller, document, *, interval=300):
        if not 30 <= interval <= 3600:
            raise ValueError("Native renewal interval bound")
        self.controller, self.document, self.interval = controller, document, interval
        self._stop, self._thread = threading.Event(), None

    def poll(self):
        from .provider_usage import ProviderUsage
        with ProviderUsage(getattr(self.controller.journal.store,'db_path',None),'observer:native-watch',
                           runs_per_day=86400/self.interval,soft_budget=2):
            return self._poll()

    def _poll(self):
        # The existing cross-process Desired State apply lock serializes intent
        # reconciliation. apply() takes the same lock, so planning occurs outside.
        document = self.controller.load(self.document)
        if len(document.resources) != 1:
            raise ValueError("Exactly one reviewed notification resource required")
        resource = document.resources[0]
        adapter = self.controller.registry.resolve(resource)
        from .reconcilers.zoho_notification import ZohoCrmNotificationReconciler
        if not isinstance(adapter, ZohoCrmNotificationReconciler) or not resource.enabled or resource.lifecycle.get("ensure", "present") != "present":
            raise ValueError("Only the reviewed native notification adapter is allowed")
        adapter.configuration(resource)  # Scope refusal before provider access.
        journal, key = self.controller.journal, resource_key(resource)
        plan = self.controller.plan(document)
        change = plan.changes[0]
        with journal.lock():
            if journal.unresolved(key):
                previous = journal.last(key, ("started", "manual"))
                evidence = previous["metadata"]
                if (evidence.get("action") == "update" and evidence.get("native_binding") == adapter.binding(resource)
                        and change.current == evidence.get("native_expected")):
                    adapter.remember(resource, change.current)
                    journal.record("verified", key, {**evidence, "verification": True, "reconciled_by_readback": True}, "native-renewal-reconciliation")
                    journal.record("native_renewal_result", key, {"status": "verified", "reconciled_by_readback": True}, "native-renewal")
                else:
                    journal.record("native_status", key, {"status": "human_action_required"}, "native-renewal")
                    return
        previous = adapter.verified(resource)
        if change.current == previous and previous:
            expiry = datetime.fromisoformat(previous["expiry"])
            if expiry - adapter.clock() <= timedelta(hours=24):
                renewal = document.model_copy(deep=True)
                renewal.resources[0].desired["renewal_expiry"] = (adapter.clock() + timedelta(days=6)).replace(microsecond=0).isoformat()
                plan = self.controller.plan(renewal)
                results = self.controller.apply(renewal, plan, actor="reviewed-phase5-native-renewal")
                status = "verified" if all(r.status == "completed" for r in results) else "human_action_required"
                journal.record("native_renewal_result", key, {"status": status, "results": [r.model_dump(mode="json") for r in results]}, "native-renewal")
                journal.record("native_status", key, {"status": status}, "native-renewal")
                return
            with journal.lock():
                if journal.unresolved(key) or adapter.verified(resource) != previous:
                    return
                adapter.remember(resource, previous)  # Refresh time without overwriting a concurrent renewal.
            status = "verified"
        else:
            status = "pending_subscription" if change.action == "create" else "degraded"
        journal.record("native_status", key, {"status": status}, "native-renewal")

    def _run(self):
        while not self._stop.is_set():
            try:
                self.poll()
            except ApplyConflict:
                pass  # No intent/write occurred; another controller owns the lock.
            except Exception as exc:
                self.controller.journal.record("native_status", NATIVE_KEY,
                    {"status": "degraded", "exception_type": type(exc).__name__}, "native-renewal")
            self._stop.wait(self.interval)

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="reviewed-native-renewal", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
