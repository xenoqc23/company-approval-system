"""Opt-in, per-user Windows startup and native toast integration."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

APP_ID = 'Xenosys.LocalNotificationTrial'
RUN_NAME = 'XenosysLocalPendingTrial'
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
APP_KEY = 'Software\\Classes\\AppUserModelId\\' + APP_ID
DISPLAY_NAME = '사내결재 PC 알림 테스트'

TOAST_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime] > $null
$data = Get-Content -LiteralPath $env:XENOSYS_LOCAL_TOAST_PAYLOAD -Raw -Encoding UTF8 | ConvertFrom-Json
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml('<toast duration="long"><visual><binding template="ToastGeneric"><text></text><text></text><text></text></binding></visual></toast>')
$nodes = $xml.GetElementsByTagName('text')
$nodes.Item(0).InnerText = [string]$data.title
$nodes.Item(1).InnerText = [string]$data.body
$nodes.Item(2).InnerText = '가상 문서입니다. 확인: START_TEST.bat 실행'
$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Xenosys.LocalNotificationTrial')
if ([string]$notifier.Setting -ne 'Enabled') { throw 'Windows notification setting is disabled.' }
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
$toast.Tag = [guid]::NewGuid().ToString('N').Substring(0, 16)
$toast.Group = 'local-trial'
$toast.SuppressPopup = $false
$notifier.Show($toast)
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
        self.data_dir.mkdir(parents=True, exist_ok=True)
        fd, filename = tempfile.mkstemp(prefix='.toast-', suffix='.json', dir=self.data_dir)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(dict(title=title, body=body), f, ensure_ascii=False)
            env = os.environ.copy()
            env['XENOSYS_LOCAL_TOAST_PAYLOAD'] = filename
            # Use the Windows system binary; never change execution policies.
            powershell = self.powershell_path()
            result = subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-Command', TOAST_SCRIPT],
                                    env=env, capture_output=True, timeout=20,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if result.returncode:
                raise RuntimeError('Windows 알림 표시 요청에 실패했습니다. 알림 설정에서 ‘사내결재 PC 알림 테스트’를 허용하고 방해 금지를 확인해 주세요.')
        except subprocess.TimeoutExpired:
            raise RuntimeError('Windows 알림 요청 시간이 초과됐습니다. 실행 결과를 확인해 주세요.') from None
        finally:
            Path(filename).unlink(missing_ok=True)

    def powershell_path(self):
        import ctypes
        system_dir = ctypes.create_unicode_buffer(32768)
        if not ctypes.windll.kernel32.GetSystemDirectoryW(system_dir, len(system_dir)):
            raise RuntimeError('Windows 시스템 경로를 확인하지 못했습니다.')
        return Path(system_dir.value) / 'WindowsPowerShell/v1.0/powershell.exe'
