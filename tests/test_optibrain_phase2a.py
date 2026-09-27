import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from botocore.exceptions import ClientError
from botocore.response import StreamingBody

spec = importlib.util.spec_from_file_location('uploader', Path(__file__).resolve().parents[1] / 'ops/backup/optibrain-phase2a-upload.py')
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)

class S3:
    def __init__(self):
        self.objects = {}
        self.puts = 0
        self.denied = False
        self.corrupt = False
        self.crash_after_put = False
    def head_object(self, Bucket, Key):
        if self.denied or Key not in self.objects:
            status = 403 if self.denied else 404
            raise ClientError({'ResponseMetadata': {'HTTPStatusCode': status}, 'Error': {'Code': str(status)}}, 'HeadObject')
        data, meta = self.objects[Key]
        return {'Metadata': meta, 'ContentLength': len(data), 'ETag': 'fixture'}
    def put_object(self, Bucket, Key, Body, Metadata, **kwargs):
        if Key in self.objects:
            raise AssertionError('overwrite attempted')
        self.puts += 1
        self.objects[Key] = (Body.read(), Metadata)
        if self.crash_after_put:
            self.crash_after_put = False
            raise ConnectionError('ambiguous completed upload')
    def get_object(self, Bucket, Key, **kwargs):
        data = self.objects[Key][0]
        if self.corrupt:
            data = b'!' + data[1:]
        return {'Body': StreamingBody(io.BytesIO(data), len(data))}

class UploadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.archive = self.root / 'optibrain-backup-20260927T010000Z.tar.gz'
        self.archive.write_bytes(b'sensitive fixture')
        self.archive.with_name(self.archive.name + '.sha256').write_text(u.sha(self.archive) + ' archive\n')
        self.client = S3()
        self.encryptions = 0
    def subprocess(self, args, **kwargs):
        if args[0] == 'age':
            self.encryptions += 1
            Path(args[args.index('-o')+1]).write_bytes(b'age-encryption.org/v1\n-> randomized-' + str(self.encryptions).encode())
    def run_upload(self):
        with patch.object(u.subprocess, 'run', self.subprocess):
            u.run(self.client, self.archive, 'age1publicfixture', self.root, Path('/fixture-verifier'))
    def test_ambiguous_upload_resumes_same_ciphertext(self):
        self.client.crash_after_put = True
        with self.assertRaises(ConnectionError): self.run_upload()
        self.assertFalse((self.root / 'state.json').exists())
        self.run_upload()
        self.run_upload()
        self.assertEqual(self.encryptions, 1)
        self.assertEqual(self.client.puts, 2)
        self.assertEqual(json.loads((self.root/'state.json').read_text())['verification_status'], 'download_hash_verified')
    def test_denied_head_never_writes(self):
        self.client.denied = True
        with self.assertRaises(ClientError): self.run_upload()
        self.assertEqual(self.client.puts, 0)
    def test_download_corruption_never_records_success(self):
        self.client.corrupt = True
        with self.assertRaises(RuntimeError): self.run_upload()
        self.assertFalse((self.root/'state.json').exists())
        self.assertEqual(self.client.puts, 1)
    def test_changed_source_cannot_overwrite(self):
        self.run_upload()
        self.archive.write_bytes(b'changed')
        self.archive.with_name(self.archive.name+'.sha256').write_text(u.sha(self.archive))
        with self.assertRaises(RuntimeError): self.run_upload()
        self.assertEqual(self.client.puts, 2)
    def test_conditional_put_header(self):
        params={'headers':{}}
        u.create_only_header(params)
        self.assertEqual(params['headers']['If-None-Match'], '*')
    def test_bad_checksum_never_encrypts_or_writes(self):
        self.archive.write_bytes(b'corrupt')
        with self.assertRaises(RuntimeError): self.run_upload()
        self.assertEqual(self.encryptions, 0)
        self.assertEqual(self.client.puts, 0)

if __name__ == '__main__': unittest.main()
