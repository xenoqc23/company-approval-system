"""Isolated integrated PC test. Does not load NAS .env or use existing data."""
import argparse,os,socket,sqlite3,subprocess,sys,time,urllib.request,venv,webbrowser,secrets,shutil,json
from pathlib import Path
from datetime import datetime
ROOT=Path(__file__).resolve().parent
PYTHON=ROOT/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
DATA=ROOT/'var'/'full-nas-test-v3'/'purchase-test'
DEFAULT_PORT=18141


def environment():
    DATA.mkdir(parents=True,exist_ok=True)
    key=DATA/'session-secret.txt'
    if not key.exists():
        with key.open('x',encoding='utf-8') as handle:handle.write(secrets.token_urlsafe(64))
        key.chmod(0o600)
    env=os.environ.copy();env.update(DB_ENGINE='sqlite',APPROVAL_DATA_DIR=str(DATA),APPROVAL_PRODUCTION='0',APPROVAL_BACKUP_DIR=str(DATA/'backups'),
        DJANGO_DEBUG='1',DJANGO_SETTINGS_MODULE='approval_site.settings',DJANGO_ALLOWED_HOSTS='localhost,127.0.0.1,testserver',
        DJANGO_SECURE_COOKIES='0',DJANGO_SSL_REDIRECT='0',DJANGO_TRUST_PROXY='0',DJANGO_CSRF_TRUSTED_ORIGINS='',
        APPROVAL_WEBPUSH_ENABLED='0',APPROVAL_PURCHASE_LAB='1',APPROVAL_INTEGRATED_PURCHASES='1',APPROVAL_PURCHASES_ENABLED='1',APPROVAL_LOCAL_DEMO='1',APPROVAL_PURCHASE_LAB_INSTANCE='reviewer-final-v3',DJANGO_SECRET_KEY=key.read_text(),
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
    command('manage.py','seed_full_demo')
    command('manage.py','check')
    print('준비 완료. RUN_LOCAL_FULL.bat을 실행해 주세요. 첫 로그인 후 화면 상단에서 가상 역할을 전환할 수 있습니다.')


def reset():
    # Only the fixed, isolated fictional database belonging to this extracted bundle.
    if DATA.resolve()!=ROOT.resolve()/'var'/'full-nas-test-v3'/'purchase-test' or DATA.is_symlink():raise RuntimeError('테스트 데이터 경로를 확인해 주세요.')
    running=DATA/'running.json'
    if running.exists():
        try:port=int(json.loads(running.read_text())['port'])
        except (ValueError,KeyError,OSError):raise RuntimeError('실행 중인 테스트 창을 먼저 종료해 주세요.')
        try:connection=socket.create_connection(('127.0.0.1',port),timeout=.5)
        except OSError:pass
        else:
            connection.close();raise RuntimeError('실행 중인 테스트 창을 먼저 종료해 주세요.')
    db=DATA/'prototype.sqlite3'
    if DATA.exists():
        if db.exists():
            if not (DATA/'.purchase-lab').is_file() or not (DATA/'.full-local').is_file():raise RuntimeError('가상 테스트 표시가 없어 초기화를 중단했습니다.')
            try:
                with sqlite3.connect(db.as_uri()+'?mode=ro',uri=True) as c:
                    users=c.execute('SELECT COUNT(*) FROM auth_user').fetchone()[0]
                    demo=c.execute('SELECT COUNT(*) FROM purchasing_demoaccount').fetchone()[0]
                    foreign=c.execute('SELECT COUNT(*) FROM auth_user u LEFT JOIN purchasing_demoaccount d ON u.id=d.user_id WHERE d.user_id IS NULL').fetchone()[0]
                    real_docs=c.execute('SELECT COUNT(*) FROM workflow_document d LEFT JOIN purchasing_demoaccount a ON a.user_id=d.owner_id WHERE a.user_id IS NULL').fetchone()[0]
                    balances=c.execute('SELECT COUNT(*) FROM workflow_annualbalance b LEFT JOIN purchasing_demoaccount a ON a.user_id=b.user_id WHERE a.user_id IS NULL').fetchone()[0]
                if users!=demo or foreign or real_docs or balances:raise RuntimeError('가상 계정 외 자료가 있어 초기화를 중단했습니다.')
            except sqlite3.Error:raise RuntimeError('테스트 DB를 확인할 수 없어 초기화를 중단했습니다.')
        elif any(DATA.iterdir()):raise RuntimeError('확인되지 않은 파일이 있어 초기화를 중단했습니다.')
        shutil.rmtree(DATA)
    print('이 폴더의 가상 테스트 데이터를 비웠습니다. 새 테스트 비밀번호를 정해 주세요.')
    setup()


def run(port,open_browser=True):
    if not PYTHON.is_file() or not (DATA/'prototype.sqlite3').is_file() or not (DATA/'.purchase-lab').is_file() or not (DATA/'.full-local').is_file():
        raise RuntimeError('먼저 SETUP_LOCAL_FULL.bat을 실행해 주세요.')
    if not 1024<=port<=65535:raise RuntimeError('포트 번호는 1024~65535로 지정해 주세요.')
    with socket.socket() as probe:
        try:probe.bind(('127.0.0.1',port))
        except OSError:raise RuntimeError('이미 실행 중인 테스트 창을 닫거나 다른 포트를 지정해 주세요.')
    process=None
    try:
        process=subprocess.Popen([str(PYTHON),'manage.py','runserver',f'127.0.0.1:{port}','--noreload'],cwd=ROOT,env=environment())
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(100):
            if process.poll() is not None:raise RuntimeError('통합 테스트 서버를 시작하지 못했습니다.')
            try:
                with opener.open(f'http://127.0.0.1:{port}/health/',timeout=1) as response:
                    if response.read()==b'ok':break
            except OSError:pass
            time.sleep(.2)
        else:raise RuntimeError('테스트 서버 응답 시간이 초과되었습니다.')
        print(f'사내결재 전체 기능 로컬 테스트 실행 중: http://127.0.0.1:{port}/\n종료: 이 창에서 Ctrl+C. NAS에는 적용하지 않습니다.',flush=True)
        if open_browser:webbrowser.open(f'http://127.0.0.1:{port}/')
        (DATA/'running.json').write_text(json.dumps({'pid':os.getpid(),'port':port}))
        process.wait()
    finally:
        (DATA/'running.json').unlink(missing_ok=True)
        if process and process.poll() is None:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['setup','run','reset']);parser.add_argument('--port',type=int,default=DEFAULT_PORT);parser.add_argument('--no-browser',action='store_true');args=parser.parse_args()
    try:setup() if args.mode=='setup' else reset() if args.mode=='reset' else run(args.port,not args.no_browser)
    except KeyboardInterrupt:print('통합 테스트를 종료했습니다.')
    except (RuntimeError,OSError,subprocess.CalledProcessError) as exc:print(str(exc),file=sys.stderr);sys.exit(1)
