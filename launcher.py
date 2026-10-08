"""PC 시안 설치/실행 도우미. 실제 NAS 설정과 별개로 로컬 테스트 DB를 사용합니다."""
import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import venv
import webbrowser

ROOT = Path(__file__).resolve().parent
PYTHON = ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def local_environment():
    env = os.environ.copy()
    env.update({
        'DB_ENGINE': 'sqlite',
        'APPROVAL_DATA_DIR': str(ROOT / 'var'),
        'DJANGO_SETTINGS_MODULE': 'approval_site.settings',
        'DJANGO_ALLOWED_HOSTS': '127.0.0.1,localhost,testserver',
        'DJANGO_DEBUG': '1',
        'PYTHONUTF8': '1',
        'PYTHONUNBUFFERED': '1',
    })
    return env


def command(*args):
    subprocess.run([str(PYTHON), *args], cwd=ROOT, env=local_environment(), check=True)


def setup():
    if sys.version_info < (3, 10):
        raise RuntimeError('Python 3.10 이상이 필요합니다. Python을 새 버전으로 설치해 주세요.')
    print('\n[1/4] 실행 환경을 준비합니다.', flush=True)
    if not PYTHON.is_file():
        venv.EnvBuilder(with_pip=True).create(ROOT / '.venv')
    # An interrupted first setup can leave python.exe without pip. Repair that
    # environment before installing dependencies instead of skipping it.
    pip_check = subprocess.run([str(PYTHON), '-m', 'pip', '--version'],
                               cwd=ROOT, env=local_environment(), capture_output=True)
    if pip_check.returncode != 0:
        print('이전에 중단된 실행 환경의 설치 도구(pip)를 복구합니다.', flush=True)
        command('-m', 'ensurepip', '--upgrade')
    print('\n[2/4] 필요한 프로그램을 설치합니다. 처음에는 인터넷 연결이 필요합니다.', flush=True)
    command('-m', 'pip', 'install', '-r', 'requirements-prototype.txt')
    print('\n[3/4] PC용 테스트 데이터베이스를 준비합니다.', flush=True)
    command('manage.py', 'migrate', '--noinput')
    print('\n[4/4] 예시 직원과 문서를 준비합니다.', flush=True)
    print('처음 설치할 때 초기 비밀번호를 입력합니다. 입력한 글자는 화면에 표시되지 않습니다.', flush=True)
    command('manage.py', 'seed_demo')
    command('manage.py', 'check')
    print('\n설치가 완료되었습니다! 이 창을 닫고 run.bat을 더블클릭해 주세요.', flush=True)
    print('Mac/Linux에서는 python3 launcher.py run 명령으로 실행합니다.', flush=True)


def run(port, open_browser):
    if not PYTHON.is_file() or not (ROOT / 'var/prototype.sqlite3').is_file():
        raise RuntimeError('먼저 setup.bat을 실행해 설치를 완료해 주세요. Mac/Linux: python3 launcher.py setup')
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(('127.0.0.1', port))
        except OSError as exc:
            raise RuntimeError(f'{port}번 포트를 이미 사용 중입니다. 이전 시안 실행 창을 닫은 뒤 다시 실행해 주세요.') from exc
    address = f'http://127.0.0.1:{port}/'
    process = subprocess.Popen([str(PYTHON), 'manage.py', 'runserver', f'127.0.0.1:{port}', '--noreload'],
                               cwd=ROOT, env=local_environment())
    try:
        # Loopback requests do not need the user's network proxy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError('프로그램을 시작하지 못했습니다. 위쪽 오류 내용을 확인해 주세요.')
            try:
                with opener.open(address + 'health/', timeout=1) as response:
                    if response.read() == b'ok':
                        break
            except OSError:
                pass
            time.sleep(.2)
        else:
            raise RuntimeError('시작 확인 시간이 초과되었습니다. 위쪽 오류 내용을 확인해 주세요.')
        print('\n프로그램이 실행되었습니다!', flush=True)
        print(f'본인 PC의 브라우저 주소창: {address}', flush=True)
        print('이 창을 열어둔 상태로 사용하세요. 종료하려면 Ctrl+C를 누르세요.', flush=True)
        if open_browser:
            try:
                webbrowser.open(address)
            except webbrowser.Error:
                print('브라우저 주소창에 위 주소를 직접 입력해 주세요.', flush=True)
        process.wait()
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='사내결재 PC 시안 설치·실행')
    parser.add_argument('mode', choices=['setup', 'run'])
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    try:
        if args.mode == 'setup':
            setup()
        else:
            if not 1024 <= args.port <= 65535:
                raise RuntimeError('포트 번호는 1024~65535 사이로 입력해 주세요.')
            run(args.port, not args.no_browser)
    except KeyboardInterrupt:
        print('\n프로그램을 종료했습니다.')
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f'\n진행을 완료하지 못했습니다: {exc}', file=sys.stderr)
        print('창을 닫기 전에 오류 문구를 복사하거나 사진으로 남겨 주세요.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
