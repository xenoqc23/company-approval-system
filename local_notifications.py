"""Separate PC-only notification demo; never reads NAS .env or production data."""
import argparse
import os
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request
import venv
import webbrowser
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parent
PYTHON=ROOT/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
DATA=ROOT/'var'/'notification-test'


def environment():
    env=os.environ.copy()
    env.update(DB_ENGINE='sqlite',APPROVAL_DATA_DIR=str(DATA),APPROVAL_PRODUCTION='0',DJANGO_DEBUG='1',
               DJANGO_SETTINGS_MODULE='approval_site.settings',DJANGO_ALLOWED_HOSTS='localhost,127.0.0.1,testserver',
               DJANGO_SECURE_COOKIES='0',DJANGO_SSL_REDIRECT='0',DJANGO_TRUST_PROXY='0',
               DJANGO_CSRF_TRUSTED_ORIGINS='',APPROVAL_WEBPUSH_ENABLED='1',WEBPUSH_PRIVATE_KEY_FILE=str(DATA/'webpush-private.pem'),
               WEBPUSH_CONTACT='https://localhost',PYTHONUTF8='1',PYTHONUNBUFFERED='1')
    return env


def command(*args):
    subprocess.run([str(PYTHON),*args],cwd=ROOT,env=environment(),check=True)


def setup():
    if sys.version_info<(3,10):raise RuntimeError('Python 3.10 이상이 필요합니다.')
    if not PYTHON.is_file():venv.EnvBuilder(with_pip=True).create(ROOT/'.venv')
    command('-m','ensurepip','--upgrade')
    command('-m','pip','install','-r','requirements-prototype.txt','-r','requirements-webpush.txt')
    db=DATA/'prototype.sqlite3'
    if db.exists():
        backups=DATA/'backups';backups.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(db) as source,sqlite3.connect(backups/f'before-update-{datetime.now():%Y%m%d-%H%M%S-%f}.sqlite3') as dest:source.backup(dest)
    command('manage.py','migrate','--noinput')
    command('manage.py','init_webpush')
    command('manage.py','seed_demo')
    command('manage.py','notification_demo_permissions')
    command('manage.py','check')
    print('설치 완료. RUN_LOCAL_NOTIFICATIONS.bat을 실행해 주세요. NAS와 별도인 가상 데이터만 사용합니다.')


def run(port,open_browser=True):
    if not PYTHON.is_file() or not (DATA/'prototype.sqlite3').is_file():raise RuntimeError('먼저 SETUP_LOCAL_NOTIFICATIONS.bat을 실행해 주세요.')
    if not 1024<=port<=65535:raise RuntimeError('포트 번호는 1024~65535로 입력해 주세요.')
    with socket.socket() as probe:
        try:probe.bind(('127.0.0.1',port))
        except OSError:raise RuntimeError('이미 실행 중인 테스트 창을 닫거나 다른 포트를 지정해 주세요.')
    processes=[]
    try:
        processes.append(subprocess.Popen([str(PYTHON),'manage.py','runserver',f'127.0.0.1:{port}','--noreload'],cwd=ROOT,env=environment()))
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(100):
            if processes[0].poll() is not None:raise RuntimeError('테스트 서버를 시작하지 못했습니다.')
            try:
                with opener.open(f'http://127.0.0.1:{port}/health/',timeout=1) as response:
                    if response.read()==b'ok':break
            except OSError:pass
            time.sleep(.2)
        else:raise RuntimeError('서버 응답 시간이 초과되었습니다.')
        processes.append(subprocess.Popen([str(PYTHON),'manage.py','run_webpush'],cwd=ROOT,env=environment()))
        print('알림 테스트가 실행되었습니다. 브라우저를 닫아도 이 창은 열어 두세요. 종료: Ctrl+C',flush=True)
        if open_browser:webbrowser.open(f'http://127.0.0.1:{port}/login/')
        while all(p.poll() is None for p in processes):time.sleep(.5)
        raise RuntimeError('테스트 서버 또는 푸시 발송 프로그램이 종료되었습니다. 위 오류를 확인해 주세요.')
    finally:
        for process in processes:
            if process.poll() is None:process.terminate()
        for process in processes:
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['setup','run']);parser.add_argument('--port',type=int,default=18095);parser.add_argument('--no-browser',action='store_true');args=parser.parse_args()
    try:
        if args.mode=='setup':setup()
        else:run(args.port,not args.no_browser)
    except KeyboardInterrupt:print('테스트를 종료했습니다.')
    except (RuntimeError,OSError,subprocess.CalledProcessError) as e:print(str(e),file=sys.stderr);sys.exit(1)
