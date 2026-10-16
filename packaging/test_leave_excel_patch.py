"""Validate the combined Excel/manual-leave updater using fake installations only."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from zipfile import ZipFile

import build_leave_excel_patch as patch


class LeaveExcelPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive = patch.build()

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='approval-excel-patch-')
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
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
        (self.app / 'workflow/exports.py').write_text('# previous exports\n')
        (self.app / 'workflow/annual_grants.py').write_text('# original annual calculation\n')
        (self.base / '.env').write_text('PRIVATE_CONFIGURATION_SENTINEL\n')

    def apply(self):
        return subprocess.run(['sh',str(self.stage / 'APPLY_LEAVE_EXCEL.sh')],
            env=dict(os.environ, APPROVAL_LEAVE_EXCEL_BASE=str(self.base)), capture_output=True, text=True)

    def test_combined_payload_backup_and_original_grants_configuration_preserved(self):
        result = self.apply()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('LEAVE_EXCEL_READY',result.stdout)
        for name in patch.FILES:
            self.assertEqual((self.app / name).read_bytes(),(patch.ROOT / name).read_bytes())
        self.assertIn('workflow/manual_leave.py',patch.FILES)
        self.assertIn('workflow/migrations/0010_manualleaveusage.py',patch.FILES)
        backup, = self.base.glob('.leave-excel-backup.*')
        self.assertEqual((backup / 'workflow/exports.py').read_text(),'# previous exports\n')
        self.assertEqual(backup.stat().st_mode & 0o777,0o700)
        self.assertEqual((self.app / 'workflow/annual_grants.py').read_text(),'# original annual calculation\n')
        self.assertEqual((self.base / '.env').read_text(),'PRIVATE_CONFIGURATION_SENTINEL\n')

    def test_corrupt_export_or_pending_recovery_is_rejected_before_copy(self):
        for marker in ['.pending-image','.recovery-in-progress','.operation.lock']:
            (self.base / marker).touch()
            self.assertNotEqual(self.apply().returncode,0)
            (self.base / marker).unlink()
        (self.stage / 'app/workflow/exports.py').write_text('corrupt upload')
        self.assertNotEqual(self.apply().returncode,0)
        self.assertEqual((self.app / 'workflow/exports.py').read_text(),'# previous exports\n')
        self.assertFalse(list(self.base.glob('.leave-excel-backup.*')))

    def test_update_failure_keeps_backup_and_does_not_report_ready(self):
        self.nas.write_text('#!/bin/sh\nexit 7\n')
        result = self.apply()
        self.assertEqual(result.returncode,7)
        self.assertNotIn('LEAVE_EXCEL_READY',result.stdout)
        self.assertEqual(len(list(self.base.glob('.leave-excel-backup.*'))),1)


if __name__ == '__main__':
    unittest.main()
