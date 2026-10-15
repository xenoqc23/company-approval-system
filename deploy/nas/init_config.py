"""Run only by the NAS installer; secrets are generated locally, never printed."""
import os
from pathlib import Path
import secrets

root = Path('/target')
owner = int(os.environ.get('CONFIG_OWNER', '0'))
# Synology's legacy Docker refuses bind mounts whose host directory is missing.
# Leave database ownership to MariaDB's entrypoint and preserve existing files.
(root / 'data/mariadb').mkdir(parents=True, exist_ok=True)
for name in ['data/app', 'backups']:
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    os.chown(folder, 10001, 10001)
    folder.chmod(0o700)
config = root / '.env'
if not config.exists():
    values = {
        'DJANGO_SECRET_KEY': secrets.token_hex(40),
        'DB_NAME': 'approval_main', 'DB_USER': 'approval_app',
        'DB_PASSWORD': secrets.token_hex(32), 'DB_ROOT_PASSWORD': secrets.token_hex(32),
        'BIND_IP': os.environ.get('INITIAL_BIND_IP', '192.168.1.46'),
        'APP_PORT': os.environ.get('INITIAL_APP_PORT', '18080'),
        'DJANGO_ALLOWED_HOSTS': os.environ.get('INITIAL_ALLOWED_HOSTS', '192.168.1.46,localhost,127.0.0.1'),
        'DJANGO_CSRF_TRUSTED_ORIGINS': '', 'DJANGO_SECURE_COOKIES': '0',
        'DJANGO_SSL_REDIRECT': '0', 'DJANGO_TRUST_PROXY': '0',
    }
    with config.open('x') as stream:
        stream.write('# NAS local configuration. Keep private; never overwrite during updates.\n')
        stream.writelines(f'{key}={value}\n' for key, value in values.items())
    config.chmod(0o600)
    os.chown(config, owner, -1)
password_file = root / 'data/app/initial-admin-password.txt'
if not (root / '.initialized').exists() and not password_file.exists():
    password_file.write_text(secrets.token_urlsafe(18) + '\n')
    password_file.chmod(0o600)
    os.chown(password_file, 10001, 10001)
    instructions = root / 'initial-login.txt'
    instructions.write_text('Xenosys 사내결재시스템\n아이디: admin\n임시 비밀번호: ' + password_file.read_text()
                            + '\n최초 로그인에서 비밀번호를 변경하고 이 파일을 삭제해 주세요.\n')
    instructions.chmod(0o600)
    os.chown(instructions, owner, -1)
