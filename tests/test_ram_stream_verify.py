"""Exercise the RAM verifier on a synthetic SQLite store larger than 384 MiB."""
import contextlib, hashlib, io, json, os, socket, sqlite3, sys, tarfile, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'ops/rebuild'))
if not (ROOT/'ops/rebuild/common.py').exists():
    sys.path.insert(0,'/opt/optibrain-rebuild-toolchain/migration-20261027/ops/rebuild')
from common import RebuildError, file_hash

SOURCE=Path(os.environ.get('OPTIBRAIN_RAM_VERIFIER_UNDER_TEST',ROOT/'ops/rebuild/ram_stream_verify.py'))

class RetainedReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='optibrain-guard-synthetic-')
        cls.root=Path(cls.tmp.name);cls.generation='20300101T000000Z'
        cls.ref=cls.root/('generation-'+cls.generation)
        cls.db=cls.ref/'database/automation.db';cls.db.parent.mkdir(parents=True)
        with sqlite3.connect(cls.db) as db:
            db.execute('PRAGMA journal_mode=OFF')
            db.execute('PRAGMA secure_delete=OFF')
            db.execute('CREATE TABLE synthetic_only (payload BLOB)')
            db.execute('INSERT INTO synthetic_only VALUES (zeroblob(?))',(400*1024**2,))
            db.execute('DELETE FROM synthetic_only')
        cls.db.chmod(0o600)
        assert cls.db.stat().st_size>384*1024**2
        cls.manifest={'backup_format_version':'1','timestamp':cls.generation,
            'files':[{'path':'database/automation.db','size':cls.db.stat().st_size,'sha256':file_hash(cls.db)}],
            'sqlite_databases':[{'backup_path':'database/automation.db'}]}
        manifest=cls.ref/'manifest.json';manifest.write_text(json.dumps(cls.manifest))
        cls.archive=cls.root/'capture.tar.gz'
        with tarfile.open(cls.archive,'w:gz') as tar:
            tar.add(cls.ref,arcname=cls.ref.name)
        cls.code=SOURCE.read_text()
    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()
    def run_verifier(self,archive,code=None):
        namespace={'__name__':'__main__','__file__':str(SOURCE)}
        old_path=list(sys.path);old_mask=os.umask(0o077)
        try:
            with tempfile.TemporaryDirectory(prefix='optibrain-guard-scratch-',dir='/dev/shm') as scratch:
                with patch.object(socket,'gethostname',return_value='vps-214ba8cd'),patch.object(sys,'argv',[str(SOURCE),str(archive),scratch]),contextlib.redirect_stdout(io.StringIO()):
                    exec(compile(code or self.code,str(SOURCE),'exec'),namespace)
                return namespace['r']
        finally:
            sys.path[:]=old_path;os.umask(old_mask)
    def alternative(self,name):
        parent=self.root/name;parent.mkdir()
        archive=parent/'capture.tar.gz';os.link(self.archive,archive)
        return archive
    def test_retained_large_database_gets_all_checks_without_extraction_scratch(self):
        result=self.run_verifier(self.archive)
        self.assertEqual(result['status'],'PASS')
        self.assertEqual(result['scratch_bytes'],0)
        self.assertEqual(result['database_snapshots_verified'],1)
        self.assertEqual(result['files_verified'],1)
        self.assertEqual(result['archive_sha256'],file_hash(self.archive))
    def test_original_reviewed_guard_reproduces_live_failure(self):
        conditional="require(use_reference or db_bytes<=384*1024**2,'snapshot_scratch_exceeds_bound')"
        old=self.code.replace(conditional,"require(db_bytes<=384*1024**2,'snapshot_scratch_exceeds_bound')")
        with self.assertRaisesRegex(RebuildError,'snapshot_scratch_exceeds_bound'):
            self.run_verifier(self.archive,old)
    def test_missing_reference_still_enforces_384MiB_scratch_cap(self):
        with self.assertRaisesRegex(RebuildError,'snapshot_scratch_exceeds_bound'):
            self.run_verifier(self.alternative('missing-reference'))
    def test_symlink_reference_is_not_a_trusted_retained_generation(self):
        archive=self.alternative('symlink-reference')
        (archive.parent/self.ref.name).symlink_to(self.ref,target_is_directory=True)
        with self.assertRaisesRegex(RebuildError,'snapshot_scratch_exceeds_bound'):
            self.run_verifier(archive)
    def test_corrupt_retained_database_fails_hash_validation(self):
        archive=self.alternative('bad-reference')
        db=archive.parent/self.ref.name/'database/automation.db';db.parent.mkdir(parents=True)
        db.write_bytes(b'SYNTHETIC CORRUPTED REFERENCE')
        with self.assertRaisesRegex(RebuildError,'staging_database_reference_mismatch'):
            self.run_verifier(archive)
    def test_symlink_retained_database_is_rejected(self):
        archive=self.alternative('symlink-database')
        db=archive.parent/self.ref.name/'database/automation.db';db.parent.mkdir(parents=True)
        db.symlink_to(self.db)
        with self.assertRaisesRegex(RebuildError,'staging_database_reference_mismatch'):
            self.run_verifier(archive)
    def test_ram_directory_guard_is_retained(self):
        with patch.object(socket,'gethostname',return_value='vps-214ba8cd'),patch.object(sys,'argv',[str(SOURCE),str(self.archive),'/tmp/not-approved-RAM']):
            with self.assertRaisesRegex(RebuildError,'verification_scratch_must_be_ram'):
                exec(compile(self.code,str(SOURCE),'exec'),{'__name__':'__main__','__file__':str(SOURCE)})

if __name__=='__main__':
    unittest.main()
