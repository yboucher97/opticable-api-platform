import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('drill', Path(__file__).resolve().parents[1] / 'ops/backup/optibrain-restore-drill.py')
drill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(drill)

class ExtractionSafety(unittest.TestCase):
    def test_unsafe_members_rejected_before_extraction(self):
        for name, symlink in [('../escape', False), ('/absolute', False), ('link', True)]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                archive = root/'test.tar.gz'
                target = root/'target'
                target.mkdir()
                with tarfile.open(archive, 'w:gz') as t:
                    member = tarfile.TarInfo(name)
                    if symlink:
                        member.type = tarfile.SYMTYPE
                        member.linkname = '/etc'
                        t.addfile(member)
                    else:
                        member.size = 1
                        t.addfile(member, io.BytesIO(b'x'))
                with self.assertRaises(drill.DrillError): drill.extract(archive, target)
                self.assertEqual(list(target.iterdir()), [])
    def test_checksum_failure_creates_no_staging(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root/'invalid'
            archive.write_bytes(b'not the verified archive')
            with self.assertRaises(drill.DrillError): drill.validate(archive, '0'*64, root)
            self.assertEqual(list(root.iterdir()), [archive])

if __name__ == '__main__': unittest.main()
