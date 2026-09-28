"""Desired State evidence in the existing automation audit table; no new schema."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
import stat
import threading

from .event_schema import digest


class ApplyConflict(ValueError):
    pass


def resource_key(resource) -> str:
    identity = resource.identity
    desired = resource.desired
    return digest([resource.provider, resource.kind, identity.get("module", desired.get("module")),
                   identity.get("channel_id") or identity.get("id") or identity.get("api_name") or desired.get("api_name") or resource.name])


class DesiredJournal:
    def __init__(self, store=None):
        self.store, self._lock, self._records = store, threading.Lock(), []

    @contextmanager
    def lock(self):
        if not self._lock.acquire(blocking=False):
            raise ApplyConflict("desired_state_apply_in_progress")
        fd = None
        try:
            if self.store is not None:
                path = self.store.db_path.with_suffix(".desired-state.lock")
                fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
                meta = os.fstat(fd)
                if not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.geteuid() or meta.st_nlink != 1 or meta.st_mode & 0o077:
                    raise ApplyConflict("unsafe_desired_state_lock")
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise ApplyConflict("desired_state_apply_in_progress") from None
            yield
        finally:
            if fd is not None:
                os.close(fd)
            self._lock.release()

    def record(self, action: str, target: str, metadata: dict, actor: str) -> None:
        if self.store is not None:
            self.store.audit(category="desired_state_v1", action=action, actor=actor,
                             success=action == "verified" or (action == "apply_result" and all(
                                 r.get("status") == "completed" for r in metadata.get("results", []))), target=target, metadata=metadata)
        else:
            self._records.append({"action": action, "target": target, "metadata": metadata})

    def last(self, target: str, actions: tuple[str, ...]) -> dict | None:
        if self.store is not None:
            with self.store._connect() as conn:
                row = conn.execute("SELECT action,metadata_json,at,actor FROM automation_audit WHERE category='desired_state_v1' "
                                   "AND target=? AND action IN (" + ",".join("?" for _ in actions) + ") ORDER BY id DESC LIMIT 1",
                                   (target, *actions)).fetchone()
            return {"action": row[0], "metadata": json.loads(row[1]), "at": row[2], "actor": row[3]} if row else None
        return next((r for r in reversed(self._records) if r["target"] == target and r["action"] in actions), None)

    def unresolved(self, target: str) -> bool:
        previous = self.last(target, ("started", "verified", "manual"))
        return previous is not None and previous["action"] != "verified"
