import os
from pathlib import Path
from urllib.parse import urlparse, unquote
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')
os.environ.setdefault('CUDA_VISIBLE_DEVICES', '-1')
os.environ.setdefault('OMP_NUM_THREADS', '2')
os.environ.setdefault('TF_NUM_INTRAOP_THREADS', '2')
os.environ.setdefault('TF_NUM_INTEROP_THREADS', '2')
DEBUG = os.getenv('DJANGO_DEBUG', '0') == '1'
SECRET_KEY = os.getenv('SECRET_KEY', '')
if not SECRET_KEY or SECRET_KEY == 'replace-with-random-secret':
    raise ImproperlyConfigured('Set a random SECRET_KEY in backend/.env')
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
INSTALLED_APPS = ['django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes',
                  'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles',
                  'corsheaders', 'rest_framework', 'attendance']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware', 'attendance.middleware.PrivateResponseMiddleware', 'corsheaders.middleware.CorsMiddleware',
              'django.contrib.sessions.middleware.SessionMiddleware', 'django.middleware.common.CommonMiddleware',
              'django.middleware.csrf.CsrfViewMiddleware', 'django.contrib.auth.middleware.AuthenticationMiddleware',
              'django.contrib.messages.middleware.MessageMiddleware', 'django.middleware.clickjacking.XFrameOptionsMiddleware']
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [], 'APP_DIRS': True,
              'OPTIONS': {'context_processors': ['django.template.context_processors.request',
                        'django.contrib.auth.context_processors.auth', 'django.contrib.messages.context_processors.messages']}}]
WSGI_APPLICATION = 'config.wsgi.application'
db = urlparse(os.getenv('DATABASE_URL', 'sqlite:///demo.sqlite3'))
if db.scheme in ('postgres', 'postgresql'):
    DATABASES = {'default': {'ENGINE': 'django.db.backends.postgresql', 'NAME': db.path.lstrip('/'),
                            'USER': unquote(db.username or ''), 'PASSWORD': os.getenv('DATABASE_PASSWORD', unquote(db.password or '')),
                            'HOST': db.hostname, 'PORT': db.port or 5432, 'CONN_MAX_AGE': 60}}
else:
    if not DEBUG: raise ImproperlyConfigured('Production requires PostgreSQL; SQLite is a local demo option only.')
    DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / db.path.lstrip('/')}}
AUTH_USER_MODEL = 'attendance.User'
AUTH_PASSWORD_VALIDATORS = [{'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
                            {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'}]
TIME_ZONE = os.getenv('APP_TIME_ZONE', 'Asia/Karachi')
USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
REST_FRAMEWORK = {'DEFAULT_AUTHENTICATION_CLASSES': ['rest_framework.authentication.SessionAuthentication'],
                  'EXCEPTION_HANDLER': 'attendance.errors.exception_handler',
                  'DEFAULT_PERMISSION_CLASSES': ['attendance.permissions.IsStaffRole'],
                  'DEFAULT_THROTTLE_CLASSES': ['rest_framework.throttling.AnonRateThrottle', 'rest_framework.throttling.UserRateThrottle'],
                  'DEFAULT_THROTTLE_RATES': {'anon': '30/min', 'user': '240/min'}}
FRONTEND_ORIGIN = os.getenv('FRONTEND_ORIGIN', 'http://localhost:5173')
CORS_ALLOWED_ORIGINS = [FRONTEND_ORIGIN]
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = [FRONTEND_ORIGIN]
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_AGE = 8 * 3600
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = not DEBUG
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
BIOMETRIC_KEY = os.getenv('BIOMETRIC_KEY', '')
PRIVATE_STORAGE = BASE_DIR / os.getenv('PRIVATE_STORAGE', 'private')
os.environ['DEEPFACE_HOME'] = str(PRIVATE_STORAGE / 'weights')
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_SOFT_TIME_LIMIT = 150
CELERY_TASK_TIME_LIMIT = 180
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BEAT_SCHEDULE = {'purge-private-data': {'task': 'attendance.tasks.purge_expired', 'schedule': 60.0}}
REQUIRE_CLASSIFIER = os.getenv('REQUIRE_CLASSIFIER', '1') == '1'
if not DEBUG and not REQUIRE_CLASSIFIER:
    raise ImproperlyConfigured('Production requires a trained classifier (REQUIRE_CLASSIFIER=1).')
CAPTURE_TTL_SECONDS = int(os.getenv('CAPTURE_TTL_SECONDS', '90'))
JOB_REVIEW_TTL_SECONDS = int(os.getenv('JOB_REVIEW_TTL_SECONDS', '300'))
BIOMETRIC_RETENTION_DAYS = int(os.getenv('BIOMETRIC_RETENTION_DAYS', '365'))
FRAME_RETENTION_SECONDS = int(os.getenv('FRAME_RETENTION_SECONDS', '600'))
DATA_UPLOAD_MAX_MEMORY_SIZE = 6 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 6 * 1024 * 1024
FILE_UPLOAD_HANDLERS = ['attendance.uploads.PrivateMemoryUploadHandler']
