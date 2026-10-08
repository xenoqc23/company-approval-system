from datetime import datetime
from pathlib import Path
import sqlite3
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
    with sqlite3.connect(str(connection.settings_dict['NAME'])) as source:
        with sqlite3.connect(str(dest)) as target:
            source.backup(target)
    return dest

def restore_backup(name):
    if connection.vendor != 'sqlite':
        raise RuntimeError('MariaDB의 운영 복구는 NAS 복구 절차와 연결한 뒤 사용할 수 있습니다.')
    path = directory() / name
    if Path(name).name != name or path.suffix != '.sqlite3' or not path.is_file():
        raise ValueError('유효한 백업 파일을 선택해 주세요.')
    with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as source:
        if source.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('백업 파일의 무결성을 확인할 수 없습니다.')
        create_backup()
        connection.close()
        with sqlite3.connect(str(connection.settings_dict['NAME'])) as target:
            source.backup(target)
