"""Expendable Mail metadata cache, fenced by the durable immutable event.

Two-day overlapping reads and a daily seven-day audit discover late/reordered
messages. A failed/incomplete scan never advances the successful scan checkpoint.
Content is revalidated daily; a changed known body is an exception, never a new
event or replacement of immutable evidence. No mutation consumer uses this cache.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json

FIELDS=('messageId','folderId','threadId','receivedTime','fromAddress','sender',
        'subject','summary','toAddress','ccAddress','hasAttachment','priority','modifiedTime')


def fingerprint(item):
    return hashlib.sha256(json.dumps({k:str(item.get(k) or '') for k in FIELDS},
                                    sort_keys=True,separators=(',',':')).encode()).hexdigest()


class MailObservationCache:
    def __init__(self,store,account,*,now=None):
        self.store,self.account=store,account
        self.now=now or datetime.now(timezone.utc)
        with store._connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS mailbox_observation_cache (
                  account TEXT NOT NULL, message_id TEXT NOT NULL, metadata_hash TEXT NOT NULL,
                  body_hash TEXT NOT NULL, checked_at TEXT NOT NULL, seen_at TEXT NOT NULL,
                  PRIMARY KEY(account,message_id));
                CREATE TABLE IF NOT EXISTS mailbox_observation_checkpoints (
                  account TEXT PRIMARY KEY, successful_at TEXT NOT NULL, full_at TEXT NOT NULL);
            ''')
            state=db.execute('SELECT successful_at,full_at FROM mailbox_observation_checkpoints WHERE account=?',(account,)).fetchone()
            self.cache={r['message_id']:dict(r) for r in db.execute('SELECT * FROM mailbox_observation_cache WHERE account=?',(account,))}
            # One lookup across the known event identities; cache loss cannot lose an event.
            rows=db.execute("SELECT e.idempotency_key,e.payload_json FROM automation_events e JOIN automation_event_ledger l ON l.event_id=e.event_id "
                            "WHERE e.source='zoho-mail-poller' AND e.event_type='customer.lifecycle.email.received' AND e.idempotency_key LIKE ?",
                            ('email:'+account+':%',)).fetchall()
        self.known={}
        for row in rows:
            payload=json.loads(row['payload_json'])
            if payload.get('mailbox_account_id')==account:
                self.known[str(payload['message_id'])]=payload
        if state and self.now-datetime.fromisoformat(state['successful_at'])>timedelta(days=7):
            raise ValueError('Mail observation gap requires reviewed bounded backfill')
        self.full_scan=not state or self.now<datetime.fromisoformat(state['full_at']) or self.now-datetime.fromisoformat(state['full_at'])>=timedelta(days=1)
        self.full_at=state['full_at'] if state else self.now.isoformat()
        self.pending={}

    def hit(self,item):
        identity=str(item['messageId']);cached=self.cache.get(identity)
        if not cached or identity not in self.known:return False
        original=self.known[identity]
        body_hash=hashlib.sha256(str(original.get('body') or '').encode()).hexdigest()
        checked=datetime.fromisoformat(cached['checked_at'])
        if (cached['metadata_hash']!=fingerprint(item) or cached['body_hash']!=body_hash
                or not timedelta(0)<=self.now-checked<timedelta(days=1)):
            return False
        self.pending[identity]=(cached['metadata_hash'],body_hash,cached['checked_at'],self.now.isoformat())
        return True

    def remember(self,item,body):
        identity=str(item['messageId'])
        original=self.known.get(identity)
        if original is not None and str(original.get('body') or '')!=body:
            raise ValueError('Known Mail content differs from immutable intake evidence')
        self.pending[identity]=(fingerprint(item),hashlib.sha256(body.encode()).hexdigest(),self.now.isoformat(),self.now.isoformat())

    def commit(self):
        with self.store._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for identity,values in self.pending.items():
                db.execute('INSERT INTO mailbox_observation_cache VALUES(?,?,?,?,?,?) ON CONFLICT(account,message_id) DO UPDATE SET '
                           'metadata_hash=excluded.metadata_hash,body_hash=excluded.body_hash,checked_at=excluded.checked_at,seen_at=excluded.seen_at',
                           (self.account,identity,*values))
            db.execute('DELETE FROM mailbox_observation_cache WHERE seen_at<?',((self.now-timedelta(days=30)).isoformat(),))
            db.execute('INSERT INTO mailbox_observation_checkpoints VALUES(?,?,?) ON CONFLICT(account) DO UPDATE SET '
                       'successful_at=excluded.successful_at,full_at=excluded.full_at',
                       (self.account,self.now.isoformat(),self.now.isoformat() if self.full_scan else self.full_at))
