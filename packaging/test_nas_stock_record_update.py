import json
import tempfile
from pathlib import Path
from zipfile import ZipFile
import build_nas_stock_record_update as release
import test_nas_purchase_update as base_tests


class StockRecordReleaseTests(base_tests.NasPurchasePackageTests):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='nas-stock-record-release-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.archive=self.root/'update.zip'
        release.build(self.archive)
        with ZipFile(self.archive) as archive:
            self.assertIsNone(archive.testzip())
            archive.extractall(self.root/'upload')
        self.stage=self.root/'upload'/release.NAME

    def test_allowlist_manifest_and_no_local_data_or_employee_names(self):
        super().test_allowlist_manifest_and_no_local_data_or_employee_names()
        meta=json.loads((self.stage/'RELEASE.json').read_text())
        self.assertFalse(meta['schema_changes'])
        self.assertFalse(meta['stock_finance_handover'])
        self.assertTrue(meta['preserve_submitted_route_snapshots'])
        self.assertEqual(meta['base_release'],'xenosys-nas-reviewer-update-20261028-v3')
        self.assertIn('기존 담당자·권한·규정',(self.stage/'README.md').read_text())
        self.assertIn('stock_record_only=True',(self.stage/'app/workflow/delegation.py').read_text())
        self.assertIn('확인 완료',(self.stage/'app/workflow/models.py').read_text())
        with ZipFile(release.ROOT/'releases/xenosys-nas-reviewer-update-20261028-v3.zip') as previous:
            prefix='xenosys-nas-reviewer-update-20261028-v3/app/'
            old={n[len(prefix):]:previous.read(n) for n in previous.namelist() if n.startswith(prefix)}
        current={p.relative_to(self.stage/'app').as_posix():p.read_bytes() for p in (self.stage/'app').rglob('*') if p.is_file()}
        for name in old:
            if name.startswith(('purchasing/','deploy/nas/','approval_site/','workflow/migrations/')):
                self.assertEqual(current[name],old[name],name)


if __name__=='__main__':
    import unittest
    unittest.main()
