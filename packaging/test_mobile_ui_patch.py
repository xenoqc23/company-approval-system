"""Verify the NAS UI updater only against disposable, fake installations."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from zipfile import ZipFile

import build_mobile_ui_patch as patch


class MobilePatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive = patch.build()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='approval-mobile-patch-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        with ZipFile(self.archive) as archive:
            archive.extractall(self.root / 'upload')
        self.stage = self.root / 'upload' / patch.NAME
        self.base = self.root / 'existing application'
        self.app = self.base / 'app'
        (self.app / 'deploy/nas').mkdir(parents=True)
        (self.app / 'manage.py').write_text('# existing application\n')
        (self.app / 'deploy/nas/nas.sh').write_text(
            '#!/bin/sh\n[ "$1" = update ] || exit 1\necho QA_UPDATE_ONLY\n')
        (self.base / '.env').write_text('PRIVATE_CONFIGURATION_SENTINEL\n')
        self.previous = 'previous desktop template\n'
        self.existing = self.app / 'workflow/templates/workflow/base.html'
        self.existing.parent.mkdir(parents=True)
        self.existing.write_text(self.previous)

    def apply(self):
        env = dict(os.environ, APPROVAL_MOBILE_BASE=str(self.base))
        return subprocess.run(['sh', str(self.stage / 'APPLY_MOBILE_UI.sh')],
                              env=env, text=True, capture_output=True)

    def test_copy_whitelist_and_backup_without_touching_configuration(self):
        result = self.apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('MOBILE_UI_READY', result.stdout)
        self.assertIn('QA_UPDATE_ONLY', result.stdout)
        for name in patch.FILES:
            self.assertEqual((self.app / name).read_bytes(), (patch.ROOT / name).read_bytes())
        backup, = self.base.glob('.mobile-ui-backup.*')
        self.assertEqual((backup / 'workflow/templates/workflow/base.html').read_text(), self.previous)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o700)
        self.assertFalse((backup / '.env').exists())
        self.assertEqual((self.base / '.env').read_text(), 'PRIVATE_CONFIGURATION_SENTINEL\n')
        self.assertFalse((self.app / 'approval_site').exists())

    def test_corrupt_upload_is_rejected_before_copying(self):
        (self.stage / 'app' / patch.FILES[0]).write_text('damaged upload')
        result = self.apply()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.existing.read_text(), self.previous)
        self.assertEqual(list(self.base.glob('.mobile-ui-backup.*')), [])

    def test_pending_recovery_is_rejected_before_copying(self):
        (self.base / '.recovery-in-progress').touch()
        result = self.apply()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('pending', result.stderr)
        self.assertEqual(self.existing.read_text(), self.previous)

    def test_missing_installation_is_not_created(self):
        (self.app / 'manage.py').unlink()
        result = self.apply()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.existing.read_text(), self.previous)
        self.assertEqual(list(self.base.glob('.mobile-ui-backup.*')), [])


if __name__ == '__main__':
    unittest.main()
