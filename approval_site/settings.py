import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get('APPROVAL_DATA_DIR', BASE_DIR / 'var'))
DATA_DIR.mkdir(parents=True, exist_ok=True)
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'development-only-approval-prototype-key')
DEBUG = os.environ.get('DJANGO_DEBUG', '1') == '1'
PRODUCTION = os.environ.get('APPROVAL_PRODUCTION', '0') == '1'
if PRODUCTION:
    if DEBUG or len(os.environ.get('DJANGO_SECRET_KEY', '')) < 50:
        raise ImproperlyConfigured('운영 모드에서는 DEBUG=0과 별도의 충분한 비밀키가 필요합니다.')
    if os.environ.get('DB_ENGINE') != 'mariadb':
        raise ImproperlyConfigured('NAS 운영 모드에는 MariaDB 설정이 필요합니다.')
    if not os.environ.get('DJANGO_ALLOWED_HOSTS') or '*' in os.environ['DJANGO_ALLOWED_HOSTS']:
        raise ImproperlyConfigured('운영 접속 주소를 명시해 주세요.')
ALLOWED_HOSTS = os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1,testserver').split(',')
INSTALLED_APPS = [
    'django.contrib.auth', 'django.contrib.contenttypes', 'django.contrib.sessions',
    'django.contrib.messages', 'django.contrib.staticfiles', 'workflow',
]
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware', 'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware', 'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware', 'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware', 'workflow.middleware.AccountGateMiddleware',
]
if PRODUCTION:
    MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')
ROOT_URLCONF = 'approval_site.urls'
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'workflow/templates'], 'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.request', 'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages', 'workflow.context.shell',
    ]},
}]
WSGI_APPLICATION = 'approval_site.wsgi.application'
if os.environ.get('DB_ENGINE') == 'mariadb':
    DATABASES = {'default': {
        'ENGINE': 'django.db.backends.mysql', 'NAME': os.environ['DB_NAME'],
        'USER': os.environ['DB_USER'], 'PASSWORD': os.environ['DB_PASSWORD'],
        'HOST': os.environ.get('DB_HOST', '127.0.0.1'), 'PORT': os.environ.get('DB_PORT', '3306'),
        'OPTIONS': {'charset': 'utf8mb4', 'init_command': "SET sql_mode='STRICT_TRANS_TABLES'"},
    }}
else:
    DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': DATA_DIR / 'prototype.sqlite3',
                             'OPTIONS': {'timeout': 20}}}
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 4}},
]
LANGUAGE_CODE = 'ko-kr'
TIME_ZONE = 'Asia/Seoul'
USE_I18N = True
USE_TZ = True
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
if PRODUCTION:
    STORAGES = {'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
                'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'}}
BACKUP_DIR = Path(os.environ.get('APPROVAL_BACKUP_DIR', DATA_DIR / 'backups'))
APP_VERSION = os.environ.get('APP_VERSION', 'pc')
CSRF_TRUSTED_ORIGINS = [x for x in os.environ.get('DJANGO_CSRF_TRUSTED_ORIGINS', '').split(',') if x]
SESSION_COOKIE_SECURE = os.environ.get('DJANGO_SECURE_COOKIES', '0') == '1'
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
# Cookies are scoped to a host, not a port. Keep other NAS apps isolated.
SESSION_COOKIE_NAME = 'xenosys_approval_sessionid'
CSRF_COOKIE_NAME = 'xenosys_approval_csrftoken'
SECURE_SSL_REDIRECT = os.environ.get('DJANGO_SSL_REDIRECT', '0') == '1'
SECURE_REDIRECT_EXEMPT = [r'^health/$']
if os.environ.get('DJANGO_TRUST_PROXY', '0') == '1':
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
LOGIN_URL = 'login'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
X_FRAME_OPTIONS = 'DENY'
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'csrf_console': {'class': 'logging.StreamHandler'}},
    'loggers': {'django.security.csrf': {
        'handlers': ['csrf_console'], 'level': 'WARNING', 'propagate': False,
    }},
}

# Web Push is opt-in. The private key lives outside the source tree/public ZIPs.
WEBPUSH_PRIVATE_KEY_FILE = os.environ.get('WEBPUSH_PRIVATE_KEY_FILE', str(DATA_DIR / 'webpush-private.pem'))
WEBPUSH_CONTACT = os.environ.get('WEBPUSH_CONTACT', 'https://localhost')

# Closed-browser push is deferred on NAS; only explicitly enabled local tests use it.
WEBPUSH_ENABLED = not PRODUCTION and os.environ.get('APPROVAL_WEBPUSH_ENABLED', '0') == '1'

# One application is used on NAS and on a local PC. Only the fictional account
# switcher and its seed commands are limited to an explicitly marked local lab.
LOCAL_DEMO_ENABLED = not PRODUCTION and os.environ.get('APPROVAL_LOCAL_DEMO', '0') == '1'
_legacy_integrated_lab = not PRODUCTION and os.environ.get('APPROVAL_INTEGRATED_PURCHASES', '0') == '1'
PURCHASE_LAB_ENABLED = not PRODUCTION and (os.environ.get('APPROVAL_PURCHASE_LAB', '0') == '1' or LOCAL_DEMO_ENABLED or _legacy_integrated_lab)
_STANDALONE_PURCHASE_LAB = PURCHASE_LAB_ENABLED and not (LOCAL_DEMO_ENABLED or _legacy_integrated_lab)
INTEGRATED_PURCHASES = not _STANDALONE_PURCHASE_LAB and os.environ.get('APPROVAL_PURCHASES_ENABLED', '1') == '1'
# Register schema on both platforms, including when the legacy UI is selected.
INSTALLED_APPS.append('purchasing')
if INTEGRATED_PURCHASES:
    TEMPLATES[0]['OPTIONS']['context_processors'].append('purchasing.integration.shell')
if PURCHASE_LAB_ENABLED:
    if DATA_DIR.name != 'purchase-test':
        raise ImproperlyConfigured('가상 테스트는 별도 purchase-test 데이터 폴더에서만 실행할 수 있습니다.')
    if DATABASES['default']['ENGINE'] == 'django.db.backends.sqlite3':
        DATABASES['default']['OPTIONS']['transaction_mode'] = 'IMMEDIATE'
    WEBPUSH_ENABLED = False
    if _STANDALONE_PURCHASE_LAB:
        MIDDLEWARE[-1] = 'purchasing.middleware.PurchaseLabGateMiddleware'
        TEMPLATES[0]['OPTIONS']['context_processors'][-1] = 'purchasing.context.shell'
        _purchase_cookie_prefix = {'terms-v1':'xenosys_purchase_terms','features-v1':'xenosys_purchase_features','complete-v1':'xenosys_purchase_complete','simple-v1':'xenosys_purchase_simple','departments-v1':'xenosys_purchase_departments'}.get(os.environ.get('APPROVAL_PURCHASE_LAB_INSTANCE'),'xenosys_purchase_lab')
        SESSION_COOKIE_NAME = _purchase_cookie_prefix + '_sessionid'
        CSRF_COOKIE_NAME = _purchase_cookie_prefix + '_csrftoken'
        LOGIN_URL = '/purchase-lab/login/'
    elif LOCAL_DEMO_ENABLED:
        _full_prefix = 'xenosys_final_full_local' if os.environ.get('APPROVAL_PURCHASE_LAB_INSTANCE')=='reviewer-final-v3' else 'xenosys_simple_full_local' if os.environ.get('APPROVAL_PURCHASE_LAB_INSTANCE')=='simple-full-v2' else 'xenosys_full_local'
        SESSION_COOKIE_NAME = _full_prefix + '_sessionid'
        CSRF_COOKIE_NAME = _full_prefix + '_csrftoken'
        LOGIN_URL = '/login/'
    else:
        SESSION_COOKIE_NAME = 'xenosys_integrated_local_sessionid'
        CSRF_COOKIE_NAME = 'xenosys_integrated_local_csrftoken'
        LOGIN_URL = '/login/'
