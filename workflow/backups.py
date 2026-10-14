from datetime import datetime
from pathlib import Path
import sqlite3
import os
import subprocess
import sys
from tempfile import TemporaryDirectory
from contextlib import closing
from django.conf import settings
from django.db import connection

def directory():
    root = settings.DATA_DIR / 'backups'
    root.mkdir(exist_ok=True)
    return root

def list_backups():
    return [{'name': p.name, 'size': round(p.stat().st_size / 1024), 'time': datetime.fromtimestamp(p.stat().st_mtime)}
            for p in sorted(directory().glob('*.sqlite3'), reverse=True)]

def create_backup():
    if connection.vendor != 'sqlite':
        raise RuntimeError('MariaDB의 운영 백업은 NAS 백업 작업과 연결한 뒤 사용할 수 있습니다.')
    dest = directory() / f'backup-{datetime.now():%Y%m%d-%H%M%S-%f}.sqlite3'
    with closing(sqlite3.connect(str(connection.settings_dict['NAME']))) as source:
        with closing(sqlite3.connect(str(dest))) as target:
            source.backup(target)
    return dest

def restore_backup(name):
    if connection.vendor != 'sqlite':
        raise RuntimeError('MariaDB의 운영 복구는 NAS 복구 절차와 연결한 뒤 사용할 수 있습니다.')
    path = directory() / name
    if Path(name).name != name or path.suffix != '.sqlite3' or not path.is_file():
        raise ValueError('유효한 백업 파일을 선택해 주세요.')
    with closing(sqlite3.connect(f'file:{path}?mode=ro', uri=True)) as source:
        if source.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('백업 파일의 무결성을 확인할 수 없습니다.')
        tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'auth_user', 'workflow_profile', 'workflow_document', 'workflow_annualbalance', 'django_migrations'} <= tables:
            raise ValueError('사내결재시스템의 백업 파일을 선택해 주세요.')
        # Upgrade a staged copy first: an older backup must not replace the live
        # DB until it can be read by the current application version.
        with TemporaryDirectory(prefix='restore-', dir=settings.DATA_DIR) as folder:
            staged = Path(folder) / 'prototype.sqlite3'
            with closing(sqlite3.connect(str(staged))) as target:
                source.backup(target)
            env = os.environ.copy()
            env.update({'DB_ENGINE': 'sqlite', 'APPROVAL_DATA_DIR': folder, 'PYTHONUTF8': '1'})
            try:
                result = subprocess.run([sys.executable, str(settings.BASE_DIR / 'manage.py'), 'migrate', '--noinput'],
                                        cwd=settings.BASE_DIR, env=env, capture_output=True, timeout=120)
            except (subprocess.TimeoutExpired, OSError) as exc:
                raise RuntimeError('백업 준비를 완료하지 못했습니다. 현재 데이터는 유지됩니다.') from exc
            if result.returncode:
                raise RuntimeError('백업을 현재 버전으로 준비하지 못했습니다. 현재 데이터는 유지됩니다.')
            create_backup()
            connection.close()
            with closing(sqlite3.connect(str(staged))) as prepared, closing(sqlite3.connect(str(connection.settings_dict['NAME']))) as target:
                prepared.backup(target)
