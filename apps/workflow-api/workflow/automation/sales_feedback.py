"""Local, append-only shadow review feedback; never provider suppression authority."""
import json
import re
import sqlite3
from .sales_intelligence import FEEDBACK, key


class SalesFeedback:
    def __init__(self, path):
        self.path = str(path)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.execute('CREATE TABLE IF NOT EXISTS sales_shadow_feedback (identity TEXT PRIMARY KEY, prospect TEXT NOT NULL, version TEXT NOT NULL, choice TEXT NOT NULL, actor TEXT NOT NULL, at TEXT NOT NULL)')
        return db

    def record(self, candidate, version, choice, actor, now):
        if not re.fullmatch('[0-9a-f]{64}',str(candidate.get('key',''))) or candidate.get('version') != version:
            raise ValueError('Fresh displayed candidate required')
        if choice not in FEEDBACK or not actor or len(actor)>200 or now.tzinfo is None:
            raise ValueError('Invalid shadow review')
        identity = key([candidate['key'],version,choice,actor])
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO sales_shadow_feedback VALUES (?,?,?,?,?,?)',
                       (identity,candidate['key'],version,choice,actor,now.isoformat()))
        return {'state':'SHADOW REVIEW RECORDED','choice':choice,'provider_writes':0,
                'apollo_changed':False,'cold_send_enabled':False}

    def latest(self):
        try:
            with sqlite3.connect('file:'+self.path+'?mode=ro',uri=True,timeout=5) as db:
                rows = db.execute('SELECT prospect,choice,actor,at FROM sales_shadow_feedback ORDER BY at, rowid').fetchall()
        except sqlite3.OperationalError:
            return {}
        result = {}
        for prospect,choice,actor,at in rows:
            # A later GOOD cannot silently undo local do-not-contact feedback.
            if result.get(prospect,{}).get('choice') == 'DO NOT CONTACT':continue
            result[prospect] = dict(choice=choice,actor=actor,at=at)
        return result
