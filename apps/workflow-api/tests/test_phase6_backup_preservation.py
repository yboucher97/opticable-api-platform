"""Real backup primitive in a tiny temporary repository; no production paths."""
import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]

class BackupPreservationTests(unittest.TestCase):
    def test_preserve_existing_never_prunes_verified_or_historical_generations(self):
        with tempfile.TemporaryDirectory(prefix='phase6-backup-fixture-') as temporary:
            root = Path(temporary)
            repo = root / 'repo'
            repo.mkdir()
            subprocess.run(['/usr/bin/git', 'init', '-q', str(repo)], check=True)
            api = repo / 'apps/workflow-api/workflow/api.py'
            api.parent.mkdir(parents=True)
            api.write_text('API_VERSION = "1.11.0"\n')
            subprocess.run(['/usr/bin/git', '-C', str(repo), 'add', '.'], check=True)
            subprocess.run(['/usr/bin/git', '-C', str(repo), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.test', 'commit', '-qm', 'fixture'], check=True)
            database = root / 'fixture.db'
            with sqlite3.connect(database) as connection:
                connection.execute('CREATE TABLE fixture (id INTEGER)')
            environment = root / 'fixture.env'
            environment.write_text('OPTICABLE_AUTOMATION_DB_PATH=' + str(database) + '\n')
            destination = root / 'backups'
            destination.mkdir()
            originals = {}
            for day in range(1, 8):
                archive = destination / ('optibrain-backup-202609%02dT000000Z.tar.gz' % day)
                archive.write_bytes(b'protected historical fixture ' + str(day).encode())
                sidecar = Path(str(archive) + '.sha256')
                sidecar.write_text(hashlib.sha256(archive.read_bytes()).hexdigest() + '  ' + archive.name + '\n')
                originals[archive] = archive.read_bytes()
                originals[sidecar] = sidecar.read_bytes()
            binaries = root / 'bin'
            binaries.mkdir()
            logger = binaries / 'logger'
            logger.write_text('#!/bin/sh\nexit 0\n')
            logger.chmod(0o700)
            variables = {'PATH': str(binaries) + ':/usr/bin:/bin', 'LANG': 'C.UTF-8',
                         'OPTIBRAIN_REPO_DIR': str(repo), 'OPTIBRAIN_BACKUP_CONFIG': str(root/'absent.conf'),
                         'OPTIBRAIN_BACKUP_DIR': str(destination), 'OPTIBRAIN_WORKFLOW_ENV_FILE': str(environment),
                         'OPTIBRAIN_SKIP_LIVE_STATE': 'true', 'OPTIBRAIN_SKIP_LIVE_CONFIG': 'true'}
            result = subprocess.run(['/bin/bash', str(ROOT/'ops/backup/optibrain-backup.sh'), '--preserve-existing', '--retention', '1'],
                                    env=variables, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            for path, content in originals.items():
                with self.subTest(path=path.name):
                    self.assertEqual(path.read_bytes(), content)
            self.assertEqual(len(list(destination.glob('optibrain-backup-*.tar.gz'))), 8)
            self.assertFalse(list(destination.glob('.staging-*')))
