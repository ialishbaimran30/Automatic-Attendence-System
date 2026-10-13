import os
os.environ['SECRET_KEY'] = 'test-only-not-for-deployment'
os.environ['DJANGO_DEBUG'] = '1'
from .settings import *  # noqa
from cryptography.fernet import Fernet
BIOMETRIC_KEY = Fernet.generate_key().decode()
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
ALLOWED_HOSTS = ['testserver', 'localhost', '127.0.0.1']
CELERY_TASK_ALWAYS_EAGER = True
REQUIRE_CLASSIFIER = False
if not os.getenv('TEST_POSTGRES'):
    DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
