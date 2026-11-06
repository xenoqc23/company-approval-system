import json
import tempfile
from pathlib import Path
from zipfile import ZipFile
import build_nas_reviewer_access_update as release
import test_nas_purchase_update as base_tests


class ReviewerAccessReleaseTests(base_tests.NasPurchasePackageTests):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='nas-reviewer-access-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.archive=self.root/'update.zip'
        release.build(self.archive)
        with ZipFile(self.archive) as archive:
            self.assertIsNone(archive.testzip());archive.extractall(self.root/'upload')
        self.stage=self.root/'upload'/release.NAME

    def test_allowlist_manifest_and_no_local_data_or_employee_names(self):
        super().test_allowlist_manifest_and_no_local_data_or_employee_names()
        meta=json.loads((self.stage/'RELEASE.json').read_text())
        self.assertTrue(meta['schema_changes']);self.assertFalse(meta['automatic_permission_grants'])
        self.assertTrue(meta['live_pending_review_permissions']);self.assertTrue(meta['separate_leave_and_purchase_permissions'])
        self.assertFalse(meta['stock_finance_handover'])
        self.assertTrue((self.stage/'app/workflow/migrations/0021_reviewer_completion_authority.py').exists())
        expected={
            'purchasing/forms.py','purchasing/integrated_rules.py','purchasing/integration.py',
            'purchasing/progress.py','purchasing/services.py','purchasing/views.py','purchasing/urls.py',
            'purchasing/templates/purchasing/assignment_panel.html','purchasing/templates/purchasing/detail.html',
            'purchasing/templates/purchasing/regulations.html','purchasing/templates/purchasing/reviewer_authority.html',
            'purchasing/templates/purchasing/reviewer_authority_panel.html',
            'workflow/models.py','workflow/progressive.py','workflow/services.py','workflow/views.py','workflow/rollout.py',
            'workflow/migrations/0021_reviewer_completion_authority.py',
            'workflow/templates/workflow/document_actions.html','workflow/templates/workflow/integrated_rule_edit.html',
            'workflow/templates/workflow/staff.html',
            'purchasing/static/purchasing/purchase.js','workflow/templates/workflow/base.html',
            'purchasing/static/purchasing/integrated.css',
        }
        with ZipFile(release.ROOT/'releases/xenosys-nas-stock-record-update-20261102-v4.zip') as previous:
            prefix='xenosys-nas-stock-record-update-20261102-v4/app/'
            old={n[len(prefix):]:previous.read(n) for n in previous.namelist() if n.startswith(prefix)}
        current={p.relative_to(self.stage/'app').as_posix():p.read_bytes() for p in (self.stage/'app').rglob('*') if p.is_file()}
        self.assertEqual({name for name in set(old)|set(current) if old.get(name)!=current.get(name)},expected)


if __name__=='__main__':
    import unittest
    unittest.main()
