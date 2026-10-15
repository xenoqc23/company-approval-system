"""Consistent logical MariaDB backups. Restore is an offline NAS operation."""
from contextlib import contextmanager
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile, ZIP_DEFLATED
from django.conf import settings
from django.db import connection
from django.db.utils import ConnectionHandler
from django.db.migrations.loader import MigrationLoader
from django.utils import timezone

REQUIRED_TABLES = {'auth_user', 'workflow_profile', 'workflow_document', 'workflow_annualbalance', 'django_migrations'}


def require_known_migrations(database):
    loader = MigrationLoader(database)
    if set(loader.applied_migrations) - set(loader.disk_migrations):
        raise ValueError('현재 프로그램보다 새로운 DB 백업입니다. 해당 버전의 프로그램으로 복구해 주세요.')
    loader.check_consistent_history(database)


def digest(path):
    result = sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


@contextmanager
def client_config():
    """Never put passwords in command arguments or subprocess error output."""
    db = connection.settings_dict
    def quote(value):
        return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n') + '"'
    with TemporaryDirectory(prefix='approval-db-') as folder:
        config = Path(folder) / 'client.cnf'
        config.write_text('[client]\n' + '\n'.join(f'{k}={quote(v)}' for k, v in {
            'host': db['HOST'], 'port': db['PORT'], 'user': db['USER'], 'password': db['PASSWORD'],
            'default-character-set': 'utf8mb4',
        }.items()) + '\n')
        config.chmod(0o600)
        yield config


def client_run(program, arguments, *, stdin=None, stdout=None):
    with client_config() as config:
        try:
            result = subprocess.run([program, f'--defaults-extra-file={config}', *arguments],
                                    stdin=stdin, stdout=stdout or subprocess.DEVNULL,
                                    stderr=subprocess.PIPE, timeout=600)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError('DB 작업을 완료하지 못했습니다. 연결 상태와 백업 경로를 확인해 주세요.') from exc
        if result.returncode:
            # Client output can contain personal data or connection details.
            raise RuntimeError('DB 작업에 실패했습니다. 현재 서비스 상태와 DB 연결을 확인해 주세요.')


def create_mariadb_backup(kind='manual'):
    from .backups import directory
    if kind not in {'manual', 'daily', 'monthly', 'update', 'before-restore'}:
        raise ValueError('지원하지 않는 백업 종류입니다.')
    root = directory()
    now = timezone.localtime()
    name = f'backup-{now:%Y%m%d-%H%M%S-%f}-{kind}.zip'
    with TemporaryDirectory(prefix='.backup-', dir=root) as folder:
        sql = Path(folder) / 'database.sql'
        with sql.open('wb') as stream:
            client_run('mariadb-dump', ['--single-transaction', '--quick', '--skip-lock-tables',
                       '--hex-blob', '--no-tablespaces', '--default-character-set=utf8mb4',
                       connection.settings_dict['NAME']], stdout=stream)
        if not sql.stat().st_size:
            raise RuntimeError('빈 백업은 저장하지 않습니다.')
        manifest = {'format': 1, 'engine': 'mariadb', 'created_at': now.isoformat(),
                    'app_version': settings.APP_VERSION, 'sha256': digest(sql), 'kind': kind}
        staged = Path(folder) / name
        with ZipFile(staged, 'w', ZIP_DEFLATED) as archive:
            archive.write(sql, 'database.sql')
            archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        staged.chmod(0o600)
        with staged.open('rb') as stream:
            os.fsync(stream.fileno())
        final = root / name
        os.replace(staged, final)
    return final


def prune_scheduled_backups():
    from .backups import directory
    # Only our scheduled archives: manual/update/recovery files are preserved.
    for kind, limit in [('daily', 30), ('monthly', 12)]:
        archives = sorted(directory().glob(f'backup-*-{kind}.zip'), reverse=True)
        for path in archives[limit:]:
            path.unlink()


@contextmanager
def verified_sql(name):
    from .backups import directory
    path = directory() / name
    if Path(name).name != name or not name.startswith('backup-') or path.suffix != '.zip' or not path.is_file() or path.is_symlink():
        raise ValueError('백업 목록에 있는 ZIP 파일명을 지정해 주세요.')
    with TemporaryDirectory(prefix='.restore-', dir=directory()) as folder:
        sql = Path(folder) / 'database.sql'
        try:
            with ZipFile(path) as archive:
                if sorted(archive.namelist()) != ['database.sql', 'manifest.json']:
                    raise ValueError('사내결재시스템의 백업 파일이 아닙니다.')
                if archive.getinfo('manifest.json').file_size > 16384 or archive.getinfo('database.sql').file_size > 10 * 1024**3:
                    raise ValueError('백업 파일 크기를 확인해 주세요.')
                manifest = json.loads(archive.read('manifest.json'))
                if manifest.get('format') != 1 or manifest.get('engine') != 'mariadb':
                    raise ValueError('지원하지 않는 백업 형식입니다.')
                with archive.open('database.sql') as source, sql.open('wb') as target:
                    shutil.copyfileobj(source, target)
            if digest(sql) != manifest.get('sha256'):
                raise ValueError('백업 파일 무결성 검사에 실패했습니다. 현재 DB는 변경하지 않았습니다.')
        except (OSError, KeyError, json.JSONDecodeError) as exc:
            raise ValueError('백업 파일을 읽을 수 없습니다.') from exc
        yield sql, manifest


def restore_mariadb(name):
    """Called by the root-only tools container after the web service is stopped."""
    if os.environ.get('APPROVAL_OFFLINE_RESTORE') != '1' or connection.settings_dict['USER'] != 'root':
        raise RuntimeError('NAS의 오프라인 복구 명령으로 실행해 주세요.')
    dbname = connection.settings_dict['NAME']
    if not re.fullmatch(r'approval_[a-z0-9_]+', dbname):
        raise RuntimeError('결재시스템 전용 DB만 복구할 수 있습니다.')
    staging = 'approval_restore_' + os.urandom(8).hex()
    with verified_sql(name) as (sql, manifest):
        with connection.cursor() as cursor:
            cursor.execute(f'CREATE DATABASE `{staging}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
        try:
            with sql.open('rb') as stream:
                client_run('mariadb', [staging], stdin=stream)
            with connection.cursor() as cursor:
                cursor.execute('SELECT table_name FROM information_schema.tables WHERE table_schema=%s', [staging])
                tables = {row[0] for row in cursor.fetchall()}
            if not REQUIRED_TABLES <= tables:
                raise ValueError('필수 데이터가 없는 백업입니다. 현재 DB는 변경하지 않았습니다.')
            staged_connection = ConnectionHandler({'default': {**connection.settings_dict, 'NAME': staging}})['default']
            try:
                require_known_migrations(staged_connection)
            finally:
                staged_connection.close()
            env = {**os.environ, 'DB_NAME': staging}
            result = subprocess.run([sys.executable, str(settings.BASE_DIR / 'manage.py'), 'migrate', '--noinput'],
                                    env=env, cwd=settings.BASE_DIR, capture_output=True, timeout=600)
            if result.returncode:
                raise RuntimeError('백업의 버전 호환성을 확인하지 못했습니다. 현재 DB는 유지됩니다.')
            # Re-dump the validated, migrated staging DB before touching live data.
            prepared = sql.with_name('prepared.sql')
            with prepared.open('wb') as stream:
                client_run('mariadb-dump', ['--single-transaction', '--quick', '--skip-lock-tables', '--hex-blob', '--no-tablespaces', staging], stdout=stream)
            safety = create_mariadb_backup('before-restore')
            connection.close()
            client_run('mariadb', ['--execute', f'DROP DATABASE `{dbname}`; CREATE DATABASE `{dbname}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;'])
            with prepared.open('rb') as stream:
                client_run('mariadb', [dbname], stdin=stream)
            return safety
        finally:
            # A dropped live DB can temporarily invalidate this connection.
            connection.close()
            with connection.cursor() as cursor:
                cursor.execute(f'DROP DATABASE IF EXISTS `{staging}`')
