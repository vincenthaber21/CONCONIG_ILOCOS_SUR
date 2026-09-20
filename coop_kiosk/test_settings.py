"""
Minimal settings for ingestion pipeline tests (SQLite, ingestion app only).
Run: python manage.py test ingestion.tests --settings=coop_kiosk.test_settings
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = 'test-secret-key-for-ingestion-only'
DEBUG = True
ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.auth',
    'rest_framework',
    'ingestion',
]

MIDDLEWARE = []
ROOT_URLCONF = 'coop_kiosk.test_urls'

_SHARED_SQLITE = 'file:ingestion_test_mem?mode=memory&cache=shared'
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': _SHARED_SQLITE,
    },
    'primary': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': _SHARED_SQLITE,
    },
}

DATABASE_ROUTERS = ['ingestion.db_router.PrimaryReplicaRouter']

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [],
    'DEFAULT_PERMISSION_CLASSES': [],
}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_RESULT_BACKEND = 'cache+memory://'
CELERY_BROKER_URL = 'memory://'

INGESTION_API_KEY = 'test-key'
INGESTION_SHARD_COUNT = 4

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'ingestion.metrics': {
            'handlers': ['console'],
            'level': 'INFO',
        },
    },
}

USE_TZ = True
TIME_ZONE = 'UTC'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
