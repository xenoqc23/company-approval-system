"""Apply the release only to disposable installations with data/config sentinels."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from zipfile import ZipFile
import build_reviewer_authority_patch as patch


class ReviewerAuthorityPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive = patch.build()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='approval-birthday-installer-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        with ZipFile(self.archive) as archive:
            archive.extractall(self.root / 'upload')
        self.stage = self.root / 'upload' / patch.NAME
        self.base = self.root / 'existing application'
        self.app = self.base / 'app'
        for folder in ['deploy/nas', 'workflow', 'workflow/migrations']:
            (self.app / folder).mkdir(parents=True, exist_ok=True)
        self.protected = {
            'manage.py':'# existing\n',
            'workflow/migrations/0011_hire_year_monthly.py':'# existing predecessor\n',
            'workflow/migrations/0011_existing.py':'# existing migration\n',
        }
        for name, text in self.protected.items():
            (self.app / name).write_text(text)
        (self.app / 'workflow/manual_leave.py').write_text('# existing manual leave\n')
        (self.app / 'deploy/nas/nas.sh').write_text(
            '#!/bin/sh\n# backup_name=$(run_manage backup_database --kind update)\n[ "$1" = update ] || exit 1\necho QA_UPDATE_ONLY\n')
        (self.base / '.env').write_text('PRIVATE_CONFIGURATION_SENTINEL\n')
        (self.base / 'data').mkdir()
        (self.base / 'data/existing-db').write_bytes(b'EXISTING_DATABASE_SENTINEL')
        self.existing = self.app / patch.FILES[0]
        self.existing.write_text('previous display code\n')

    def apply(self):
        return subprocess.run(['sh', str(self.stage / 'APPLY_REVIEWER_AUTHORITY.sh')],
            env=dict(os.environ, APPROVAL_REVIEWER_AUTHORITY_BASE=str(self.base)), text=True, capture_output=True)

    def test_only_whitelisted_display_files_replaced_backed_up_and_data_untouched(self):
        result = self.apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('REVIEWER_AUTHORITY_READY', result.stdout)
        self.assertIn('QA_UPDATE_ONLY', result.stdout)
        for name in patch.FILES:
            self.assertEqual((self.app / name).read_bytes(), (patch.ROOT / name).read_bytes())
        backup, = self.base.glob('.reviewer-authority-backup.*')
        self.assertEqual((backup / patch.FILES[0]).read_text(), 'previous display code\n')
        self.assertEqual(backup.stat().st_mode & 0o777, 0o700)
        for name, text in self.protected.items():
            self.assertEqual((self.app / name).read_text(), text)
        self.assertEqual((self.base / '.env').read_text(), 'PRIVATE_CONFIGURATION_SENTINEL\n')
        self.assertEqual((self.base / 'data/existing-db').read_bytes(), b'EXISTING_DATABASE_SENTINEL')
        self.assertEqual([name for name in patch.FILES if '/migrations/' in name], ['workflow/migrations/0012_simplified_approval.py', 'workflow/migrations/0013_common_rule_deletion.py', 'workflow/migrations/0014_hire_year_tenure.py', 'workflow/migrations/0015_employee_birthdays.py', 'workflow/migrations/0016_representative_account.py', 'workflow/migrations/0017_progressive_approval.py', 'workflow/migrations/0018_reviewer_final_authority.py'])
        self.assertIn('workflow/annual_grants.py',patch.FILES)
        self.assertIn('korean-lunar-calendar==0.4.0',(self.app / 'requirements-prototype.txt').read_text())
        self.assertNotIn('workflow/migrations/0011_hire_year_monthly.py',patch.FILES)

    def test_corrupt_upload_rejected_before_mutation(self):
        (self.stage / 'app' / patch.FILES[0]).write_text('damaged')
        self.assertNotEqual(self.apply().returncode, 0)
        self.assertEqual(self.existing.read_text(), 'previous display code\n')
        self.assertEqual(list(self.base.glob('.reviewer-authority-backup.*')), [])

    def test_each_pending_operation_blocks_copy(self):
        for marker in ['.pending-image', '.recovery-in-progress', '.operation.lock']:
            with self.subTest(marker=marker):
                path = self.base / marker
                path.touch()
                self.assertNotEqual(self.apply().returncode, 0)
                self.assertEqual(self.existing.read_text(), 'previous display code\n')
                path.unlink()

    def test_manual_feature_missing_rejected(self):
        (self.app / 'workflow/manual_leave.py').unlink()
        self.assertNotEqual(self.apply().returncode, 0)
        self.assertEqual(self.existing.read_text(), 'previous display code\n')

    def test_missing_schema_predecessor_is_rejected_before_copy(self):
        (self.app / 'workflow/migrations/0011_hire_year_monthly.py').unlink()
        self.assertNotEqual(self.apply().returncode,0)
        self.assertEqual(self.existing.read_text(),'previous display code\n')

    def test_installer_without_database_backup_rejected(self):
        (self.app / 'deploy/nas/nas.sh').write_text('echo no-backup\n')
        self.assertNotEqual(self.apply().returncode, 0)
        self.assertEqual(self.existing.read_text(), 'previous display code\n')

    def test_update_failure_keeps_source_backup_and_does_not_claim_success(self):
        (self.app / 'deploy/nas/nas.sh').write_text('# backup_name=$(run_manage backup_database --kind update)\nexit 29\n')
        result = self.apply()
        self.assertEqual(result.returncode, 29)
        self.assertNotIn('REVIEWER_AUTHORITY_READY', result.stdout)
        backup, = self.base.glob('.reviewer-authority-backup.*')
        self.assertEqual((backup / patch.FILES[0]).read_text(), 'previous display code\n')


if __name__ == '__main__':
    unittest.main()
