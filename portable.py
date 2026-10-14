"""Start the PC prototype using the Python runtime bundled beside the executable."""
import argparse
from io import StringIO
import os
from pathlib import Path
import socket
import subprocess
import sys
import launcher


def prepare():
    os.environ.update(launcher.local_environment())
    import django
    django.setup()
    from django.core.management import call_command
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor
    executor = MigrationExecutor(connection)
    if executor.migration_plan(executor.loader.graph.leaf_nodes()):
        launcher.backup_before_update()
        call_command('migrate', interactive=False, verbosity=0)
    call_command('seed_demo', verbosity=0)
    call_command('check', stdout=StringIO())
    connection.close()


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='사내결재시스템 설치 없는 PC 시안')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--no-pause', action='store_true')
    args = parser.parse_args()
    launcher.PYTHON = Path(sys.executable)
    try:
        if not 1024 <= args.port <= 65535:
            raise RuntimeError('포트 번호는 1024~65535 사이로 입력해 주세요.')
        if not args.prepare_only:
            with socket.socket() as probe:
                try:
                    probe.bind(('127.0.0.1', args.port))
                except OSError as exc:
                    raise RuntimeError('이전에 열어둔 프로그램 실행 창을 종료하고 다시 실행해 주세요.') from exc
        print('사내결재시스템을 준비합니다. 처음 실행하면 초기 비밀번호를 입력합니다.', flush=True)
        prepare()
        if not args.prepare_only:
            launcher.run(args.port, not args.no_browser)
        return 0
    except KeyboardInterrupt:
        print('\n프로그램을 종료했습니다.')
        return 0
    except Exception as exc:
        print(f'\n실행을 완료하지 못했습니다: {exc}', file=sys.stderr, flush=True)
        print('오류 내용을 확인한 뒤 다시 실행해 주세요. var 폴더는 보관해 주세요.', flush=True)
        if not args.no_pause:
            try:
                input('창을 닫으려면 Enter를 누르세요.')
            except (EOFError, KeyboardInterrupt):
                pass
        return 1


if __name__ == '__main__':
    sys.exit(main())
