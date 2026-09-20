"""
settings_helper.py - Enhanced security and performance settings for coop_kiosk
Usage: Import in settings.py: from .settings_helper import *
"""

import os
import secrets
from pathlib import Path
import logging
from typing import Dict, Any, List
import re

# ============================================================================
# ENVIRONMENT VALIDATION & SECURE DEFAULTS
# ============================================================================

def validate_environment_settings():
    """
    Validate critical environment variables are set in production.
    Raises helpful errors if production settings are misconfigured.
    """
    from django.core.exceptions import ImproperlyConfigured
    
    is_production = os.environ.get('PRODUCTION', 'False').lower() == 'true'
    
    if is_production:
        required_vars = [
            'DJANGO_SECRET_KEY',
            'MAIL_PASSWORD',
        ]
        
        missing_vars = [var for var in required_vars if not os.environ.get(var)]
        
        if missing_vars:
            raise ImproperlyConfigured(
                f"Production environment requires these variables: {', '.join(missing_vars)}\n"
                f"Please set them in your environment or .env file."
            )
        
        # Validate secret key strength
        secret_key = os.environ.get('DJANGO_SECRET_KEY', '')
        if len(secret_key) < 50:
            raise ImproperlyConfigured(
                "DJANGO_SECRET_KEY must be at least 50 characters long in production"
            )
        
        # Check for common weak keys
        weak_patterns = ['test', 'demo', '12345', 'password', 'secret']
        if any(pattern in secret_key.lower() for pattern in weak_patterns):
            raise ImproperlyConfigured(
                "DJANGO_SECRET_KEY contains weak patterns. Please use a strong random key."
            )

def generate_secure_secret_key():
    """
    Generate a secure random secret key for Django.
    Use this to create a new secret key for production.
    """
    return secrets.token_urlsafe(50)

# ============================================================================
# DATABASE CONFIGURATION WITH CONNECTION POOLING
# ============================================================================

def get_secure_database_config(db_url: str = None) -> Dict[str, Any]:
    """
    Get database configuration with connection pooling and SSL support.
    Supports SQLite, PostgreSQL, and MySQL.
    """
    import dj_database_url
    
    # Priority: 1. Parameter, 2. Environment, 3. Default SQLite
    database_url = db_url or os.environ.get('DATABASE_URL')
    
    if database_url:
        # Use DATABASE_URL for PostgreSQL/MySQL (production)
        config = dj_database_url.config(
            default=database_url,
            conn_max_age=600,  # Connection persistence for 10 minutes
            conn_health_checks=True,  # Enable connection health checks
            ssl_require=os.environ.get('DB_SSL', 'False').lower() == 'true'
        )
        
        # Add additional optimizations for production databases
        if 'postgresql' in database_url:
            config['OPTIONS'] = {
                'connect_timeout': 10,
                'keepalives': 1,
                'keepalives_idle': 30,
                'keepalives_interval': 10,
                'keepalives_count': 5,
            }
        elif 'mysql' in database_url:
            config['OPTIONS'] = {
                'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
                'charset': 'utf8mb4',
                'connect_timeout': 10,
            }
        
        return {'default': config}
    else:
        return get_sqlite_database_config()


def get_sqlite_database_config(base_dir: Path = None) -> Dict[str, Any]:
    """SQLite database config for local dev and PythonAnywhere deployments."""
    db_path = os.environ.get('SQLITE_DB_PATH')
    if db_path:
        name = db_path
    elif base_dir is not None:
        name = str(base_dir / 'db.sqlite3')
    else:
        name = 'db.sqlite3'

    return {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': name,
            'OPTIONS': {
                'timeout': 20,
            },
        }
    }

# ============================================================================
# SECURITY ENHANCEMENTS
# ============================================================================

def get_secure_session_settings() -> Dict[str, Any]:
    """
    Get secure session settings based on environment.

    ``SESSION_COOKIE_SECURE`` must be False for plain HTTP (e.g. local
    ``http://127.0.0.1:8000``); browsers do not send Secure cookies over HTTP,
    which breaks login and CSRF.
    """
    is_production = os.environ.get('PRODUCTION', 'False').lower() == 'true'

    settings = {
        'SESSION_COOKIE_AGE': 60 * 60 * 24 * 7,  # 7 days
        'SESSION_COOKIE_HTTPONLY': True,
        'SESSION_COOKIE_SAMESITE': 'Strict',
        'SESSION_SAVE_EVERY_REQUEST': True,
        'SESSION_EXPIRE_AT_BROWSER_CLOSE': False,
        'SESSION_COOKIE_SECURE': is_production,
    }

    return settings

def get_secure_csrf_settings() -> Dict[str, Any]:
    """
    Get secure CSRF settings.
    """
    is_production = os.environ.get('PRODUCTION', 'False').lower() == 'true'
    
    settings = {
        'CSRF_COOKIE_HTTPONLY': True,
        'CSRF_USE_SESSIONS': False,  # Must be False so CSRF token is stored in a cookie, not session
        'CSRF_COOKIE_SAMESITE': 'Strict',
        'CSRF_COOKIE_SECURE': is_production,
    }

    trusted_origins_env = os.environ.get('CSRF_TRUSTED_ORIGINS', '')
    cors_origins_env = os.environ.get('CORS_ALLOWED_ORIGINS', '')

    # Keep only non-empty values and align CSRF trusted origins with CORS origins.
    trusted_origins = [origin.strip() for origin in trusted_origins_env.split(',') if origin.strip()]
    cors_origins = [origin.strip() for origin in cors_origins_env.split(',') if origin.strip()]

    # In development, allow rotating Cloudflare tunnel subdomains to avoid repeated 403s.
    dev_defaults = []
    if not is_production:
        dev_defaults = [
            'https://*.trycloudflare.com',
            'https://*.asse.devtunnels.ms',
            'http://localhost:8000',
            'http://127.0.0.1:8000',
            'http://localhost:3000',
            'http://127.0.0.1:3000',
            'http://localhost:8081',
            'http://127.0.0.1:8081',
        ]

    merged_origins = []
    for origin in trusted_origins + cors_origins + dev_defaults:
        if origin not in merged_origins:
            merged_origins.append(origin)

    settings.update({
        'CSRF_TRUSTED_ORIGINS': merged_origins,
    })
    
    return settings

def get_security_middleware_settings():
    """
    Get security middleware settings for production.
    """
    is_production = os.environ.get('PRODUCTION', 'False').lower() == 'true'
    
    if not is_production:
        return {}
    
    return {
        'SECURE_BROWSER_XSS_FILTER': True,
        'SECURE_CONTENT_TYPE_NOSNIFF': True,
        'X_FRAME_OPTIONS': 'DENY',
        'SECURE_HSTS_SECONDS': 31536000,  # 1 year
        'SECURE_HSTS_INCLUDE_SUBDOMAINS': True,
        'SECURE_HSTS_PRELOAD': True,
        'SECURE_SSL_REDIRECT': True,
        'SECURE_PROXY_SSL_HEADER': ('HTTP_X_FORWARDED_PROTO', 'https'),
    }

# ============================================================================
# CACHING CONFIGURATION
# ============================================================================

def get_cache_config() -> Dict[str, Any]:
    """
    Get cache configuration based on environment.
    Supports Redis, Memcached, or local memory.
    """
    redis_url = os.environ.get('REDIS_URL')
    memcache_url = os.environ.get('MEMCACHE_URL')
    is_production = os.environ.get('PRODUCTION', 'False').lower() == 'true'
    
    if redis_url:
        # Redis cache for production
        return {
            'default': {
                'BACKEND': 'django.core.cache.backends.redis.RedisCache',
                'LOCATION': redis_url,
                'OPTIONS': {
                    'socket_connect_timeout': 5,
                    'socket_timeout': 5,
                    'retry_on_timeout': True,
                    'compression': 'zlib',
                },
                'KEY_PREFIX': 'coop_kiosk',
                'TIMEOUT': 300,
                'VERSION': 1,
            }
        }
    elif memcache_url:
        # Memcached cache
        return {
            'default': {
                'BACKEND': 'django.core.cache.backends.memcached.PyMemcacheCache',
                'LOCATION': memcache_url,
                'OPTIONS': {
                    'no_delay': True,
                    'ignore_exc': True,
                },
                'KEY_PREFIX': 'coop_kiosk',
                'TIMEOUT': 300,
            }
        }
    elif is_production:
        # Database caching for production without Redis/Memcached
        return {
            'default': {
                'BACKEND': 'django.core.cache.backends.db.DatabaseCache',
                'LOCATION': 'django_cache_table',
                'TIMEOUT': 300,
                'OPTIONS': {
                    'MAX_ENTRIES': 5000,
                }
            }
        }
    else:
        # Local memory cache for development
        return {
            'default': {
                'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                'LOCATION': 'coop-kiosk-cache',
                'TIMEOUT': 300,
                'OPTIONS': {
                    'MAX_ENTRIES': 10000,
                }
            }
        }

def create_cache_table():
    """
    Create cache table if using database cache.
    Run: python manage.py createcachetable
    """
    from django.core.management import call_command
    try:
        call_command('createcachetable')
        logging.info("Cache table created successfully")
    except Exception as e:
        logging.warning(f"Could not create cache table: {e}")

# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

class SuppressBrokenPipeFilter(logging.Filter):
    """
    Drops harmless client-disconnect noise from Django's development server.

    Django 5.x logs early disconnects on the ``django.server`` logger (see
    ``django.core.servers.basehttp``). Older setups used
    ``django.core.servers.basehttp`` as the logger name in some configs; the
    message is still "- Broken pipe from ..." at INFO.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage().lower()
        return 'broken pipe' not in msg


def dev_server_operator_hints() -> str:
    """
    Short text for scripts or support docs: auto-reload and broken-pipe behavior.
    """
    return (
        "This server auto-reloads when you save Python/template/static changes "
        "(do not use --noreload unless you must). "
        "If you used to see 'Broken pipe from (host, port)' in the console, that "
        "means a browser or mobile client closed the connection before the reply "
        "finished; it is normal, not a server failure."
    )


def get_logging_config(log_level: str = None, base_dir: Path = None) -> Dict[str, Any]:
    """
    Get comprehensive logging configuration.

    ``base_dir`` should be Django's BASE_DIR so log files are written under
    ``<project>/logs/`` regardless of the process working directory (required
    on PythonAnywhere and other WSGI hosts).
    """
    is_production = os.environ.get('PRODUCTION', 'False').lower() == 'true'
    log_level = log_level or os.environ.get('LOG_LEVEL', 'INFO' if is_production else 'DEBUG')
    
    handlers = {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose' if is_production else 'simple',
            'level': log_level,
        }
    }
    
    # Add file logging in production
    file_handlers_enabled = False
    if is_production:
        log_dir = (Path(base_dir) / 'logs') if base_dir is not None else Path('logs')
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handlers_enabled = True
        except OSError:
            file_handlers_enabled = False

        if file_handlers_enabled:
            handlers.update({
                'file': {
                    'class': 'logging.handlers.RotatingFileHandler',
                    'filename': str(log_dir / 'django.log'),
                    'maxBytes': 10 * 1024 * 1024,  # 10 MB
                    'backupCount': 10,
                    'formatter': 'verbose',
                    'level': 'WARNING',
                },
                'error_file': {
                    'class': 'logging.handlers.RotatingFileHandler',
                    'filename': str(log_dir / 'errors.log'),
                    'maxBytes': 10 * 1024 * 1024,
                    'backupCount': 30,
                    'formatter': 'verbose',
                    'level': 'ERROR',
                },
                'mobile_api_file': {
                    'class': 'logging.handlers.RotatingFileHandler',
                    'filename': str(log_dir / 'mobile_api.log'),
                    'maxBytes': 5 * 1024 * 1024,  # 5 MB
                    'backupCount': 5,
                    'formatter': 'verbose',
                    'level': 'INFO',
                },
            })
    
    production_file_handlers = ['console', 'error_file'] if file_handlers_enabled else ['console']
    mobile_api_handlers = ['console', 'mobile_api_file'] if file_handlers_enabled else ['console']

    return {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'verbose': {
                'format': '[{levelname}] {asctime} {name} {module}:{lineno} {message}',
                'style': '{',
            },
            'simple': {
                'format': '[{levelname}] {message}',
                'style': '{',
            },
            'json': {
                'format': '{"time": "%(asctime)s", "level": "%(levelname)s", "name": "%(name)s", "message": "%(message)s"}',
            },
        },
        'handlers': handlers,
        'filters': {
            'suppress_broken_pipe': {
                '()': 'helper.settings_helper.SuppressBrokenPipeFilter',
            },
        },
        'loggers': {
            'django': {
                'handlers': ['console'],
                'level': 'INFO',
                'propagate': False,
            },
            'django.request': {
                'handlers': production_file_handlers,
                'level': 'WARNING',
                'propagate': False,
            },
            'django.db.backends': {
                'handlers': ['console'],
                'level': 'ERROR',  # Don't log SQL queries in production
                'propagate': False,
            },
            # Dev server client disconnects (Django 5.x uses logger "django.server").
            'django.server': {
                'handlers': ['console'],
                'level': 'INFO',
                'filters': ['suppress_broken_pipe'],
                'propagate': False,
            },
            # Legacy/alternate logger name; harmless if unused.
            'django.core.servers.basehttp': {
                'handlers': ['console'],
                'level': 'INFO',
                'filters': ['suppress_broken_pipe'],
                'propagate': False,
            },
            'mobile_api': {
                'handlers': mobile_api_handlers if is_production else ['console'],
                'level': log_level,
                'propagate': False,
            },
            'admin_panel': {
                'handlers': ['console'],
                'level': log_level,
                'propagate': False,
            },
        },
    }

# ============================================================================
# PERFORMANCE OPTIMIZATIONS
# ============================================================================

def get_performance_settings() -> Dict[str, Any]:
    """
    Get performance optimization settings.
    """
    is_production = os.environ.get('PRODUCTION', 'False').lower() == 'true'
    
    settings = {
        # Database optimizations
        'CONN_HEALTH_CHECKS': True,
        'CONN_MAX_AGE': 600,  # 10 minutes connection persistence
        
        # Data upload limits
        'DATA_UPLOAD_MAX_NUMBER_FIELDS': 2000,
        'DATA_UPLOAD_MAX_MEMORY_SIZE': 5242880,  # 5 MB
        
        # Template caching in production
        'TEMPLATES': [],  # Will be configured by main settings
        
        # Static files
        'STATICFILES_STORAGE': 'django.contrib.staticfiles.storage.ManifestStaticFilesStorage',
        'STATIC_ROOT': 'staticfiles',
    }
    
    if is_production:
        settings.update({
            # Enable GZip compression (requires whitenoise)
            'MIDDLEWARE': ['whitenoise.middleware.WhiteNoiseMiddleware'] if 'whitenoise' in str(__name__) else [],
            'STATICFILES_STORAGE': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
        })
    
    return settings

# ============================================================================
# ALLOWED HOSTS & CORS CONFIGURATION
# ============================================================================

def get_allowed_hosts() -> List[str]:
    """
    Get allowed hosts from environment or return safe defaults.
    """
    production_hosts = os.environ.get('ALLOWED_HOSTS', '')
    
    if production_hosts:
        return [host.strip() for host in production_hosts.split(',') if host.strip()]
    
    is_production = os.environ.get('PRODUCTION', 'False').lower() == 'true'
    if is_production:
        return []
    
    return ['*']


def get_static_files_settings() -> Dict[str, Any]:
    """
    WhiteNoise static file settings for production deployments (e.g. PythonAnywhere).
    """
    is_production = os.environ.get('PRODUCTION', 'False').lower() == 'true'
    debug = os.environ.get('DEBUG', 'False' if is_production else 'True').lower() == 'true'

    settings: Dict[str, Any] = {
        'WHITENOISE_USE_FINDERS': debug,
        'WHITENOISE_AUTOREFRESH': debug,
    }

    if is_production or not debug:
        settings['STORAGES'] = {
            'default': {
                'BACKEND': 'django.core.files.storage.FileSystemStorage',
            },
            'staticfiles': {
                'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage',
            },
        }

    return settings

def get_cors_settings() -> Dict[str, Any]:
    """
    Get CORS settings for mobile app integration.
    """
    is_production = os.environ.get('PRODUCTION', 'False').lower() == 'true'
    cors_origins = os.environ.get('CORS_ALLOWED_ORIGINS', '')
    
    allowed_origins = []
    if cors_origins:
        allowed_origins = [origin.strip() for origin in cors_origins.split(',')]
    elif not is_production:
        # Development defaults
        allowed_origins = [
            "http://localhost:3000",
            "http://localhost:8081",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:8081",
        ]
    
    settings = {
        'CORS_ALLOWED_ORIGINS': allowed_origins,
        'CORS_ALLOW_CREDENTIALS': True,
        'CORS_ALLOW_METHODS': [
            'DELETE', 'GET', 'OPTIONS', 'PATCH', 'POST', 'PUT'
        ],
        'CORS_ALLOW_HEADERS': [
            'accept', 'accept-encoding', 'authorization', 'content-type',
            'dnt', 'origin', 'user-agent', 'x-csrftoken', 'x-requested-with'
        ],
    }
    
    if not is_production and not cors_origins:
        settings['CORS_ALLOW_ALL_ORIGINS'] = True
    
    return settings

# ============================================================================
# RATE LIMITING & THROTTLING
# ============================================================================

def get_rate_limiting_settings() -> Dict[str, Any]:
    """
    Get rate limiting configuration for API protection.
    """
    return {
        'REST_FRAMEWORK': {
            'DEFAULT_THROTTLE_CLASSES': [
                'rest_framework.throttling.AnonRateThrottle',
                'rest_framework.throttling.UserRateThrottle',
            ],
            'DEFAULT_THROTTLE_RATES': {
                'anon': '100/day',      # Anonymous users
                'user': '1000/day',     # Authenticated users
                'mobile': '500/hour',   # Mobile API users
                'login': '10/minute',   # Login attempts
            },
        }
    }

# ============================================================================
# MIDDLEWARE SECURITY ENHANCEMENTS
# ============================================================================

SECURE_MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',  # Always first
    'corsheaders.middleware.CorsMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # For static files
]

# ============================================================================
# EMAIL CONFIGURATION
# ============================================================================

def get_email_config() -> Dict[str, Any]:
    """
    Get email configuration with fallback to console in development.
    """
    is_production = os.environ.get('PRODUCTION', 'False').lower() == 'true'
    
    if not is_production:
        # Use console backend in development
        return {
            'EMAIL_BACKEND': 'django.core.mail.backends.console.EmailBackend',
        }
    
    # Production email settings
    return {
        'EMAIL_BACKEND': 'django.core.mail.backends.smtp.EmailBackend',
        'EMAIL_HOST': os.environ.get('MAIL_SERVER', 'smtp.gmail.com'),
        'EMAIL_PORT': int(os.environ.get('MAIL_PORT', '587')),
        'EMAIL_USE_TLS': os.environ.get('MAIL_USE_TLS', 'True').lower() == 'true',
        'EMAIL_HOST_USER': os.environ.get('MAIL_USERNAME'),
        'EMAIL_HOST_PASSWORD': os.environ.get('MAIL_PASSWORD'),
        'DEFAULT_FROM_EMAIL': os.environ.get('MAIL_DEFAULT_SENDER', 'BAGNOS MPC <noreply@coopkiosk.com>'),
        'ADMIN_EMAIL': os.environ.get('ADMIN_EMAIL'),
        'DAILY_REPORT_EMAIL': os.environ.get('DAILY_REPORT_EMAIL'),
    }

# ============================================================================
# HEALTH CHECK ENDPOINTS
# ============================================================================

def setup_health_checks():
    """
    Configure health check endpoints for monitoring.
    """
    return {
        'HEALTH_CHECKS': {
            'database': 'django_healthchecks.contrib.check_database',
            'cache': 'django_healthchecks.contrib.check_cache',
            'storage': 'django_healthchecks.contrib.check_storage',
        }
    }

# ============================================================================
# BACKUP & MAINTENANCE
# ============================================================================

def configure_automatic_backups():
    """
    Configure automatic database backup settings.
    """
    return {
        'BACKUP_ENABLED': os.environ.get('BACKUP_ENABLED', 'False').lower() == 'true',
        'BACKUP_INTERVAL_HOURS': int(os.environ.get('BACKUP_INTERVAL_HOURS', '24')),
        'BACKUP_RETENTION_DAYS': int(os.environ.get('BACKUP_RETENTION_DAYS', '30')),
        'BACKUP_PATH': os.environ.get('BACKUP_PATH', 'backups/database/'),
        'SQLITE_WEEKLY_BACKUP_ENABLED': os.environ.get(
            'SQLITE_WEEKLY_BACKUP_ENABLED', 'True'
        ).lower() == 'true',
        'SQLITE_WEEKLY_BACKUP_FOLDER': os.environ.get(
            'SQLITE_WEEKLY_BACKUP_FOLDER', 'backups/sqlite_weekly'
        ),
        'SQLITE_WEEKLY_BACKUP_RETENTION_WEEKS': int(
            os.environ.get('SQLITE_WEEKLY_BACKUP_RETENTION_WEEKS', '52')
        ),
    }

# ============================================================================
# MAIN EXECUTION - APPLY SETTINGS
# ============================================================================

def apply_settings(settings_module):
    """
    Apply all security and performance settings to the Django settings module.
    Call this at the end of your settings.py file.
    """
    # Validate environment
    validate_environment_settings()
    
    # Database configuration
    settings_module.DATABASES = get_secure_database_config()
    
    # Security settings
    settings_module.update(get_secure_session_settings())
    settings_module.update(get_secure_csrf_settings())
    settings_module.update(get_security_middleware_settings())
    
    # Performance settings
    settings_module.CACHES = get_cache_config()
    settings_module.update(get_performance_settings())
    
    # Logging
    settings_module.LOGGING = get_logging_config(
        base_dir=getattr(settings_module, 'BASE_DIR', None),
    )
    
    # Hosts & CORS
    settings_module.ALLOWED_HOSTS = get_allowed_hosts()
    settings_module.update(get_cors_settings())
    
    # Email
    settings_module.update(get_email_config())
    
    # Rate limiting
    if 'REST_FRAMEWORK' in settings_module:
        settings_module.REST_FRAMEWORK.update(get_rate_limiting_settings()['REST_FRAMEWORK'])
    else:
        settings_module.REST_FRAMEWORK = get_rate_limiting_settings()['REST_FRAMEWORK']
    
    # Create log directories if they don't exist
    if settings_module.DEBUG is False:
        import os
        log_dirs = ['logs', 'backups/database']
        for log_dir in log_dirs:
            os.makedirs(log_dir, exist_ok=True)

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def generate_env_file():
    """
    Generate a sample .env file with secure defaults.
    Run this to create your initial environment configuration.
    """
    env_template = f"""
# Django Configuration
DJANGO_SECRET_KEY={generate_secure_secret_key()}
DEBUG=False
PRODUCTION=True
ALLOWED_HOSTS=your-domain.com,www.your-domain.com

# Database (choose one)
# PostgreSQL (Recommended for production)
DATABASE_URL=postgresql://user:password@localhost:5432/coop_kiosk
DB_SSL=True

# Redis Cache (Recommended for production)
REDIS_URL=redis://localhost:6379/1

# Email Configuration
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=True
MAIL_USERNAME=your-email@gmail.com
MAIL_PASSWORD=your-app-password
MAIL_DEFAULT_SENDER=BAGNOS MPC <noreply@coopkiosk.com>
ADMIN_EMAIL=admin@coopkiosk.com

# CORS Settings
CORS_ALLOWED_ORIGINS=https://your-domain.com,https://mobile-app-domain.com

# CSRF Trusted Origins
CSRF_TRUSTED_ORIGINS=https://your-domain.com

# Backup Configuration
BACKUP_ENABLED=True
BACKUP_INTERVAL_HOURS=24
BACKUP_RETENTION_DAYS=30

# Feature Toggles
PRODUCT_FEE_ENABLED=False

# Logging
LOG_LEVEL=INFO
"""
    
    with open('.env.example', 'w') as f:
        f.write(env_template)
    print(".env.example file created. Copy to .env and update with your values.")

if __name__ == '__main__':
    # If run directly, generate sample .env file
    generate_env_file()