import os,runpy,subprocess,sys,tempfile,unittest,sqlite3
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
from hashlib import sha256
import build_integrated_local as package

class IntegratedBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup);cls.archive=package.build(Path(cls.temp.name)/'test.zip')
    def test_sources_assets_checksums_and_private_exclusions(self):
        with ZipFile(self.archive) as z:
            self.assertIsNone(z.testzip());root=package.NAME+'/'
            names=[n[len(root):] for n in z.namelist()]
            for n in ['local_integrated.py','workflow/templates/workflow/dashboard.html','purchasing/integration.py','purchasing/templates/purchasing/inbox_tabs.html','purchasing/management/commands/seed_integrated_demo.py','workflow/static/workflow/mobile.js','workflow/static/workflow/images/mint-rest.png','workflow/static/workflow/notifications.js']:
                self.assertIn(n,names)
            for n in names:
                self.assertFalse(any(p in Path(n).parts for p in ['var','data','.env','.venv','.git','deploy','releases','__pycache__']))
                self.assertFalse(n.endswith(('.db','.sqlite3','.key','.pem','.csv')))
                source=package.ROOT/n
                if source.is_file():self.assertEqual(z.read(root+n),source.read_bytes(),n)
            for row in z.read(root+'SHA256SUMS').decode().splitlines():
                digest,name=row.split('  ',1);self.assertEqual(sha256(z.read(root+name)).hexdigest(),digest)
            for n in ['SETUP_LOCAL_INTEGRATED.bat','RUN_LOCAL_INTEGRATED.bat','RESET_LOCAL_INTEGRATED.bat']:
                self.assertIn(b'\r\n',z.read(root+n));self.assertIn(b'local_integrated.py',z.read(root+n))
    def test_forced_sqlite_data_path_and_distinct_cookies(self):
        module=runpy.run_path(str(package.ROOT/'local_integrated.py'));self.assertEqual(module['DEFAULT_PORT'],18117)
        fn=module['environment']
        with tempfile.TemporaryDirectory() as folder:
            fn.__globals__['DATA']=Path(folder)/'purchase-test'
            with patch.dict(os.environ,dict(DB_ENGINE='mariadb',APPROVAL_PRODUCTION='1',APPROVAL_DATA_DIR='nas-data',APPROVAL_WEBPUSH_ENABLED='1',APPROVAL_BACKUP_DIR='other-app-backups')):env=fn()
            self.assertEqual(env['APPROVAL_BACKUP_DIR'],str(Path(folder)/'purchase-test'/'backups'));self.assertEqual(env['DB_ENGINE'],'sqlite');self.assertEqual(env['APPROVAL_PRODUCTION'],'0');self.assertEqual(env['APPROVAL_WEBPUSH_ENABLED'],'0');self.assertEqual(env['APPROVAL_INTEGRATED_PURCHASES'],'1')
            code="import approval_site.settings as s; assert s.INTEGRATED_PURCHASES; assert s.SESSION_COOKIE_NAME=='xenosys_integrated_local_sessionid'; assert s.CSRF_COOKIE_NAME=='xenosys_integrated_local_csrftoken'; assert s.MIDDLEWARE[-1]=='workflow.middleware.AccountGateMiddleware'"
            r=subprocess.run([sys.executable,'-c',code],cwd=package.ROOT,env=env,capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stderr)
    def test_production_cannot_activate_integrated_preview(self):
        with tempfile.TemporaryDirectory() as folder:
            env={**os.environ,'APPROVAL_INTEGRATED_PURCHASES':'1','APPROVAL_PURCHASE_LAB':'1','APPROVAL_PRODUCTION':'1','DJANGO_DEBUG':'0','DB_ENGINE':'mariadb','DB_NAME':'unconnected-test','DB_USER':'unconnected','DB_PASSWORD':'not-real','DJANGO_SECRET_KEY':'settings-check-only-'+'x'*64,'DJANGO_ALLOWED_HOSTS':'localhost','APPROVAL_DATA_DIR':folder}
            code="import approval_site.settings as s; assert s.INTEGRATED_PURCHASES; assert not s.PURCHASE_LAB_ENABLED; assert 'purchasing' in s.INSTALLED_APPS; assert not s.LOCAL_DEMO_ENABLED"
            r=subprocess.run([sys.executable,'-c',code],cwd=package.ROOT,env=env,capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stderr)
    def make_data(self,root,foreign=False):
        data=root/'var/integrated-test/purchase-test';data.mkdir(parents=True);(data/'.purchase-lab').write_text('purchase-lab-v1');(data/'.integrated-lab').write_text('integrated-local-fictional-v1')
        with sqlite3.connect(data/'prototype.sqlite3') as c:
            c.executescript('CREATE TABLE auth_user(id integer);INSERT INTO auth_user VALUES(1);CREATE TABLE purchasing_demoaccount(user_id integer);INSERT INTO purchasing_demoaccount VALUES(1);CREATE TABLE workflow_document(id integer,owner_id integer);INSERT INTO workflow_document VALUES(1,1);CREATE TABLE workflow_annualbalance(id integer,user_id integer);INSERT INTO workflow_annualbalance VALUES(1,1);')
            if foreign:c.execute('INSERT INTO auth_user VALUES(2)')
        return data
    def test_reset_allows_only_marked_own_fictional_documents_and_balances(self):
        module=runpy.run_path(str(package.ROOT/'local_integrated.py'));fn=module['reset'];scope=fn.__globals__
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);data=self.make_data(root);other=root/'keep';other.write_text('keep');scope.update(ROOT=root,DATA=data)
            with patch.dict(scope,{'setup':lambda:None}):fn()
            self.assertFalse(data.exists());self.assertEqual(other.read_text(),'keep')
    def test_reset_refuses_foreign_users_unmarked_or_running_data(self):
        for scenario in ['foreign','unmarked','running']:
            module=runpy.run_path(str(package.ROOT/'local_integrated.py'));fn=module['reset'];scope=fn.__globals__
            with tempfile.TemporaryDirectory() as folder:
                root=Path(folder);data=self.make_data(root,foreign=scenario=='foreign');scope.update(ROOT=root,DATA=data)
                if scenario=='unmarked':(data/'.integrated-lab').unlink()
                if scenario=='running':(data/'running.json').write_text('{"port":18117}')
                with patch.dict(scope,{'setup':lambda:None}),patch.object(scope['socket'],'create_connection'):
                    with self.assertRaises(RuntimeError):fn()
                self.assertTrue((data/'prototype.sqlite3').exists())
if __name__=='__main__':unittest.main()
