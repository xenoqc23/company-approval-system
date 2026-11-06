import hashlib
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile
import build_local_push_trial as release


class LocalPushPackageTests(unittest.TestCase):
    def test_exact_pc_only_payload_manifests_and_windows_launcher(self):
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'test.zip';digest=release.build(target)
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(),digest)
            with ZipFile(target) as z:
                self.assertIsNone(z.testzip())
                names={n.removeprefix(release.NAME+'/') for n in z.namelist()}
                self.assertEqual(names,set(release.FILES)|{'SHA256SUMS'})
                for line in z.read(release.NAME+'/SHA256SUMS').decode().splitlines():
                    expected,name=line.split('  ',1)
                    self.assertEqual(hashlib.sha256(z.read(release.NAME+'/'+name)).hexdigest(),expected)
                self.assertIn(b'\r\n',z.read(release.NAME+'/START_TEST.bat'))
                for name in names:
                    self.assertFalse(name.endswith(('.pem','.key','.sqlite3','.env')))
                    self.assertNotIn('workflow/',name);self.assertNotIn('purchasing/',name)
            with self.assertRaises(FileExistsError):release.build(target)


if __name__=='__main__':unittest.main()
