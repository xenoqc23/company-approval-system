import os,runpy,subprocess,sys,tempfile,unittest,sqlite3
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
from hashlib import sha256
import build_full_local as package

class FullBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup);cls.archive=package.build(Path(cls.temp.name)/'full.zip')
    def test_complete_source_assets_nas_tools_and_checksums(self):
        with ZipFile(self.archive) as z:
            root=package.NAME+'/';self.assertIsNone(z.testzip());names=[n[len(root):] for n in z.namelist()]
            for name in ['local_full.py','.dockerignore','requirements-nas.txt','deploy/nas/Dockerfile','deploy/nas/nas.sh','workflow/templates/workflow/staff_card.html','workflow/templates/workflow/regulations.html','workflow/backup_files.py','purchasing/migrations/0008_application_policy.py','purchasing/templates/purchasing/compose.html']:
                self.assertIn(name,names)
            for name in names:
                self.assertFalse(any(part in Path(name).parts for part in ['var','data','.env','.venv','.git','releases','__pycache__']))
                self.assertFalse(name.endswith(('.sqlite3','.db','.pem','.key','.csv')))
                source=package.ROOT/name
                if source.is_file():self.assertEqual(z.read(root+name),source.read_bytes())
            for line in z.read(root+'SHA256SUMS').decode().splitlines():
                digest,name=line.split('  ',1);self.assertEqual(sha256(z.read(root+name)).hexdigest(),digest)
            for name in ['SETUP_LOCAL_FULL.bat','RUN_LOCAL_FULL.bat','RESET_LOCAL_FULL.bat']:self.assertIn(b'\r\n',z.read(root+name))
            self.assertIn(b'COPY purchasing ./purchasing',z.read(root+'deploy/nas/Dockerfile'));self.assertIn(b'!purchasing/**',z.read(root+'.dockerignore'))
    def test_launcher_isolated_and_same_app_as_nas(self):
        module=runpy.run_path(str(package.ROOT/'local_full.py'));self.assertEqual(module['DEFAULT_PORT'],18141)
        fn=module['environment']
        with tempfile.TemporaryDirectory() as folder:
            fn.__globals__['DATA']=Path(folder)/'purchase-test'
            with patch.dict(os.environ,dict(DB_ENGINE='mariadb',APPROVAL_PRODUCTION='1',APPROVAL_DATA_DIR='real-nas',APPROVAL_BACKUP_DIR='real-backups')):env=fn()
            self.assertEqual(env['DB_ENGINE'],'sqlite');self.assertEqual(env['APPROVAL_PRODUCTION'],'0');self.assertEqual(env['APPROVAL_LOCAL_DEMO'],'1');self.assertEqual(env['APPROVAL_BACKUP_DIR'],str(Path(folder)/'purchase-test/backups'))
            code="import approval_site.settings as s; assert s.INTEGRATED_PURCHASES; assert s.LOCAL_DEMO_ENABLED; assert s.MIDDLEWARE[-1]=='workflow.middleware.AccountGateMiddleware'; assert s.SESSION_COOKIE_NAME=='xenosys_final_full_local_sessionid'"
            result=subprocess.run([sys.executable,'-c',code],cwd=package.ROOT,env=env,capture_output=True,text=True);self.assertEqual(result.returncode,0,result.stderr)
    def test_nas_mode_keeps_full_features_and_disables_demo(self):
        with tempfile.TemporaryDirectory() as folder:
            env={**os.environ,'APPROVAL_PRODUCTION':'1','APPROVAL_LOCAL_DEMO':'1','APPROVAL_PURCHASE_LAB':'1','APPROVAL_INTEGRATED_PURCHASES':'1','APPROVAL_PURCHASES_ENABLED':'1','DJANGO_DEBUG':'0','DJANGO_SECRET_KEY':'full-app-settings-check-'+'x'*64,'DJANGO_ALLOWED_HOSTS':'localhost','APPROVAL_DATA_DIR':folder,'DB_ENGINE':'mariadb','DB_NAME':'unconnected','DB_USER':'unconnected','DB_PASSWORD':'not-real'}
            code="import approval_site.settings as s; assert s.INTEGRATED_PURCHASES; assert not s.PURCHASE_LAB_ENABLED; assert not s.LOCAL_DEMO_ENABLED; assert s.SESSION_COOKIE_NAME=='xenosys_approval_sessionid'; assert 'purchasing' in s.INSTALLED_APPS"
            result=subprocess.run([sys.executable,'-c',code],cwd=package.ROOT,env=env,capture_output=True,text=True);self.assertEqual(result.returncode,0,result.stderr)
    def test_reset_only_accepts_this_marked_fictional_folder(self):
        for valid in [True,False]:
            module=runpy.run_path(str(package.ROOT/'local_full.py'));fn=module['reset'];scope=fn.__globals__
            with tempfile.TemporaryDirectory() as folder:
                root=Path(folder);data=root/'var/full-nas-test-v3/purchase-test';data.mkdir(parents=True);(data/'.purchase-lab').write_text('fake')
                if valid:(data/'.full-local').write_text('full-local-fictional-v1')
                with sqlite3.connect(data/'prototype.sqlite3') as c:c.executescript('CREATE TABLE auth_user(id integer);INSERT INTO auth_user VALUES(1);CREATE TABLE purchasing_demoaccount(user_id integer);INSERT INTO purchasing_demoaccount VALUES(1);CREATE TABLE workflow_document(id integer,owner_id integer);CREATE TABLE workflow_annualbalance(id integer,user_id integer);INSERT INTO workflow_annualbalance VALUES(1,1);')
                scope.update(ROOT=root,DATA=data)
                with patch.dict(scope,{'setup':lambda:None}):
                    if valid:fn();self.assertFalse(data.exists())
                    else:
                        with self.assertRaises(RuntimeError):fn()
                        self.assertTrue(data.exists())
if __name__=='__main__':unittest.main()
