"""Explicit capture-only maintenance mode in the existing event ledger.

No routing, workers, replay, provider calls, schema changes, or pruning. Each
receipt and its quarantine commit together before HTTP success. Switching the
kernel on later cannot release these events; existing reviewed replay controls
remain the only release path.
"""
from dataclasses import dataclass
from contextlib import closing
import os
from pathlib import Path
import shutil
import sqlite3

from .events import EventConflict, EventLedger
from .models import AutomationEvent

HOLD_REASON = 'migration_intake_hold'
EXECUTION_OFF = {
    'OPTICABLE_AUTOMATION_ENABLED': 'false', 'OPTIBRAIN_CRM_DRIFT_ENABLED': 'false',
    'OPTIBRAIN_BUSINESS_AUTO_WRITES': '0', 'OPTIBRAIN_AUTO_TEST_TASK': '0',
    'OPTIBRAIN_AUTO_TEST_PROJECT': '0', 'OPTIBRAIN_AUTO_TEST_INTERNAL': '0',
    'OPTIBRAIN_PHASE9_FORM_ENRICHMENT': 'off', 'OPTIBRAIN_PHASE9_FORM_GO_LIVE': 'off',
    'OPTIBRAIN_CRM_LEAD_WRITES': 'off', 'OPTIBRAIN_CRM_CANARY': 'off',
    'OPTIBRAIN_LEAD_CREATE_CANARY': 'off', 'OPTIBRAIN_OUTBOUND_SENDS': 'off',
    'OPTIBRAIN_SALES_DRAFTS': 'off', 'OPTICABLE_CONNECT_STANDBY_ENABLED': 'false',
    'OPTIBRAIN_ALLOW_APOLLO_CREDIT_CONSUMPTION': 'false',
}
RECEIVER_PATHS = frozenset({'/v1/automation/events', '/v1/lifecycle/leads',
                            '/v1/lifecycle/emails', '/v1/lifecycle/meetings'})


class HoldUnavailable(RuntimeError):
    """Retryable capture failure. Never contains provider bodies or secrets."""


@dataclass(frozen=True)
class IntakeHoldPolicy:
    enabled: bool = False
    max_receipts: int = 10_000
    max_database_bytes: int = 512 * 1024**2
    minimum_free_bytes: int = 12 * 1024**3

    @classmethod
    def from_environment(cls, *, execution_enabled: bool):
        mode = os.getenv('OPTIBRAIN_INTAKE_MODE', 'disabled')
        if mode not in {'disabled', 'hold-v1'}:
            raise ValueError('Unknown intake mode')
        if mode == 'disabled':
            return cls()
        if execution_enabled or any(os.getenv(k) != v for k, v in EXECUTION_OFF.items()):
            raise ValueError('Intake hold requires every execution safety flag explicitly OFF')

        def bounded(name, default, minimum, maximum):
            raw = os.getenv(name, str(default))
            if not raw.isdecimal() or not minimum <= int(raw) <= maximum:
                raise ValueError('Invalid intake storage bound: ' + name)
            return int(raw)

        return cls(True,
            bounded('OPTIBRAIN_INTAKE_MAX_RECEIPTS', 10_000, 1, 100_000),
            bounded('OPTIBRAIN_INTAKE_MAX_DATABASE_BYTES', 512 * 1024**2, 16 * 1024**2, 4 * 1024**3),
            bounded('OPTIBRAIN_INTAKE_MINIMUM_FREE_BYTES', 12 * 1024**3, 1024**3, 1024**4))


def hold_event(ledger: EventLedger, event: AutomationEvent, policy: IntakeHoldPolicy,
               *, legacy_identity: bool = False, quarantine_reason: str | None = None):
    if not policy.enabled:
        raise HoldUnavailable('Intake hold is disabled')
    try:
        if shutil.disk_usage(ledger.store.db_path.parent).free < policy.minimum_free_bytes:
            raise HoldUnavailable('Intake reserve threshold')
        with closing(ledger.store._connect()) as resource, resource as conn:
            conn.execute('PRAGMA synchronous=FULL')
            conn.execute('PRAGMA busy_timeout=5000')
            if conn.execute('PRAGMA synchronous').fetchone()[0] != 2:
                raise HoldUnavailable('Durable commit unavailable')
            conn.execute('BEGIN IMMEDIATE')
            accepted, event_id, correlation = ledger._capture(conn, event,
                legacy_identity=legacy_identity, strict_identity=True)
            if accepted:
                ledger._quarantine(conn, event_id, event.source, quarantine_reason or HOLD_REASON)
            receipts = conn.execute("SELECT COUNT(*) FROM automation_event_processing WHERE status='quarantined'").fetchone()[0]
            size = conn.execute('PRAGMA page_count').fetchone()[0] * conn.execute('PRAGMA page_size').fetchone()[0]
            wal = Path(str(ledger.store.db_path) + '-wal')
            size += wal.stat().st_size if wal.exists() else 0
            if receipts > policy.max_receipts or size > policy.max_database_bytes:
                raise HoldUnavailable('Intake capacity threshold')
            row = conn.execute('SELECT status FROM automation_event_processing WHERE event_id=?', (event_id,)).fetchone()
            result = {'accepted': accepted, 'duplicate': not accepted, 'event_id': event_id,
                      'received_event_id': event.event_id, 'correlation_id': correlation,
                      'run_ids': [], 'durable': True, 'intake_only': True,
                      'held': row['status'] == 'quarantined'}
        # The connection context has COMMITTED. A failed commit never returns a
        # success receipt. All capacity failures roll back the complete capture.
        return result
    except EventConflict:
        raise
    except (sqlite3.Error, OSError) as exc:
        raise HoldUnavailable('Durable capture unavailable') from exc


def hold_health(ledger: EventLedger, policy: IntakeHoldPolicy):
    with closing(ledger.store._connect()) as conn:
        held = conn.execute("SELECT COUNT(*),MIN(first_seen_at) FROM automation_event_processing "
                            "WHERE status='quarantined' AND last_error=?", (HOLD_REASON,)).fetchone()
        total = conn.execute("SELECT COUNT(*) FROM automation_event_processing WHERE status='quarantined'").fetchone()[0]
        size = conn.execute('PRAGMA page_count').fetchone()[0] * conn.execute('PRAGMA page_size').fetchone()[0]
    wal = Path(str(ledger.store.db_path) + '-wal')
    size += wal.stat().st_size if wal.exists() else 0
    free = shutil.disk_usage(ledger.store.db_path.parent).free
    return {'mode': 'hold-v1' if policy.enabled else 'disabled', 'held_receipts': held[0],
            'oldest_held_at': held[1], 'all_quarantined_receipts': total,
            'max_receipts': policy.max_receipts, 'database_and_wal_bytes': size,
            'max_database_bytes': policy.max_database_bytes, 'free_bytes': free,
            'minimum_free_bytes': policy.minimum_free_bytes,
            'capture_available': policy.enabled and total < policy.max_receipts
                and size < policy.max_database_bytes and free >= policy.minimum_free_bytes,
            'automatic_release': False}
