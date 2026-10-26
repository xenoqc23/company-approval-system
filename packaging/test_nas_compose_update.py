import unittest
import tempfile
from pathlib import Path
from zipfile import ZipFile
import build_nas_compose_update as release
import test_nas_purchase_update as base_tests


class ComposeReleaseTests(base_tests.NasPurchasePackageTests):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='nas-compose-release-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.archive=self.root/'update.zip'
        release.build(self.archive)
        with ZipFile(self.archive) as archive:
            self.assertIsNone(archive.testzip());archive.extractall(self.root/'upload')
        self.stage=self.root/'upload'/release.NAME

    def test_allowlist_manifest_and_no_local_data_or_employee_names(self):
        super().test_allowlist_manifest_and_no_local_data_or_employee_names()
        self.assertTrue((self.stage/'app/workflow/templates/workflow/unified_compose.html').exists())
        self.assertTrue((self.stage/'app/purchasing/templates/purchasing/compose_form.html').exists())
        self.assertTrue((self.stage/'app/workflow/static/workflow/unified-compose.js').exists())
        self.assertTrue((self.stage/'app/purchasing/composition.py').exists())
        self.assertIn('기존에 저장된 담당자', (self.stage/'README.md').read_text())


if __name__=='__main__':unittest.main()
