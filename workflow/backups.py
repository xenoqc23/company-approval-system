from datetime import datetime
from pathlib import Path
import sqlite3
import os
import subprocess
import sys
import json
from zipfile import ZipFile,ZIP_DEFLATED,BadZipFile
from hashlib import sha256
from tempfile import TemporaryDirectory
from contextlib import closing
from django.conf import settings
from django.db import connection

def directory():
    root = settings.BACKUP_DIR
    root.mkdir(parents=True, exist_ok=True)
    return root

def list_backups():
    return [{'name': p.name, 'size': round(p.stat().st_size / 1024), 'time': datetime.fromtimestamp(p.stat().st_mtime)}
            for p in sorted([*directory().glob('*.sqlite3'), *directory().glob('backup-*.zip')], reverse=True)]

def create_backup(kind='manual'):
    if connection.vendor != 'sqlite':
        from .nas_backup import create_mariadb_backup
        return create_mariadb_backup(kind)
    dest = directory() / f'backup-{datetime.now():%Y%m%d-%H%M%S-%f}.sqlite3'
    with closing(sqlite3.connect(str(connection.settings_dict['NAME']))) as source:
        with closing(sqlite3.connect(str(dest))) as target:
            source.backup(target)
    from .backup_files import add_files
    files_root=settings.DATA_DIR/'purchase-attachments'
    if files_root.exists() and any(p.is_file() for p in files_root.rglob('*')):
        zipped=dest.with_suffix('.zip')
        try:
            with ZipFile(zipped,'w',ZIP_DEFLATED) as archive:
                archive.write(dest,'database.sqlite3');files=add_files(archive)
                archive.writestr('manifest.json',json.dumps(dict(format=2,engine='sqlite',sha256=sha256(dest.read_bytes()).hexdigest(),files=files)))
        except Exception:
            zipped.unlink(missing_ok=True);raise
        dest.unlink();return zipped
    return dest

def restore_backup(name):
    if connection.vendor != 'sqlite':
        raise RuntimeError('운영 DB 복구는 서비스를 중지한 뒤 NAS의 복구 명령으로 실행해 주세요.')
    path = directory() / name
    if Path(name).name==name and path.suffix=='.zip':
        return restore_sqlite_archive(path)
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
            env.update({'DB_ENGINE': 'sqlite', 'APPROVAL_DATA_DIR': folder, 'PYTHONUTF8': '1','APPROVAL_LOCAL_DEMO':'0','APPROVAL_PURCHASE_LAB':'0','APPROVAL_INTEGRATED_PURCHASES':'0'})
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


def restore_sqlite_archive(path):
    try:return _restore_sqlite_archive(path)
    except (BadZipFile,KeyError,json.JSONDecodeError) as exc:raise ValueError('백업 파일 형식이나 내용을 확인해 주세요.') from exc


def _restore_sqlite_archive(path):
    from .backup_files import verify_files,install_files
    if not path.is_file() or path.is_symlink():raise ValueError('유효한 백업 파일을 선택해 주세요.')
    with TemporaryDirectory(prefix='.restore-files-',dir=settings.DATA_DIR) as folder:
        stage=Path(folder)
        with ZipFile(path) as archive:
            names=archive.namelist()
            if len(names)!=len(set(names)) or not {'database.sqlite3','manifest.json'}<=set(names) or any(n not in ['database.sqlite3','manifest.json'] and not n.startswith('attachments/') for n in names):raise ValueError('사내결재시스템의 백업 파일이 아닙니다.')
            if archive.getinfo('manifest.json').file_size>16*1024*1024:raise ValueError('백업 목록이 너무 큽니다.')
            manifest=json.loads(archive.read('manifest.json'))
            if not isinstance(manifest,dict):raise ValueError('백업 목록 형식이 올바르지 않습니다.')
            if manifest.get('format')!=2 or manifest.get('engine')!='sqlite':raise ValueError('SQLite 백업 파일을 선택해 주세요.')
            verify_files(archive,manifest,stage/'files')
            if archive.getinfo('database.sqlite3').file_size>10*1024**3:raise ValueError('백업 크기를 확인해 주세요.')
            raw=archive.read('database.sqlite3')
            if sha256(raw).hexdigest()!=manifest.get('sha256'):raise ValueError('백업 DB 무결성 검사에 실패했습니다.')
            database=directory()/('.staged-'+stage.name+'.sqlite3');database.write_bytes(raw)
        try:
            # Existing restore validates/migrates the staged DB and takes a safety backup.
            restore_backup(database.name)
            install_files(stage/'files')
        finally:database.unlink(missing_ok=True)
