import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('phase14_sampler',Path(__file__).resolve().parents[3]/'ops/phase14/runtime_snapshot.py')
sampler=importlib.util.module_from_spec(spec);spec.loader.exec_module(sampler)


class ObserverResolutionTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.producer=self.root/'producer.py';self.producer.write_text('reviewed source')
        self.db=self.root/'events.db';self.receipt=self.root/'receipt.json'
        with sqlite3.connect(self.db) as db:
            db.executescript('CREATE TABLE automation_runs(run_id,status,workflow_id);CREATE TABLE automation_run_steps(run_id,action,error);')
            db.executemany('INSERT INTO automation_runs VALUES(?,?,?)',[
                ('read','failed','opticable.crm.lead-observe'),('write','failed','opticable.crm.lead-reconcile'),
                ('unrelated','failed','opticable.crm.lead-observe')])
            db.executemany('INSERT INTO automation_run_steps VALUES(?,?,?)',[
                ('read','crm.lead.observe','EventConflict'),('write','crm.lead.reconcile','EventConflict'),
                ('unrelated','crm.lead.observe','AuthenticationError')])
        self.value=dict(schema=1,provider_mutations=0,new_events=0,producer_sha256=hashlib.sha256(self.producer.read_bytes()).hexdigest(),
                        run_ids=['read','write','unrelated'])
    def resolve(self):
        self.receipt.write_text(json.dumps(self.value))
        return sampler.resolved_read_reviews(self.receipt,self.producer,self.db)
    def test_only_exact_read_only_conflict_is_acknowledged_and_original_failure_remains(self):
        self.assertEqual(self.resolve(),['read'])
        with sqlite3.connect(self.db) as db:self.assertEqual(db.execute("SELECT status FROM automation_runs WHERE run_id='read'").fetchone()[0],'failed')
    def test_changed_producer_or_incomplete_proof_never_acknowledges_failures(self):
        for field,value in [('producer_sha256','f'*64),('provider_mutations',1),('new_events',1),('schema',2),('run_ids',['read','read']),('run_ids',list(map(str,range(21))))]:
            original=self.value.copy();self.value[field]=value
            with self.subTest(field=field):self.assertEqual(self.resolve(),[])
            self.value=original
        self.producer.write_text('different source')
        self.assertEqual(self.resolve(),[])


if __name__=='__main__':unittest.main()
