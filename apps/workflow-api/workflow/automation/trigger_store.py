"""Durable rebuildable trigger versions in the existing acquisition SQLite store."""
import json
from datetime import timedelta
from .acquisition_store import AcquisitionStore, digest, safe
from .sales_intelligence import stamp


class TriggerStore(AcquisitionStore):
    MAX_CURRENT = 2000

    def initialize(self):
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS acquisition_trigger_current (
              id TEXT PRIMARY KEY, source TEXT NOT NULL, source_record_id TEXT NOT NULL,
              version_id TEXT NOT NULL, version_at TEXT NOT NULL, first_observed_at TEXT NOT NULL,
              last_verified_at TEXT NOT NULL, record TEXT NOT NULL,
              UNIQUE(source, source_record_id));
            CREATE TABLE IF NOT EXISTS acquisition_trigger_versions (
              id TEXT PRIMARY KEY, trigger_id TEXT NOT NULL REFERENCES acquisition_trigger_current(id),
              source_version TEXT NOT NULL, version_at TEXT NOT NULL, retrieved_at TEXT NOT NULL,
              raw TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS acquisition_trigger_versions_trigger ON acquisition_trigger_versions(trigger_id, version_at);
            ''')

    def upsert(self, record, *, now):
        self.initialize(); safe(record)
        if record.get('test_only') is True or record.get('evidence_kind') == 'FIXTURE':
            return {'state': 'TEST EXCLUDED', 'provider_writes': 0}
        if not all(record.get(k) for k in ('source_provider', 'source_record_id', 'source_url', 'source_version', 'last_verified_at')):
            raise ValueError('Trigger provenance required')
        if not record['source_url'].startswith('https://') or not stamp(record['last_verified_at']):
            raise ValueError('Trigger provenance invalid')
        source, rid = record['source_provider'], str(record['source_record_id'])
        tid = digest([source, rid]); record = {**record, 'trigger_id': tid}
        # Verification timestamps are not changes or new triggers.
        content = {k: v for k, v in record.items() if k not in {'last_verified_at', 'retrieved_at', 'first_observed_at'}}
        vid = digest(content); version_at = record.get('source_version_at') or record.get('publish_date')
        if not stamp(version_at): raise ValueError('Aware source version date required')
        version_at = stamp(version_at).isoformat()
        raw = json.dumps(record, sort_keys=True, ensure_ascii=False)
        if len(raw.encode()) > 131072: raise ValueError('Trigger exceeds record bound')
        with self.connect() as db:
            old = db.execute('SELECT * FROM acquisition_trigger_current WHERE id=?', (tid,)).fetchone()
            if not old and db.execute('SELECT count(*) FROM acquisition_trigger_current').fetchone()[0] >= self.MAX_CURRENT:
                return {'state': 'CAPACITY HELD', 'provider_writes': 0}
            if old and stamp(old['version_at']) > stamp(version_at):
                return {'state': 'OLDER VERSION HELD', 'id': tid, 'provider_writes': 0}
            first = old['first_observed_at'] if old else now.isoformat()
            record['first_observed_at'] = first
            if old:
                db.execute('UPDATE acquisition_trigger_current SET version_id=?,version_at=?,last_verified_at=?,record=? WHERE id=?',
                           (vid, version_at, record['last_verified_at'], json.dumps(record, ensure_ascii=False), tid))
            else:
                db.execute('INSERT INTO acquisition_trigger_current VALUES (?,?,?,?,?,?,?,?)',
                           (tid, source, rid, vid, version_at, first, record['last_verified_at'], json.dumps(record, ensure_ascii=False)))
            db.execute('INSERT OR IGNORE INTO acquisition_trigger_versions VALUES (?,?,?,?,?,?)',
                       (vid, tid, record['source_version'], version_at, now.isoformat(), raw))
            return {'state': 'NEW' if not old else 'REPLAY' if old['version_id'] == vid else 'UPDATED', 'id': tid, 'provider_writes': 0}

    def records(self):
        self.initialize()
        with self.connect() as db:
            rows = db.execute('SELECT record FROM acquisition_trigger_current ORDER BY first_observed_at DESC,id LIMIT ?', (self.MAX_CURRENT,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def version_count(self):
        with self.connect() as db:
            return db.execute('SELECT count(*) FROM acquisition_trigger_versions').fetchone()[0]

    def prune_triggers(self, now):
        with self.connect() as db:
            # Retire only dated terminal research after a year. Active/unresolved
            # records are never silently evicted to make room for new research.
            obsolete = [r['id'] for r in db.execute('SELECT id,record FROM acquisition_trigger_current')
                        if (lambda row: row.get('status') in {'CLOSED','EXPIRED','CANCELLED','AWARDED','COMPLETED'} and
                            stamp(row.get('source_version_at')) and stamp(row['source_version_at']) < now-timedelta(days=365))(json.loads(r['record']))]
            for tid in obsolete:
                db.execute('DELETE FROM acquisition_trigger_versions WHERE trigger_id=?', (tid,))
                db.execute('DELETE FROM acquisition_trigger_current WHERE id=?', (tid,))
            # Preserve the current version and the twelve newest versions. Historical
            # phase receipts/recovery archives remain immutable outside the projection.
            db.execute('''DELETE FROM acquisition_trigger_versions WHERE id NOT IN
              (SELECT version_id FROM acquisition_trigger_current) AND retrieved_at < ? AND id NOT IN
              (SELECT id FROM (SELECT id, row_number() OVER (PARTITION BY trigger_id ORDER BY version_at DESC,retrieved_at DESC) n
                FROM acquisition_trigger_versions) WHERE n<=12)''', ((now-timedelta(days=90)).isoformat(),))
