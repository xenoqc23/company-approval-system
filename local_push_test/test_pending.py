import json
import tempfile
import unittest
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock,patch
from pending import PendingStore,remind_once
from login_reminder import run
from desktop import WindowsDesktop,RUN_KEY,RUN_NAME,APP_KEY


class PendingReminderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.store=PendingStore(self.root/'pending-trial.sqlite3')
        self.desktop=Mock()

    def test_same_day_restart_restores_pending_and_each_login_reminds_until_completed(self):
        self.store.create_samples()
        first=run(self.root,login=True,desktop=self.desktop,delay=0)
        self.assertEqual(first['count'],2);self.assertEqual(first['result'],'requested')
        self.assertEqual(len(PendingStore(self.store.path).documents(pending_only=True)),2)
        second=run(self.root,login=True,desktop=self.desktop,delay=0)
        self.assertEqual(second['count'],2);self.assertEqual(self.desktop.notify.call_count,2)
        title,body=self.desktop.notify.call_args.args
        self.assertIn('2건',title);self.assertIn('홍길동 대리',body);self.assertIn('김가영 과장',body)
        self.assertEqual(self.store.status()['last_reminder']['reason'],'windows_login')

    def test_old_and_recent_documents_are_both_pending_without_date_cutoff(self):
        old=PendingStore(self.store.path,clock=lambda:1);old.create_samples()
        self.assertEqual(remind_once(self.store,self.desktop)['count'],2)
        with self.store.connect() as db:
            db.execute('UPDATE documents SET created=999999999999 WHERE id=?',('trial-leave',))
        self.assertEqual(remind_once(self.store,self.desktop)['count'],2)

    def test_completed_documents_excluded_and_empty_login_does_not_show_popup(self):
        self.store.create_samples();self.store.complete('trial-leave')
        self.assertEqual(remind_once(self.store,self.desktop)['count'],1)
        self.assertNotIn('홍길동',self.desktop.notify.call_args.args[1])
        self.store.complete('trial-purchase');self.desktop.reset_mock()
        result=run(self.root,login=True,desktop=self.desktop,delay=0)
        self.assertEqual(result['result'],'empty');self.desktop.notify.assert_not_called()

    def test_create_samples_is_explicit_reset_not_duplicate_documents(self):
        self.store.create_samples();self.store.create_samples();self.assertEqual(len(self.store.documents()),2)
        self.store.complete('trial-leave');self.store.create_samples()
        self.assertEqual(len(self.store.documents(pending_only=True)),2)

    def test_failure_recorded_and_pending_not_marked_done(self):
        self.store.create_samples();self.desktop.notify.side_effect=RuntimeError('알림 차단')
        result=remind_once(self.store,self.desktop)
        self.assertEqual(result['result'],'failed');self.assertEqual(len(self.store.documents(pending_only=True)),2)
        self.assertIn('차단',self.store.status()['last_reminder']['message'])

    def test_login_helper_needs_no_browser_or_http_server(self):
        self.store.create_samples()
        with patch('webbrowser.open') as browser,patch('socket.create_connection',side_effect=AssertionError('no network')):
            result=run(self.root,login=True,desktop=self.desktop,delay=0)
        browser.assert_not_called();self.assertEqual(result['result'],'requested')

    def test_new_helper_process_reads_remaining_documents_without_running_web_server(self):
        self.store.create_samples();self.store.complete('trial-leave')
        script='from login_reminder import run; from unittest.mock import Mock; import json,sys; print(json.dumps(run(sys.argv[1],login=True,desktop=Mock(),delay=0)))'
        result=subprocess.run([sys.executable,'-c',script,str(self.root)],cwd=Path(__file__).parent,
                              capture_output=True,text=True,check=True)
        self.assertEqual(json.loads(result.stdout)['count'],1)
        self.assertEqual(self.store.status()['last_reminder']['reason'],'windows_login')


class FakeRegistry:
    HKEY_CURRENT_USER=1
    REG_SZ=1
    REG_DWORD=4
    KEY_SET_VALUE=2
    def __init__(self):self.keys={RUN_KEY:{'OtherApplication':'unchanged'}}
    @contextmanager
    def CreateKey(self,hive,path):
        self.keys.setdefault(path,{})
        yield path
    @contextmanager
    def OpenKey(self,hive,path,*args):
        if path not in self.keys:raise FileNotFoundError
        yield path
    def QueryValueEx(self,key,name):
        if name not in self.keys[key]:raise FileNotFoundError
        return self.keys[key][name],1
    def SetValueEx(self,key,name,unused,kind,value):self.keys[key][name]=value
    def DeleteValue(self,key,name):
        if name not in self.keys[key]:raise FileNotFoundError
        del self.keys[key][name]


class DesktopIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'folder with spaces';self.root.mkdir()
        self.desktop=WindowsDesktop(self.root,self.root/'.local-test-data')
        self.registry=FakeRegistry()
        self.mock_registry=patch.dict('sys.modules',winreg=self.registry);self.mock_registry.start();self.addCleanup(self.mock_registry.stop)
        self.supported=patch.object(WindowsDesktop,'supported',new=property(lambda _:True));self.supported.start();self.addCleanup(self.supported.stop)

    def test_optin_registers_one_user_startup_value_and_disable_preserves_other_apps(self):
        with patch.object(WindowsDesktop,'command',return_value='"pythonw.exe" "folder with spaces/login_reminder.py" --login'):
            self.desktop.enable();self.desktop.enable()
        self.assertEqual(set(self.registry.keys[RUN_KEY]),{RUN_NAME,'OtherApplication'})
        self.assertIn('--login',self.registry.keys[RUN_KEY][RUN_NAME])
        self.assertIn('DisplayName',self.registry.keys[APP_KEY])
        self.desktop.disable();self.desktop.disable()
        self.assertEqual(self.registry.keys[RUN_KEY],{'OtherApplication':'unchanged'})

    def test_startup_command_handles_spaces_and_rejects_overlong_run_value_before_registration(self):
        python=self.root/'python.exe';pythonw=self.root/'pythonw.exe';pythonw.touch()
        with patch('desktop.sys.executable',str(python)):
            command=self.desktop.command()
            self.assertIn('"'+str(pythonw)+'"',command);self.assertIn('--login',command)
            self.assertNotIn('--data-dir',command)
            self.assertTrue(self.desktop.enable()['enabled'])
        self.desktop.disable()
        long=WindowsDesktop(self.root/('long-'*55),self.root/'.local-test-data')
        self.registry.keys.pop(APP_KEY,None)
        with patch('desktop.sys.executable',str(python)):
            with self.assertRaises(RuntimeError):long.enable()
        self.assertNotIn(RUN_NAME,self.registry.keys[RUN_KEY]);self.assertNotIn(APP_KEY,self.registry.keys)

    def test_native_request_passes_text_as_json_and_does_not_bypass_execution_policy(self):
        payload=[]
        def runner(command,**kwargs):
            path=Path(kwargs['env']['XENOSYS_LOCAL_TOAST_PAYLOAD'])
            payload.append((path,json.loads(path.read_text(encoding='utf-8'))))
            self.assertNotIn('-ExecutionPolicy',command);self.assertNotIn('-EncodedCommand',command)
            self.assertNotIn('shell',kwargs)
            return Mock(returncode=0)
        with (patch.object(WindowsDesktop,'powershell_path',return_value=Path('powershell.exe')),
              patch('desktop.subprocess.run',side_effect=runner)):
            self.desktop.notify('처리할 문서 2건','홍길동 · 휴가원\n김가영 · 구매요청서')
        self.assertIn('홍길동',payload[0][1]['body']);self.assertFalse(payload[0][0].exists())

    def test_native_block_is_reported_as_failure_not_display_success(self):
        with (patch.object(WindowsDesktop,'powershell_path',return_value=Path('powershell.exe')),
              patch('desktop.subprocess.run',return_value=Mock(returncode=1))):
            with self.assertRaises(RuntimeError):self.desktop.notify('제목','내용')


if __name__=='__main__':unittest.main()
