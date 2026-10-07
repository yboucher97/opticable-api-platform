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
            if action in {'started','verified','manual'}:
                from datetime import datetime,timezone
                from .action_evidence import ActionEvidence,envelope
                from .acquisition_store import digest
                audit=ActionEvidence(self.store.db_path);now=datetime.now(timezone.utc)
                aid=digest(['desired-state',target,metadata.get('plan_hash') or metadata.get('draft_identity')])
                if action=='started':
                    reversible=metadata.get('before_state') is not None and metadata.get('action')!='delete'
                    plan=envelope(aid,'CONFIGURATION_'+metadata.get('action','UNKNOWN'),{'type':metadata.get('kind','CONFIGURATION'),'identity':target},now,
                        mutation=True,initiator=actor,provider=metadata.get('provider','UNKNOWN'),
                        before_state=metadata.get('before_state') if metadata.get('before_state') is not None else {'exists':False},
                        proposed_state=metadata.get('proposed_state'),reason='Reviewed exact desired-state drift',
                        business_rationale='Explicit reviewed plan and fresh provider state; existing adapter authority remains required',
                        exact_versions={'document_hash':metadata.get('document_hash'),'plan_hash':metadata.get('plan_hash'),'version':metadata.get('document_version')},
                        rollback_capability='REVERSIBLE_WITH_LIMITATIONS' if reversible else 'COMPENSATING_ACTION_ONLY',
                        rollback_target=metadata.get('before_state') if reversible else None,
                        rollback_procedure='Owner-reviewed conditional restoration of exact captured provider configuration; reject newer drift' if reversible else None,
                        consequence='Configuration or derived object may affect downstream provider behavior',
                        compensating_action='Reconcile provider state with owner; preserve original intent and avoid destructive cleanup',
                        authority_class='EXPLICIT_DESIRED_STATE_REVIEW',automatic_rule='Existing exact plan/actor/root-adapter authorization')
                    audit.plan(plan,now);audit.start(aid,now,authority_check=lambda:None)
                elif audit.get(aid) and audit.get(aid)['status']=='STARTED':
                    audit.finish(aid,now,provider_success=action=='verified',actual_after=metadata.get('actual_after'),
                        verified=metadata.get('verification') is True,response=metadata.get('result'))
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
