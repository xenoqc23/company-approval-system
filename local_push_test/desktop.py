"""Opt-in, per-user Windows startup and native toast integration."""
import json
import os
import subprocess
import sys
import tempfile
import platform
from pathlib import Path

APP_ID = 'Xenosys.LocalNotificationTrial'
RUN_NAME = 'XenosysLocalPendingTrial'
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
APP_KEY = 'Software\\Classes\\AppUserModelId\\' + APP_ID
DISPLAY_NAME = '사내결재 PC 알림 테스트'

TOAST_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$stage = 'runtime'
$setting = 'unknown'
try {
    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] > $null
    [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime] > $null
    $stage = 'payload'
    $data = Get-Content -LiteralPath $env:XENOSYS_LOCAL_TOAST_PAYLOAD -Raw -Encoding UTF8 | ConvertFrom-Json
    $stage = 'notifier'
    $notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Xenosys.LocalNotificationTrial')
    $stage = 'settings'
    $setting = [string]$notifier.Setting
    if ($data.mode -eq 'diagnose') {
        [pscustomobject]@{ok=$true; stage='diagnose'; setting=$setting} | ConvertTo-Json -Compress
        exit 0
    }
    if ($setting -ne 'Enabled') {
        [pscustomobject]@{ok=$false; stage=$stage; setting=$setting; error_type='NotificationDisabled'; hresult=''} | ConvertTo-Json -Compress
        exit 2
    }
    $stage = 'xml'
    $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
    $xml.LoadXml([string]$data.xml)
    $stage = 'show'
    $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
    $toast.Tag = [guid]::NewGuid().ToString('N').Substring(0, 16)
    $toast.Group = 'local-trial'
    $toast.SuppressPopup = $false
    $notifier.Show($toast)
    [pscustomobject]@{ok=$true; stage=$stage; setting=$setting} | ConvertTo-Json -Compress
    exit 0
} catch {
    $failure = $_.Exception
    while ($failure.InnerException) { $failure = $failure.InnerException }
    $code = '0x{0:X8}' -f $failure.HResult
    [pscustomobject]@{ok=$false; stage=$stage; setting=$setting; error_type=$failure.GetType().FullName; hresult=$code} | ConvertTo-Json -Compress
    exit 1
}
'''


class WindowsDesktop:
    def __init__(self, root, data_dir):
        self.root, self.data_dir = Path(root).resolve(), Path(data_dir).resolve()

    @property
    def supported(self):
        return os.name == 'nt'

    def require_windows(self):
        if not self.supported:
            raise RuntimeError('PC 로그인 알림은 Windows 10·11에서 시험할 수 있습니다.')

    def command(self):
        pythonw = Path(sys.executable).with_name('pythonw.exe')
        if not pythonw.is_file():
            raise RuntimeError('Python의 pythonw.exe가 필요합니다. START_TEST.bat으로 다시 실행해 주세요.')
        args = [str(pythonw), str(self.root / 'login_reminder.py'), '--login']
        if self.data_dir != self.root / '.local-test-data':
            args += ['--data-dir', str(self.data_dir)]
        command = subprocess.list2cmdline(args)
        if len(command) > 260:
            raise RuntimeError('테스트 폴더 경로가 너무 깁니다. 더 짧은 경로로 옮긴 뒤 자동 알림을 다시 켜 주세요.')
        return command

    def status(self):
        if not self.supported:
            return dict(supported=False, enabled=False, message='Windows 10·11 PC에서 자동 알림을 설정할 수 있습니다.')
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                command = winreg.QueryValueEx(key, RUN_NAME)[0]
            exists = str(self.root / 'login_reminder.py').casefold() in command.casefold()
            return dict(supported=True, enabled=exists,
                        message='이 폴더의 PC 로그인 자동 알림이 등록됐습니다. Windows 시작 앱 설정에서도 사용으로 되어 있어야 실행됩니다.' if exists else 'PC 로그인 자동 알림이 꺼져 있거나 다른 테스트 폴더가 등록되어 있습니다.')
        except FileNotFoundError:
            return dict(supported=True, enabled=False, message='PC 로그인 자동 알림이 꺼져 있습니다.')

    def register_app(self):
        self.require_windows()
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, APP_KEY) as key:
            winreg.SetValueEx(key, 'DisplayName', 0, winreg.REG_SZ, DISPLAY_NAME)
            winreg.SetValueEx(key, 'ShowInSettings', 0, winreg.REG_DWORD, 1)

    def enable(self):
        self.require_windows()
        command = self.command()
        self.register_app()
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, command)
        return self.status()

    def disable(self):
        self.require_windows()
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, RUN_NAME)
        except FileNotFoundError:
            pass
        return self.status()

    def notify(self, title, body):
        self.require_windows()
        self.register_app()
        from toast_content import reminder_xml
        result = self.call_windows(dict(mode='notify', xml=reminder_xml(title,body,
                                        '확인은 알림만 닫습니다. 문서는 별도로 처리해 주세요.')))
        if not result.get('ok'):
            text = self.failure_message(result)
            raise RuntimeError(text)
        return result

    @staticmethod
    def failure_message(result):
        return ('Windows 알림 요청 실패 · 단계: ' + str(result.get('stage', 'unknown')) +
                ' · 오류: ' + str(result.get('hresult') or result.get('error_type', 'unknown')) +
                ' · 알림 설정: ' + str(result.get('setting', 'unknown')) +
                '. 아래 ‘Windows 알림 상태 확인’ 결과를 확인해 주세요.')

    def read_setting(self, path, name, machine=False):
        import winreg
        hive = winreg.HKEY_LOCAL_MACHINE if machine else winreg.HKEY_CURRENT_USER
        try:
            with winreg.OpenKey(hive, path) as key:
                value = winreg.QueryValueEx(key, name)[0]
                return value if isinstance(value, int) else None
        except OSError:
            return None

    def diagnose(self):
        if not self.supported:
            return dict(supported=False, message='Windows PC에서 확인해 주세요.')
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APP_KEY):
                registered = True
        except OSError:
            registered = False
        base = r'Software\Microsoft\Windows\CurrentVersion'
        policy = r'Software\Policies\Microsoft\Windows\CurrentVersion\PushNotifications'
        return dict(supported=True, windows=platform.win32_ver()[1], app_registered=registered,
            global_toasts=self.read_setting(base + r'\PushNotifications', 'ToastEnabled'),
            app_toasts=self.read_setting(base + '\\Notifications\\Settings\\' + APP_ID, 'Enabled'),
            user_policy=self.read_setting(policy, 'NoToastApplicationNotification'),
            machine_policy=self.read_setting(policy, 'NoToastApplicationNotification', machine=True),
            native=self.call_windows({'mode': 'diagnose'}))

    def call_windows(self, payload):
        self.require_windows()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        fd, filename = tempfile.mkstemp(prefix='.toast-', suffix='.json', dir=self.data_dir)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False)
            env = os.environ.copy()
            env['XENOSYS_LOCAL_TOAST_PAYLOAD'] = filename
            # Use the Windows system binary; never change execution policies.
            powershell = self.powershell_path()
            result = subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-STA', '-Command', TOAST_SCRIPT],
                                    env=env, capture_output=True, timeout=20,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                answer = json.loads(result.stdout.decode('utf-8-sig').strip())
                if not isinstance(answer, dict):
                    raise ValueError
                if result.returncode:
                    answer['ok'] = False
                return answer
            except (ValueError, UnicodeError):
                details = result.stderr.decode('utf-8', errors='replace')
                for path, label in [(self.data_dir, '[TEST_DATA]'), (self.root, '[TEST_FOLDER]')]:
                    details = details.replace(str(path), label)
                return dict(ok=False, stage='powershell_process', setting='unknown',
                            error_type='NoStructuredResult', exit_code=result.returncode, details=details[:1200])
        except subprocess.TimeoutExpired:
            return dict(ok=False, stage='powershell_process', setting='unknown', error_type='Timeout')
        finally:
            Path(filename).unlink(missing_ok=True)

    def powershell_path(self):
        import ctypes
        system_dir = ctypes.create_unicode_buffer(32768)
        if not ctypes.windll.kernel32.GetSystemDirectoryW(system_dir, len(system_dir)):
            raise RuntimeError('Windows 시스템 경로를 확인하지 못했습니다.')
        return Path(system_dir.value) / 'WindowsPowerShell/v1.0/powershell.exe'
