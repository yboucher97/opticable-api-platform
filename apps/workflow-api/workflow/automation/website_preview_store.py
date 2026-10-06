"""Additive observations in the shared journal; immutable proposals stay intact."""
from copy import deepcopy
import json
from .optimization_store import OptimizationStore
from .acquisition_store import AcquisitionStore, digest
from .website_preview_model import RepositoryState, validate_preview_state, approval_current


class WebsitePreviewStore(OptimizationStore):
    def preview_setup(self, db):
        # No alterations to canonical proposal/source tables. Rollback is simply
        # disabling consumers; optional DROP applies only to these two tables.
        db.executescript('''
        CREATE TABLE IF NOT EXISTS website_preview_observations (
          proposal_id TEXT NOT NULL, revision INTEGER NOT NULL, sequence INTEGER NOT NULL,
          proposal_hash TEXT NOT NULL, fingerprint TEXT NOT NULL, at TEXT NOT NULL, value TEXT NOT NULL,
          PRIMARY KEY(proposal_id,revision,sequence));
        CREATE TABLE IF NOT EXISTS website_preview_webhooks (
          event_id TEXT PRIMARY KEY, repository TEXT NOT NULL, kind TEXT NOT NULL,
          payload_hash TEXT NOT NULL, at TEXT NOT NULL, value TEXT NOT NULL);
        ''')

    def website_proposal(self, proposal_id):
        item=next((r for r in self.rows() if r['record']['proposal_id']==proposal_id),None)
        if not item or item['record']['target_system']!='WEBSITE':raise ValueError('Known website proposal required')
        return item

    def save_preview(self, value, *, expected_sequence=None):
        value=deepcopy(validate_preview_state(value));raw=json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False)
        with self.connect() as db:
            self.preview_setup(db);db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT revision,payload_hash,detail,record FROM optimization_records WHERE kind='optibrain.optimization_proposal' AND id=? ORDER BY revision DESC LIMIT 1",(value['proposal_id'],)).fetchone()
            if not row or json.loads(row['record'])['target_system']!='WEBSITE' or row['revision']!=value['proposal_revision'] or row['payload_hash']!=value['proposal_hash'] or json.loads(row['detail']).get('repository')!=value['repository']:
                raise ValueError('Canonical proposal/revision/repository mismatch')
            prior=db.execute('SELECT * FROM website_preview_observations WHERE proposal_id=? AND revision=? ORDER BY sequence DESC LIMIT 1',(value['proposal_id'],value['proposal_revision'])).fetchone()
            seq=prior['sequence'] if prior else 0
            if expected_sequence is not None and seq!=expected_sequence:raise ValueError('Concurrent preview update')
            if prior and prior['fingerprint']==digest(value):return seq
            db.execute('INSERT INTO website_preview_observations VALUES (?,?,?,?,?,?,?)',
                (value['proposal_id'],value['proposal_revision'],seq+1,value['proposal_hash'],digest(value),value['updated_at'],raw))
        return seq+1

    def preview(self, proposal_id, now):
        item=self.website_proposal(proposal_id);r=item['record']
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='website_preview_observations'").fetchone():return None
            row=db.execute('SELECT * FROM website_preview_observations WHERE proposal_id=? ORDER BY revision DESC,sequence DESC LIMIT 1',(proposal_id,)).fetchone()
            if not row:return None
            v=json.loads(row['value']);v['sequence']=row['sequence']
            if v['proposal_revision']!=r['revision'] or v['proposal_hash']!=item['payload_hash']:
                v.update(state='SUPERSEDED',stale_state='SUPERSEDED',owner_status='STALE_APPROVAL',preview_state='STALE')
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='manager_feedback'").fetchone():
                feedback=db.execute("SELECT * FROM manager_feedback WHERE kind='PROPOSAL' AND target=? ORDER BY at DESC,rowid DESC LIMIT 1",(proposal_id,)).fetchone()
                if feedback:
                    f=json.loads(feedback['value']);v['approval']=f.get('website_preview_approval')
                    if feedback['choice']=='APPROVE':v['owner_status']='APPROVED' if feedback['version']==item['payload_hash'] and approval_current(v,now) else 'STALE_APPROVAL'
                    elif feedback['version']==item['payload_hash']:
                        v['owner_status']={'REQUEST_REVISION':'REVISION_REQUESTED','REJECT':'REJECTED','WAIT':'DEFERRED'}.get(feedback['choice'],'PENDING')
            if v['owner_status']=='APPROVED' and not approval_current(v,now):v['owner_status']='STALE_APPROVAL'
            if v['owner_status'] in {'APPROVED','REVISION_REQUESTED','REJECTED','DEFERRED'}:v['state']=v['owner_status']
            return v

    def repository_state(self, value, now):
        value=value.value()
        # Reuse SOURCE entities and acquisition facts, not a parallel registry.
        return AcquisitionStore(self.path).record('SOURCE',value,source='website',native_id=value['repository_id'],
            url='https://github.com/'+value['repository_full_name'],now=now,observed_at=value['source_at'])

    def repository_states(self):
        rows=AcquisitionStore(self.path).view('SOURCE');result=[]
        for r in rows:
            facts=[f for f in r['facts'] if f['source']=='website' and 'repository_id' in f['normalized_value']]
            if facts:
                value=max(facts,key=lambda f:(f['retrieved_at'],f['id']))['normalized_value'];RepositoryState(**value).value();result.append(value)
        return result

    def accept_webhook(self, event, now):
        with self.connect() as db:
            self.preview_setup(db);db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM website_preview_webhooks WHERE event_id=?',(event['event_id'],)).fetchone():raise ValueError('Webhook replay')
            db.execute('INSERT INTO website_preview_webhooks VALUES (?,?,?,?,?,?)',
                (event['event_id'],event['repository'],event['kind'],event['payload_hash'],now.isoformat(),json.dumps(event)))
        return {'state':'ACCEPTED','execution_authorized':False,'provider_writes':0}
