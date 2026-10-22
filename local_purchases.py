"""Isolated purchase-only PC test. Does not load NAS .env or use existing data."""
import argparse,os,socket,sqlite3,subprocess,sys,time,urllib.request,venv,webbrowser,secrets
from pathlib import Path
from datetime import datetime
ROOT=Path(__file__).resolve().parent
PYTHON=ROOT/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
DATA=ROOT/'var'/'purchase-test'


def environment():
    DATA.mkdir(parents=True,exist_ok=True)
    key=DATA/'session-secret.txt'
    if not key.exists():
        with key.open('x',encoding='utf-8') as handle:handle.write(secrets.token_urlsafe(64))
        key.chmod(0o600)
    env=os.environ.copy();env.update(DB_ENGINE='sqlite',APPROVAL_DATA_DIR=str(DATA),APPROVAL_PRODUCTION='0',
        DJANGO_DEBUG='1',DJANGO_SETTINGS_MODULE='approval_site.settings',DJANGO_ALLOWED_HOSTS='localhost,127.0.0.1,testserver',
        DJANGO_SECURE_COOKIES='0',DJANGO_SSL_REDIRECT='0',DJANGO_TRUST_PROXY='0',DJANGO_CSRF_TRUSTED_ORIGINS='',
        APPROVAL_WEBPUSH_ENABLED='0',APPROVAL_PURCHASE_LAB='1',DJANGO_SECRET_KEY=key.read_text(),
        PYTHONUTF8='1',PYTHONUNBUFFERED='1')
    return env


def command(*args):subprocess.run([str(PYTHON),*args],cwd=ROOT,env=environment(),check=True)


def setup():
    if sys.version_info<(3,10):raise RuntimeError('Python 3.10 이상이 필요합니다.')
    if not PYTHON.is_file():venv.EnvBuilder(with_pip=True).create(ROOT/'.venv')
    command('-m','ensurepip','--upgrade');command('-m','pip','install','-r','requirements-prototype.txt')
    db=DATA/'prototype.sqlite3'
    if db.exists():
        folder=DATA/'backups';folder.mkdir(exist_ok=True)
        with sqlite3.connect(db) as source,sqlite3.connect(folder/f'before-update-{datetime.now():%Y%m%d-%H%M%S-%f}.sqlite3') as dest:source.backup(dest)
    command('manage.py','migrate','--noinput')
    command('manage.py','seed_purchase_demo')
    command('manage.py','check')
    print('준비 완료. RUN_LOCAL_PURCHASES.bat을 실행해 주세요. 첫 로그인 후 화면 상단에서 가상 역할을 전환할 수 있습니다.')


def run(port,open_browser=True):
    if not PYTHON.is_file() or not (DATA/'prototype.sqlite3').is_file() or not (DATA/'.purchase-lab').is_file():
        raise RuntimeError('먼저 SETUP_LOCAL_PURCHASES.bat을 실행해 주세요.')
    if not 1024<=port<=65535:raise RuntimeError('포트 번호는 1024~65535로 지정해 주세요.')
    with socket.socket() as probe:
        try:probe.bind(('127.0.0.1',port))
        except OSError:raise RuntimeError('이미 실행 중인 테스트 창을 닫거나 다른 포트를 지정해 주세요.')
    process=None
    try:
        process=subprocess.Popen([str(PYTHON),'manage.py','runserver',f'127.0.0.1:{port}','--noreload'],cwd=ROOT,env=environment())
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(100):
            if process.poll() is not None:raise RuntimeError('구매 테스트 서버를 시작하지 못했습니다.')
            try:
                with opener.open(f'http://127.0.0.1:{port}/health/',timeout=1) as response:
                    if response.read()==b'ok':break
            except OSError:pass
            time.sleep(.2)
        else:raise RuntimeError('테스트 서버 응답 시간이 초과되었습니다.')
        print(f'구매 전용 테스트 실행 중: http://127.0.0.1:{port}/purchase-lab/\n종료: 이 창에서 Ctrl+C. NAS에는 적용하지 않습니다.',flush=True)
        if open_browser:webbrowser.open(f'http://127.0.0.1:{port}/purchase-lab/')
        process.wait()
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['setup','run']);parser.add_argument('--port',type=int,default=18105);parser.add_argument('--no-browser',action='store_true');args=parser.parse_args()
    try:setup() if args.mode=='setup' else run(args.port,not args.no_browser)
    except KeyboardInterrupt:print('구매 테스트를 종료했습니다.')
    except (RuntimeError,OSError,subprocess.CalledProcessError) as exc:print(str(exc),file=sys.stderr);sys.exit(1)
