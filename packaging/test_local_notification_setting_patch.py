import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile
import build_local_notification_setting_patch as patch_release


class SettingPatchTests(unittest.TestCase):
    def test_overlay_is_small_and_preserves_existing_v2_v3_v4_runtime_and_data(self):
        archives=['xenosys-local-pc-notification-test-20261106-v2',
                  'xenosys-local-pc-notification-test-20261106-v3',
                  'xenosys-local-pc-notification-test-20261109-v4']
        with tempfile.TemporaryDirectory() as temp:
            temp=Path(temp);patch_file=temp/'patch.zip';patch_release.build(patch_file)
            with ZipFile(patch_file) as patch_zip:
                self.assertEqual(set(patch_zip.namelist()),{'desktop.py','toast_content.py','READ_ME_PATCH.txt','PATCH_SHA256SUMS.txt'})
                for line in patch_zip.read('PATCH_SHA256SUMS.txt').decode().splitlines():
                    digest,name=line.split('  ',1)
                    self.assertEqual(hashlib.sha256(patch_zip.read(name)).hexdigest(),digest)
                for name in archives:
                    with self.subTest(version=name):
                        target=temp/name
                        with ZipFile(patch_release.ROOT/'releases'/(name+'.zip')) as old:
                            old.extractall(target)
                        stage=target/name
                        sentinel=stage/'.venv'/'preserve.txt';sentinel.parent.mkdir();sentinel.write_text('preserved runtime')
                        original_server=(stage/'server.py').read_bytes()
                        patch_zip.extractall(stage)
                        self.assertEqual((stage/'server.py').read_bytes(),original_server)
                        self.assertEqual(sentinel.read_text(),'preserved runtime')
                        script='''import json
from pathlib import Path
from unittest.mock import Mock,patch
from desktop import WindowsDesktop
from pending import PendingStore,remind_once
store=PendingStore(Path('.local-test-data/pending-trial.sqlite3'));store.create_samples()
desktop=WindowsDesktop(Path.cwd(),Path('.local-test-data'))
with (patch.object(WindowsDesktop,'supported',new=property(lambda _:True)),
      patch.object(WindowsDesktop,'register_app'),
      patch.object(WindowsDesktop,'powershell_path',return_value=Path('powershell.exe')),
      patch('desktop.subprocess.run',return_value=Mock(returncode=0,stdout=b'{"ok":true,"stage":"show","setting":""}',stderr=b''))):
    result=remind_once(store,desktop)
assert result['result']=='requested',result
assert store.status()['pending_count']==2
print(json.dumps(result))
'''
                        completed=subprocess.run([sys.executable,'-c',script],cwd=stage,capture_output=True,text=True,check=True)
                        self.assertEqual(json.loads(completed.stdout)['result'],'requested')
            with self.assertRaises(FileExistsError):patch_release.build(patch_file)


if __name__=='__main__':unittest.main()
