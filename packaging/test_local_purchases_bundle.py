import os,runpy,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
from hashlib import sha256
import build_local_purchases as package


class PurchaseBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.archive=package.build()

    def test_bundle_runtime_sources_checksums_and_private_exclusions(self):
        with ZipFile(self.archive) as z:
            self.assertIsNone(z.testzip())
            names=[n[len(package.NAME)+1:] for n in z.namelist()]
            self.assertIn('purchasing/migrations/0001_initial_purchase_lab.py',names)
            self.assertIn('purchasing/templates/purchasing/regulations.html',names)
            self.assertIn('local_purchases.py',names)
            for name in names:
                self.assertFalse(any(x in Path(name).parts for x in ['var','data','.env','.venv','.git','releases','deploy','__pycache__']),name)
                self.assertFalse(name.endswith(('.sqlite3','.db','.key','.pem')),name)
                source=package.ROOT/name
                if source.is_file():self.assertEqual(z.read(package.NAME+'/'+name),source.read_bytes(),name)
            for row in z.read(package.NAME+'/SHA256SUMS').decode().splitlines():
                digest,name=row.split('  ',1);self.assertEqual(sha256(z.read(package.NAME+'/'+name)).hexdigest(),digest)
            for name in ['SETUP_LOCAL_PURCHASES.bat','RUN_LOCAL_PURCHASES.bat']:
                content=z.read(package.NAME+'/'+name);self.assertIn(b'\r\n',content);self.assertIn(b'local_purchases.py',content)
            script=z.read(package.NAME+'/local_purchases.py').decode()
            self.assertIn('seed_purchase_demo',script);self.assertNotIn("'seed_demo'",script)
            self.assertNotIn('init_webpush',script);self.assertNotIn('run_webpush',script)

    def test_launcher_forces_separate_sqlite_and_cookies_not_nas_env(self):
        module=runpy.run_path(str(package.ROOT/'local_purchases.py'))
        envfn=module['environment']
        with tempfile.TemporaryDirectory() as folder:
            envfn.__globals__['DATA']=Path(folder)/'purchase-test'
            with patch.dict(os.environ,dict(DB_ENGINE='mariadb',APPROVAL_PRODUCTION='1',APPROVAL_DATA_DIR='existing-nas-data',APPROVAL_WEBPUSH_ENABLED='1')):
                env=envfn()
            self.assertEqual(env['DB_ENGINE'],'sqlite');self.assertEqual(env['APPROVAL_PRODUCTION'],'0')
            self.assertEqual(env['APPROVAL_PURCHASE_LAB'],'1');self.assertEqual(env['APPROVAL_WEBPUSH_ENABLED'],'0')
            self.assertEqual(env['APPROVAL_DATA_DIR'],str(Path(folder)/'purchase-test'))
            self.assertGreaterEqual(len(env['DJANGO_SECRET_KEY']),50)

    def test_production_never_enables_purchase_lab(self):
        with tempfile.TemporaryDirectory() as folder:
            env={**os.environ,'APPROVAL_PURCHASE_LAB':'1','APPROVAL_PRODUCTION':'1','DJANGO_DEBUG':'0',
                 'DJANGO_SECRET_KEY':'isolated-settings-check-only-'+'x'*64,'DB_ENGINE':'mariadb','DB_NAME':'unconnected-test',
                 'DB_USER':'unconnected-test','DB_PASSWORD':'not-a-real-password','DJANGO_ALLOWED_HOSTS':'localhost',
                 'APPROVAL_DATA_DIR':folder}
            code="import approval_site.settings as s; assert not s.PURCHASE_LAB_ENABLED; assert 'purchasing' not in s.INSTALLED_APPS; assert s.SESSION_COOKIE_NAME=='xenosys_approval_sessionid'; print('Production guard verified without connecting to any database.')"
            result=subprocess.run([sys.executable,'-c',code],cwd=package.ROOT,env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_wrong_data_directory_cannot_activate_lab(self):
        with tempfile.TemporaryDirectory() as folder:
            env={**os.environ,'APPROVAL_PURCHASE_LAB':'1','APPROVAL_PRODUCTION':'0','DB_ENGINE':'sqlite','APPROVAL_DATA_DIR':folder}
            result=subprocess.run([sys.executable,'-c','import approval_site.settings'],cwd=package.ROOT,env=env,capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0);self.assertIn('purchase-test',result.stderr)


if __name__=='__main__':unittest.main()
