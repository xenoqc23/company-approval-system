"""Run the NAS updater only against disposable, fake installations."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from zipfile import ZipFile

import build_manual_leave_patch as patch


class ManualLeavePatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive = patch.build()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='approval-manual-patch-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        with ZipFile(self.archive) as archive:
            archive.extractall(self.root / 'upload')
        self.stage = self.root / 'upload' / patch.NAME
        self.base = self.root / 'existing application'
        self.app = self.base / 'app'
        (self.app / 'deploy/nas').mkdir(parents=True)
        (self.app / 'manage.py').write_text('# existing application\n')
        self.nas = self.app / 'deploy/nas/nas.sh'
        self.nas.write_text('#!/bin/sh\n[ "$1" = update ] || exit 1\necho QA_UPDATE_ONLY\n')
        (self.base / '.env').write_text('PRIVATE_CONFIGURATION_SENTINEL\n')
        self.existing = self.app / 'workflow/models.py'
        self.existing.parent.mkdir(parents=True)
        self.existing.write_text('previous model source\n')
        self.annual = self.app / 'workflow/annual_grants.py'
        self.annual.write_text('original annual grant calculation\n')

    def apply(self):
        env = dict(os.environ, APPROVAL_MANUAL_LEAVE_BASE=str(self.base))
        return subprocess.run(['sh', str(self.stage / 'APPLY_MANUAL_LEAVE.sh')], env=env, text=True, capture_output=True)

    def test_whitelist_backup_schema_addition_and_original_annual_settings_preserved(self):
        result = self.apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('MANUAL_LEAVE_READY', result.stdout)
        self.assertIn('QA_UPDATE_ONLY', result.stdout)
        for name in patch.FILES:
            self.assertEqual((self.app / name).read_bytes(), (patch.ROOT / name).read_bytes())
        backup, = self.base.glob('.manual-leave-backup.*')
        self.assertEqual((backup / 'workflow/models.py').read_text(), 'previous model source\n')
        self.assertEqual(backup.stat().st_mode & 0o777, 0o700)
        self.assertIn('workflow/migrations/0010_manualleaveusage.py', (backup / 'NEW_FILES.txt').read_text())
        self.assertEqual(self.annual.read_text(), 'original annual grant calculation\n')
        self.assertEqual((self.base / '.env').read_text(), 'PRIVATE_CONFIGURATION_SENTINEL\n')
        self.assertFalse((backup / '.env').exists())
        self.assertNotIn('workflow/annual_grants.py', patch.FILES)
        self.assertFalse((self.app / 'workflow/migrations/0011_calendar_year_leave_grants.py').exists())

    def test_corrupt_archive_file_fails_before_mutation(self):
        (self.stage / 'app' / patch.FILES[0]).write_text('corrupted upload')
        self.assertNotEqual(self.apply().returncode, 0)
        self.assertEqual(self.existing.read_text(), 'previous model source\n')
        self.assertFalse(list(self.base.glob('.manual-leave-backup.*')))

    def test_pending_update_or_recovery_rejected(self):
        for marker in ['.pending-image', '.operation.lock', '.recovery-in-progress']:
            path = self.base / marker
            path.touch()
            result = self.apply()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('pending', result.stderr)
            path.unlink()
        self.assertEqual(self.existing.read_text(), 'previous model source\n')

    def test_missing_installation_rejected(self):
        (self.app / 'manage.py').unlink()
        self.assertNotEqual(self.apply().returncode, 0)
        self.assertFalse(list(self.base.glob('.manual-leave-backup.*')))

    def test_failed_update_retains_backup_and_never_prints_ready(self):
        self.nas.write_text('#!/bin/sh\nexit 7\n')
        result = self.apply()
        self.assertEqual(result.returncode, 7)
        self.assertNotIn('MANUAL_LEAVE_READY', result.stdout)
        backup, = self.base.glob('.manual-leave-backup.*')
        self.assertTrue((backup / 'workflow/models.py').exists())
        self.assertEqual((self.base / '.env').read_text(), 'PRIVATE_CONFIGURATION_SENTINEL\n')


if __name__ == '__main__':
    unittest.main()
