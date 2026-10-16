"""Verify source backup and explicit annual-rule payload in disposable NAS folders."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from zipfile import ZipFile

import build_new_entrant_leave_patch as patch


class NewEntrantPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive = patch.build()

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='approval-entrant-patch-')
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        with ZipFile(self.archive) as archive:
            archive.extractall(root / 'upload')
        self.stage = root / 'upload' / patch.NAME
        self.base = root / 'existing application'
        self.app = self.base / 'app'
        (self.app / 'deploy/nas').mkdir(parents=True)
        (self.app / 'workflow').mkdir()
        (self.app / 'manage.py').write_text('# existing installation\n')
        self.nas = self.app / 'deploy/nas/nas.sh'
        self.nas.write_text('#!/bin/sh\n[ "$1" = update ] || exit 1\necho QA_UPDATE_ONLY\n')
        (self.app / 'workflow/annual_grants.py').write_text('# previous grant rules\n')
        (self.base / '.env').write_text('PRIVATE_CONFIGURATION_SENTINEL\n')

    def apply(self):
        return subprocess.run(['sh',str(self.stage / 'APPLY_NEW_ENTRANT_LEAVE.sh')],
            env=dict(os.environ, APPROVAL_NEW_ENTRANT_BASE=str(self.base)),capture_output=True,text=True)

    def test_exact_payload_backup_and_private_configuration_preservation(self):
        result = self.apply()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('NEW_ENTRANT_LEAVE_READY',result.stdout)
        self.assertIn('workflow/migrations/0011_hire_year_monthly.py',patch.FILES)
        self.assertIn('workflow/templates/workflow/new_entrant_rule.html',patch.FILES)
        for name in patch.FILES:
            self.assertEqual((self.app / name).read_bytes(),(patch.ROOT / name).read_bytes())
        backup, = self.base.glob('.new-entrant-leave-backup.*')
        self.assertEqual((backup / 'workflow/annual_grants.py').read_text(),'# previous grant rules\n')
        self.assertEqual(backup.stat().st_mode & 0o777,0o700)
        self.assertEqual((self.base / '.env').read_text(),'PRIVATE_CONFIGURATION_SENTINEL\n')
        self.assertFalse((backup / '.env').exists())

    def test_pending_operations_or_corrupt_upload_rejected_before_replacing_source(self):
        for marker in ['.pending-image','.operation.lock','.recovery-in-progress']:
            (self.base / marker).touch()
            self.assertNotEqual(self.apply().returncode,0)
            (self.base / marker).unlink()
        (self.stage / 'app/workflow/migrations/0011_hire_year_monthly.py').write_text('corrupt upload')
        self.assertNotEqual(self.apply().returncode,0)
        self.assertEqual((self.app / 'workflow/annual_grants.py').read_text(),'# previous grant rules\n')
        self.assertFalse(list(self.base.glob('.new-entrant-leave-backup.*')))

    def test_update_failure_keeps_original_rules_backup_without_ready_marker(self):
        self.nas.write_text('#!/bin/sh\nexit 7\n')
        result = self.apply()
        self.assertEqual(result.returncode,7)
        self.assertNotIn('NEW_ENTRANT_LEAVE_READY',result.stdout)
        backup, = self.base.glob('.new-entrant-leave-backup.*')
        self.assertTrue((backup / 'workflow/annual_grants.py').exists())


if __name__ == '__main__':
    unittest.main()
