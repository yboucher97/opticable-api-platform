import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('phase14_retention',Path(__file__).resolve().parents[3]/'ops/phase14/retention.py')
retention=importlib.util.module_from_spec(spec);spec.loader.exec_module(retention)


class RetentionTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.local=Path(tmp.name)/'backup';self.spool=Path(tmp.name)/'spool'
        self.local.mkdir();self.spool.mkdir();self.old='20260926T020000Z'
        self.generations=[self.old,retention.OWNER,'20261002T020000Z','20261003T020000Z']
        audit=[]
        for generation in self.generations:
            directory=self.spool/generation;directory.mkdir()
            cipher=directory/'archive.tar.gz.age';cipher.write_bytes(('cipher '+generation).encode())
            archive=self.local/('optibrain-backup-'+generation+'.tar.gz');archive.write_bytes(('source '+generation).encode())
            digest=retention.sha(archive);archive.with_name(archive.name+'.sha256').write_text(digest+'  '+archive.name+'\n')
            key='backup/'+generation+'.age'
            manifest=directory/'prepared.json';manifest.write_text(json.dumps(dict(generation=generation,object_key=key,
                encrypted_sha256=retention.sha(cipher),source_sha256=digest)))
            audit.extend([dict(event='download_hash_verified',key=key,sha256=retention.sha(cipher)),
                          dict(event='download_hash_verified',key=key+'.json',sha256=retention.sha(manifest)),
                          dict(event='generation_verified',generation=generation)])
        (self.spool/'audit.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in audit))
    def plan(self,**kwargs):return retention.plan(self.local,self.spool,**kwargs)
    def test_deterministic_candidates_keep_owner_recent_sources_and_all_audit(self):
        first=self.plan();self.assertEqual(first,self.plan());self.assertTrue(first['coverage_verified'])
        candidates=[r for r in first['rows'] if r['action']=='DELETE CANDIDATE']
        self.assertEqual([Path(r['path']).parent.name for r in candidates],[self.old])
        self.assertTrue(all(r['action']=='KEEP' for r in first['rows'] if r['generation']==retention.OWNER))
        self.assertTrue(all(r['action']=='KEEP' for r in first['rows'] if r['classification']=='AUDIT HOLD'))
    def test_missing_owner_or_recent_ciphertext_blocks_all_deletion(self):
        (self.spool/retention.OWNER/'archive.tar.gz.age').unlink()
        self.assertFalse(self.plan()['coverage_verified'])
        self.assertFalse(any(r['action']=='DELETE CANDIDATE' for r in self.plan()['rows']))
    def test_hash_conflict_and_uncertain_verification_are_retained(self):
        path=self.spool/self.old/'archive.tar.gz.age';path.write_bytes(b'conflict')
        row=next(r for r in self.plan()['rows'] if r['path']==str(path))
        self.assertEqual(row['action'],'MANUAL REVIEW')
        (self.spool/'audit.jsonl').write_text('')
        self.assertFalse(any(r['action']=='DELETE CANDIDATE' for r in self.plan()['rows']))
    def test_execute_revalidates_before_any_delete_and_never_deletes_remote_or_evidence(self):
        report=self.plan()
        with patch.object(retention.os,'geteuid',return_value=0):
            value=retention.execute(report,local=self.local,spool=self.spool)
        self.assertEqual(value['remote_deleted'],0);self.assertEqual(value['bytes_reclaimed'],report['candidate_bytes'])
        self.assertTrue((self.spool/self.old/'prepared.json').exists());self.assertTrue((self.spool/'audit.jsonl').exists())
        self.assertEqual(len(list(self.local.glob('*.tar.gz'))),4)
    def test_changed_report_or_symlink_cannot_execute(self):
        report=self.plan();path=self.spool/self.old/'archive.tar.gz.age';path.write_bytes(b'changed')
        with patch.object(retention.os,'geteuid',return_value=0):
            with self.assertRaisesRegex(ValueError,'changed'):retention.execute(report,local=self.local,spool=self.spool)
        path.unlink();path.symlink_to(self.local/('optibrain-backup-'+self.old+'.tar.gz'))
        self.assertFalse(any(r['action']=='DELETE CANDIDATE' for r in self.plan()['rows']))


if __name__=='__main__':unittest.main()
