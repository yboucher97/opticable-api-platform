from __future__ import annotations

import threading
import time
from typing import Any
from typing import Callable

from .store import AutomationStore
from .events import EventLedger


_SEVERITY_ORDER = {"info": 0, "warning": 1, "critical": 2}


class AutomationHealthMonitor:
    """Bounded, read-mostly automation health evaluation with durable transitions.

    The monitor never claims, executes, retries, redrives, or mutates workflow
    runs. It only reads bounded aggregate health and appends non-secret audit
    records when the alert state changes or a periodic sample is due.
    """

    def __init__(
        self,
        store: AutomationStore,
        *,
        sample_interval_seconds: int = 300,
        queue_backlog_threshold: int = 25,
        queue_growth_threshold: int = 10,
        recent_failure_threshold: int = 3,
        sync_health: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        if not 30 <= sample_interval_seconds <= 3600:
            raise ValueError("health sample interval must be 30-3600 seconds")
        if not 1 <= queue_backlog_threshold <= 10_000:
            raise ValueError("invalid queue backlog threshold")
        if not 1 <= queue_growth_threshold <= 10_000:
            raise ValueError("invalid queue growth threshold")
        if not 1 <= recent_failure_threshold <= 10_000:
            raise ValueError("invalid recent failure threshold")
        self.store = store
        self.sync_health = sync_health
        self.sample_interval_seconds = sample_interval_seconds
        self.queue_backlog_threshold = queue_backlog_threshold
        self.queue_growth_threshold = queue_growth_threshold
        self.recent_failure_threshold = recent_failure_threshold
        self._lock = threading.Lock()
        self._last_sample_monotonic = 0.0

    @staticmethod
    def _alert(code: str, severity: str, count: int, message: str) -> dict[str, Any]:
        return {
            "code": code,
            "severity": severity,
            "count": int(count),
            "message": message,
        }

    def _last_sample(self) -> dict[str, Any] | None:
        for item in self.store.recent_audit(200):
            if item.get("category") != "automation_health":
                continue
            if item.get("action") != "sample":
                continue
            metadata = item.get("metadata")
            if isinstance(metadata, dict):
                return metadata
        return None

    def _last_state(self) -> list[str] | None:
        for item in self.store.recent_audit(200):
            if item.get("category") != "automation_health":
                continue
            if item.get("action") != "alert_state_changed":
                continue
            metadata = item.get("metadata")
            if not isinstance(metadata, dict):
                continue
            codes = metadata.get("active_codes")
            if isinstance(codes, list) and all(isinstance(code, str) for code in codes):
                return sorted(set(codes))
        return None

    def evaluate(
        self,
        worker_health: dict[str, Any],
        *,
        database_health: dict[str, int] | None = None,
        previous_sample: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        db = database_health or self.store.execution_health()
        alerts: list[dict[str, Any]] = []

        if worker_health.get("enabled"):
            if not worker_health.get("thread_alive"):
                alerts.append(self._alert(
                    "recovery_worker_dead", "critical", 1,
                    "Automation recovery worker is not alive.",
                ))
            if worker_health.get("scan_stalled"):
                alerts.append(self._alert(
                    "recovery_worker_stalled", "critical", 1,
                    "Automation recovery scan exceeded its stall threshold.",
                ))
            if worker_health.get("heartbeat_stale"):
                alerts.append(self._alert(
                    "recovery_worker_heartbeat_stale", "critical", 1,
                    "Automation recovery heartbeat exceeded its stale threshold.",
                ))
            failures = int(worker_health.get("consecutive_failures") or 0)
            if failures:
                alerts.append(self._alert(
                    "recovery_worker_degraded", "warning", failures,
                    "Automation recovery worker has consecutive scan failures.",
                ))
            if worker_health.get("stopped_due_to_failures"):
                alerts.append(self._alert(
                    "recovery_worker_stopped", "critical", 1,
                    "Automation recovery worker stopped after repeated failures.",
                ))

        checks = (
            ("stale_queued", "stale_queued", "warning", "Queued work exceeded the stale threshold."),
            ("stale_running", "stale_running", "critical", "Running work exceeded the stale threshold."),
            ("expired_leases", "expired_leases", "critical", "Active work has expired execution leases."),
            ("human_action_required", "human_action_required", "critical", "Automation work requires human reconciliation."),
            ("dead_letter", "dead_letter", "warning", "Automation work is in dead-letter state."),
        )
        for key, code, severity, message in checks:
            value = int(db.get(key) or 0)
            if value:
                alerts.append(self._alert(code, severity, value, message))

        recent_failures = int(db.get("recent_failure_count") or 0)
        if recent_failures >= self.recent_failure_threshold:
            alerts.append(self._alert(
                "recent_failure_burst", "warning", recent_failures,
                "Recent automation failures exceeded the alert threshold.",
            ))

        queued = int(db.get("queued") or 0)
        if queued >= self.queue_backlog_threshold:
            alerts.append(self._alert(
                "queue_backlog", "warning", queued,
                "Automation queue exceeded the backlog threshold.",
            ))

        prior = previous_sample or {}
        previous_queued = prior.get("queued")
        if isinstance(previous_queued, int):
            growth = queued - previous_queued
            if queued > 0 and growth >= self.queue_growth_threshold:
                alerts.append(self._alert(
                    "queue_growth", "warning", growth,
                    "Automation queue grew materially since the previous health sample.",
                ))

        event_health = EventLedger(self.store).health()
        if self.sync_health:
            event_health["sync_worker"] = self.sync_health()
            if not event_health["sync_worker"]["healthy"]:
                alerts.append(self._alert("delta_worker_unhealthy", "critical", 1, "Delta synchronization worker is unhealthy."))
        if event_health["quarantined"]:
            alerts.append(self._alert("event_quarantine", "warning", event_health["quarantined"], "Events require quarantine review."))
        if event_health["backlog"] >= self.queue_backlog_threshold:
            alerts.append(self._alert("event_backlog", "warning", event_health["backlog"], "Event routing backlog exceeded its threshold."))
        if (event_health["oldest_unprocessed_age_seconds"] or 0) > 300:
            alerts.append(self._alert("event_routing_stale", "warning", event_health["backlog"], "Event routing has stalled."))
        stalled_sync = sum(item["status"] in {"failed", "resync_required"} for item in event_health["sync_checkpoints"])
        if stalled_sync:
            alerts.append(self._alert("delta_sync_stopped", "warning", stalled_sync, "Delta synchronization requires review."))
        stale_sync = sum(item["mode"] == "incremental" and (item["cursor_age_seconds"] or 0) > 172800 for item in event_health["sync_checkpoints"])
        if stale_sync:
            alerts.append(self._alert("delta_sync_stale", "warning", stale_sync, "Incremental synchronization checkpoint is stale."))

        alerts.sort(key=lambda item: (-_SEVERITY_ORDER[item["severity"]], item["code"]))
        status = "ok"
        if any(item["severity"] == "critical" for item in alerts):
            status = "critical"
        elif alerts:
            status = "warning"

        return {
            "status": status,
            "alerts": alerts,
            "database": db,
            "recovery_worker": worker_health,
            "events": event_health,
        }

    def inspect(self, worker_health: dict[str, Any]) -> dict[str, Any]:
        """Return current bounded health without writing audit state."""
        return self.evaluate(worker_health, previous_sample=self._last_sample())

    def observe(
        self,
        worker_health: dict[str, Any],
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        """Evaluate every call; persist transitions immediately and samples periodically."""
        with self._lock:
            now = time.monotonic()

            previous_sample = self._last_sample()
            snapshot = self.evaluate(
                worker_health,
                previous_sample=previous_sample,
            )

            db = snapshot["database"]
            active_codes = sorted(
                item["code"] for item in snapshot["alerts"]
            )
            previous_codes = self._last_state()

            state_changed = (
                previous_codes is None
                or active_codes != previous_codes
            )

            if state_changed:
                self.store.audit(
                    category="automation_health",
                    action="alert_state_changed",
                    actor="health-monitor",
                    success=snapshot["status"] == "ok",
                    metadata={
                        "status": snapshot["status"],
                        "active_codes": active_codes,
                        "alert_count": len(active_codes),
                    },
                )

            sample_due = (
                force
                or state_changed
                or self._last_sample_monotonic == 0.0
                or now - self._last_sample_monotonic
                >= self.sample_interval_seconds
            )

            if sample_due:
                self.store.audit(
                    category="automation_health",
                    action="sample",
                    actor="health-monitor",
                    success=snapshot["status"] == "ok",
                    metadata={
                        "status": snapshot["status"],
                        "queued": int(db.get("queued") or 0),
                        "claimed": int(db.get("claimed") or 0),
                        "running": int(db.get("running") or 0),
                        "stale_queued": int(db.get("stale_queued") or 0),
                        "stale_running": int(db.get("stale_running") or 0),
                        "expired_leases": int(db.get("expired_leases") or 0),
                        "dead_letter": int(db.get("dead_letter") or 0),
                        "human_action_required": int(
                            db.get("human_action_required") or 0
                        ),
                        "recent_failure_count": int(
                            db.get("recent_failure_count") or 0
                        ),
                        "worker_healthy": bool(
                            worker_health.get("healthy")
                        ),
                        "worker_stalled": bool(
                            worker_health.get("scan_stalled")
                        ),
                        "worker_heartbeat_stale": bool(
                            worker_health.get("heartbeat_stale")
                        ),
                        "active_codes": active_codes,
                    },
                )
                self._last_sample_monotonic = now

            snapshot["state_changed"] = state_changed
            snapshot["sample_persisted"] = sample_due
            return snapshot
