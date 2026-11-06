"""Install only this isolated PC tester, then keep its local sender running."""
import os
import subprocess
import sys
import venv
from pathlib import Path

ROOT=Path(__file__).resolve().parent
PYTHON=ROOT/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')


def main():
    if sys.version_info<(3,10):
        raise RuntimeError('Python 3.10 이상이 필요합니다. Python 3.12 설치를 권장합니다.')
    if not PYTHON.is_file():
        print('최초 1회: 이 폴더 안에 테스트용 실행 환경을 준비합니다.',flush=True)
        venv.EnvBuilder(with_pip=True).create(ROOT/'.venv')
    marker=ROOT/'.venv'/'local-push-dependencies-v1'
    if not marker.exists():
        subprocess.run([str(PYTHON),'-m','pip','install','-r',str(ROOT/'requirements.txt')],cwd=ROOT,check=True)
        marker.write_text('pywebpush==2.1.2\n')
    subprocess.run([str(PYTHON),str(ROOT/'server.py')],cwd=ROOT,check=True)


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    try:main()
    except KeyboardInterrupt:print('로컬 알림 테스트를 종료했습니다.')
    except (OSError,RuntimeError,subprocess.CalledProcessError) as exc:
        print(f'실행을 마치지 못했습니다.\n{exc}',file=sys.stderr)
        raise SystemExit(1)
