import tempfile
from pathlib import Path
from zipfile import ZipFile
import build_nas_reviewer_update as release
import test_nas_purchase_update as base_tests


class ReviewerReleaseTests(base_tests.NasPurchasePackageTests):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='nas-reviewer-release-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root / 'update.zip'
        release.build(self.archive)
        with ZipFile(self.archive) as archive:
            self.assertIsNone(archive.testzip())
            archive.extractall(self.root / 'upload')
        self.stage = self.root / 'upload' / release.NAME

    def test_allowlist_manifest_and_no_local_data_or_employee_names(self):
        super().test_allowlist_manifest_and_no_local_data_or_employee_names()
        expected_changes = {
            'app/workflow/views.py',
            'app/workflow/templates/workflow/detail.html',
            'app/workflow/templates/workflow/document_actions.html',
            'app/workflow/static/workflow/simplified-approval.css',
            'app/workflow/rollout.py',
            'app/purchasing/templates/purchasing/detail.html',
        }
        current = {p.relative_to(self.stage).as_posix(): p.read_bytes() for p in (self.stage / 'app').rglob('*') if p.is_file()}
        with ZipFile(release.ROOT / 'releases/xenosys-nas-compose-update-20261026-v2.zip') as previous:
            prefix = 'xenosys-nas-compose-update-20261026-v2/'
            old = {name[len(prefix):]: previous.read(name) for name in previous.namelist() if name.startswith(prefix + 'app/')}
        changed = {name for name in set(old) | set(current) if old.get(name) != current.get(name)}
        self.assertEqual(changed, expected_changes)
        self.assertIn('기존 담당자·권한·규정', (self.stage / 'README.md').read_text())


if __name__ == '__main__':
    import unittest
    unittest.main()
