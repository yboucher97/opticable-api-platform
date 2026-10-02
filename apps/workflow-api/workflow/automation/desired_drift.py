"""Read-only periodic desired-state drift checks on the existing delta worker."""
from pathlib import Path
import time

from .desired_journal import ApplyConflict


class DesiredDriftObserver:
    def __init__(self, controller, directory: Path, *, interval=3600):
        if not 300 <= interval <= 86400:
            raise ValueError("drift interval bound")
        self.controller, self.directory, self.interval = controller, directory, interval
        self.next_scan = 0

    def poll(self):
        if time.monotonic() < self.next_scan:
            return
        from .provider_usage import ProviderUsage
        with ProviderUsage(getattr(self.controller.journal.store,'db_path',None),'observer:desired-drift',
                           runs_per_day=86400/self.interval,soft_budget=20):
            return self._scan()

    def _scan(self):
        paths = sorted(self.directory.glob("opticable-*.json"))
        notification = self.directory / "zoho-crm-notification.template.json"
        if notification.is_file():
            paths.append(notification)
        if not 1 <= len(paths) <= 4:
            raise ValueError("drift document bound")
        try:
            with self.controller.journal.lock():
                for path in paths:
                    document = self.controller.load(path)
                    plan = self.controller.plan(document)
                    self.controller.journal.record("drift", document.name,
                        {"document_hash": plan.document_hash, "plan_hash": plan.plan_hash,
                         "summary": plan.summary, "changes": [{"resource_id": c.resource_id,
                             "action": c.action, "risk": c.risk} for c in plan.changes if c.action != "noop"]},
                        "read-only-drift-observer")
        except ApplyConflict:
            return
        self.next_scan = time.monotonic() + self.interval
