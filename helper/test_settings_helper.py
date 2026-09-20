"""
Tests for settings_helper.py

Run with:
    python manage.py test helper.test_settings_helper
or:
    python -m pytest helper/test_settings_helper.py -v
"""

import os
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestGenerateSecureSecretKey(unittest.TestCase):
    def test_returns_string(self):
        from helper.settings_helper import generate_secure_secret_key
        key = generate_secure_secret_key()
        self.assertIsInstance(key, str)

    def test_minimum_length(self):
        from helper.settings_helper import generate_secure_secret_key
        key = generate_secure_secret_key()
        self.assertGreaterEqual(len(key), 50)

    def test_unique_each_call(self):
        from helper.settings_helper import generate_secure_secret_key
        keys = {generate_secure_secret_key() for _ in range(5)}
        self.assertEqual(len(keys), 5)


class TestValidateEnvironmentSettings(unittest.TestCase):
    def test_development_mode_passes_without_vars(self):
        """Development mode (PRODUCTION=False) should not raise even if vars are missing."""
        from helper.settings_helper import validate_environment_settings
        with patch.dict(os.environ, {'PRODUCTION': 'false'}, clear=False):
            # Should not raise
            validate_environment_settings()

    def test_production_raises_when_missing_vars(self):
        from helper.settings_helper import validate_environment_settings
        env = {
            'PRODUCTION': 'true',
            'DJANGO_SECRET_KEY': '',
            'MAIL_PASSWORD': '',
        }
        with patch.dict(os.environ, env, clear=False):
            # Remove the keys so they're truly missing
            env_without = {k: v for k, v in os.environ.items()
                           if k not in ('DJANGO_SECRET_KEY', 'MAIL_PASSWORD')}
            env_without['PRODUCTION'] = 'true'
            with patch.dict(os.environ, env_without, clear=True):
                from django.core.exceptions import ImproperlyConfigured
                with self.assertRaises(ImproperlyConfigured):
                    validate_environment_settings()

    def test_production_raises_on_short_secret_key(self):
        from helper.settings_helper import validate_environment_settings
        from django.core.exceptions import ImproperlyConfigured
        env = {
            'PRODUCTION': 'true',
            'DJANGO_SECRET_KEY': 'short',
            'MAIL_PASSWORD': 'somepassword',
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ImproperlyConfigured):
                validate_environment_settings()

    def test_production_raises_on_weak_secret_key(self):
        from helper.settings_helper import validate_environment_settings
        from django.core.exceptions import ImproperlyConfigured
        weak_key = 'this_is_a_test_key_that_is_long_enough_but_has_weak_pattern_xyz'
        env = {
            'PRODUCTION': 'true',
            'DJANGO_SECRET_KEY': weak_key,
            'MAIL_PASSWORD': 'somepassword',
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ImproperlyConfigured):
                validate_environment_settings()

    def test_production_passes_with_strong_key(self):
        from helper.settings_helper import validate_environment_settings, generate_secure_secret_key
        strong_key = generate_secure_secret_key() + 'AAABBBCCC'
        env = {
            'PRODUCTION': 'true',
            'DJANGO_SECRET_KEY': strong_key,
            'MAIL_PASSWORD': 'somepassword',
        }
        with patch.dict(os.environ, env, clear=True):
            # Should not raise
            validate_environment_settings()


class TestGetSecureDatabaseConfig(unittest.TestCase):
    def test_returns_sqlite_by_default(self):
        from helper.settings_helper import get_secure_database_config
        with patch.dict(os.environ, {}, clear=True):
            config = get_secure_database_config()
        self.assertIn('default', config)
        self.assertIn('sqlite3', config['default']['ENGINE'])

    def test_sqlite_has_timeout(self):
        from helper.settings_helper import get_secure_database_config
        with patch.dict(os.environ, {}, clear=True):
            config = get_secure_database_config()
        self.assertIn('OPTIONS', config['default'])
        self.assertIn('timeout', config['default']['OPTIONS'])

    def test_db_url_param_returns_dict(self):
        """Passing a db_url should return a valid dict (requires dj_database_url)."""
        from helper.settings_helper import get_secure_database_config
        try:
            import dj_database_url  # noqa: F401
        except ImportError:
            self.skipTest('dj_database_url not installed')
        config = get_secure_database_config(db_url='sqlite:///test.db')
        self.assertIsInstance(config, dict)
        self.assertIn('default', config)


class TestGetSecureSessionSettings(unittest.TestCase):
    def test_development_returns_dict(self):
        from helper.settings_helper import get_secure_session_settings
        with patch.dict(os.environ, {'PRODUCTION': 'false'}, clear=False):
            settings = get_secure_session_settings()
        self.assertIsInstance(settings, dict)

    def test_contains_required_keys(self):
        from helper.settings_helper import get_secure_session_settings
        with patch.dict(os.environ, {'PRODUCTION': 'false'}, clear=False):
            settings = get_secure_session_settings()
        required = ['SESSION_COOKIE_AGE', 'SESSION_COOKIE_HTTPONLY', 'SESSION_COOKIE_SAMESITE']
        for key in required:
            self.assertIn(key, settings)

    def test_production_sets_secure_cookie(self):
        from helper.settings_helper import get_secure_session_settings
        with patch.dict(os.environ, {'PRODUCTION': 'true'}, clear=False):
            settings = get_secure_session_settings()
        self.assertTrue(settings.get('SESSION_COOKIE_SECURE'))

    def test_development_sets_secure_cookie(self):
        from helper.settings_helper import get_secure_session_settings
        with patch.dict(os.environ, {'PRODUCTION': 'false'}, clear=False):
            settings = get_secure_session_settings()
        self.assertTrue(settings.get('SESSION_COOKIE_SECURE'))

    def test_uses_strict_samesite(self):
        from helper.settings_helper import get_secure_session_settings
        settings = get_secure_session_settings()
        self.assertEqual(settings.get('SESSION_COOKIE_SAMESITE'), 'Strict')


class TestGetSecureCsrfSettings(unittest.TestCase):
    def test_returns_dict(self):
        from helper.settings_helper import get_secure_csrf_settings
        with patch.dict(os.environ, {'PRODUCTION': 'false'}, clear=False):
            settings = get_secure_csrf_settings()
        self.assertIsInstance(settings, dict)

    def test_contains_csrf_cookie_httponly(self):
        from helper.settings_helper import get_secure_csrf_settings
        with patch.dict(os.environ, {'PRODUCTION': 'false'}, clear=False):
            settings = get_secure_csrf_settings()
        self.assertIn('CSRF_COOKIE_HTTPONLY', settings)
        self.assertTrue(settings['CSRF_COOKIE_HTTPONLY'])

    def test_production_sets_secure_cookie(self):
        from helper.settings_helper import get_secure_csrf_settings
        with patch.dict(os.environ, {'PRODUCTION': 'true', 'CSRF_TRUSTED_ORIGINS': 'https://example.com'}, clear=False):
            settings = get_secure_csrf_settings()
        self.assertTrue(settings.get('CSRF_COOKIE_SECURE'))

    def test_uses_strict_samesite(self):
        from helper.settings_helper import get_secure_csrf_settings
        settings = get_secure_csrf_settings()
        self.assertEqual(settings.get('CSRF_COOKIE_SAMESITE'), 'Strict')


class TestGetCacheConfig(unittest.TestCase):
    def test_development_uses_locmem(self):
        from helper.settings_helper import get_cache_config
        with patch.dict(os.environ, {'PRODUCTION': 'false'}, clear=True):
            config = get_cache_config()
        self.assertIn('LocMemCache', config['default']['BACKEND'])

    def test_redis_url_uses_redis_backend(self):
        from helper.settings_helper import get_cache_config
        with patch.dict(os.environ, {'REDIS_URL': 'redis://localhost:6379/1'}, clear=True):
            config = get_cache_config()
        self.assertIn('RedisCache', config['default']['BACKEND'])
        self.assertEqual(config['default']['LOCATION'], 'redis://localhost:6379/1')

    def test_memcache_url_uses_memcache_backend(self):
        from helper.settings_helper import get_cache_config
        with patch.dict(os.environ, {'MEMCACHE_URL': '127.0.0.1:11211'}, clear=True):
            config = get_cache_config()
        self.assertIn('PyMemcacheCache', config['default']['BACKEND'])

    def test_production_without_redis_uses_db_cache(self):
        from helper.settings_helper import get_cache_config
        with patch.dict(os.environ, {'PRODUCTION': 'true'}, clear=True):
            config = get_cache_config()
        self.assertIn('DatabaseCache', config['default']['BACKEND'])

    def test_cache_has_timeout(self):
        from helper.settings_helper import get_cache_config
        with patch.dict(os.environ, {}, clear=True):
            config = get_cache_config()
        self.assertIn('TIMEOUT', config['default'])


class TestGetLoggingConfig(unittest.TestCase):
    def test_returns_valid_logging_dict(self):
        from helper.settings_helper import get_logging_config
        config = get_logging_config()
        self.assertIn('version', config)
        self.assertEqual(config['version'], 1)
        self.assertIn('handlers', config)
        self.assertIn('loggers', config)

    def test_development_has_console_handler(self):
        from helper.settings_helper import get_logging_config
        with patch.dict(os.environ, {'PRODUCTION': 'false'}, clear=False):
            config = get_logging_config()
        self.assertIn('console', config['handlers'])

    def test_production_adds_file_handlers(self):
        from helper.settings_helper import get_logging_config
        with patch.dict(os.environ, {'PRODUCTION': 'true'}, clear=False):
            config = get_logging_config(base_dir=Path('/tmp/kiosk-test'))
        self.assertIn('file', config['handlers'])
        self.assertIn('error_file', config['handlers'])
        self.assertIn('/tmp/kiosk-test/logs/errors.log', config['handlers']['error_file']['filename'])

    def test_custom_log_level_respected(self):
        from helper.settings_helper import get_logging_config
        config = get_logging_config(log_level='WARNING')
        self.assertEqual(config['handlers']['console']['level'], 'WARNING')


class TestGetAllowedHosts(unittest.TestCase):
    def test_defaults_to_wildcard_in_development(self):
        from helper.settings_helper import get_allowed_hosts
        with patch.dict(os.environ, {}, clear=True):
            hosts = get_allowed_hosts()
        self.assertEqual(hosts, ['*'])

    def test_env_var_overrides_defaults(self):
        from helper.settings_helper import get_allowed_hosts
        with patch.dict(os.environ, {'ALLOWED_HOSTS': 'example.com,www.example.com'}, clear=True):
            hosts = get_allowed_hosts()
        self.assertEqual(hosts, ['example.com', 'www.example.com'])

    def test_returns_list(self):
        from helper.settings_helper import get_allowed_hosts
        hosts = get_allowed_hosts()
        self.assertIsInstance(hosts, list)


class TestGetCorsSettings(unittest.TestCase):
    def test_development_allows_all_origins(self):
        from helper.settings_helper import get_cors_settings
        with patch.dict(os.environ, {'PRODUCTION': 'false'}, clear=True):
            settings = get_cors_settings()
        self.assertTrue(settings.get('CORS_ALLOW_ALL_ORIGINS'))

    def test_production_does_not_allow_all_origins(self):
        from helper.settings_helper import get_cors_settings
        with patch.dict(os.environ, {'PRODUCTION': 'true', 'CORS_ALLOWED_ORIGINS': 'https://example.com'}, clear=True):
            settings = get_cors_settings()
        self.assertNotIn('CORS_ALLOW_ALL_ORIGINS', settings)

    def test_contains_cors_allow_credentials(self):
        from helper.settings_helper import get_cors_settings
        settings = get_cors_settings()
        self.assertIn('CORS_ALLOW_CREDENTIALS', settings)

    def test_cors_origins_from_env(self):
        from helper.settings_helper import get_cors_settings
        origins = 'https://app.example.com,https://mobile.example.com'
        with patch.dict(os.environ, {'CORS_ALLOWED_ORIGINS': origins}, clear=True):
            settings = get_cors_settings()
        self.assertIn('https://app.example.com', settings['CORS_ALLOWED_ORIGINS'])
        self.assertIn('https://mobile.example.com', settings['CORS_ALLOWED_ORIGINS'])


class TestGetEmailConfig(unittest.TestCase):
    def test_development_uses_console_backend(self):
        from helper.settings_helper import get_email_config
        with patch.dict(os.environ, {'PRODUCTION': 'false'}, clear=True):
            config = get_email_config()
        self.assertIn('console', config['EMAIL_BACKEND'])

    def test_production_uses_smtp_backend(self):
        from helper.settings_helper import get_email_config
        env = {
            'PRODUCTION': 'true',
            'MAIL_SERVER': 'smtp.gmail.com',
            'MAIL_PORT': '587',
            'MAIL_USERNAME': 'test@gmail.com',
            'MAIL_PASSWORD': 'secret',
        }
        with patch.dict(os.environ, env, clear=True):
            config = get_email_config()
        self.assertIn('smtp', config['EMAIL_BACKEND'])

    def test_production_email_port_is_int(self):
        from helper.settings_helper import get_email_config
        env = {
            'PRODUCTION': 'true',
            'MAIL_PORT': '465',
            'MAIL_PASSWORD': 'secret',
        }
        with patch.dict(os.environ, env, clear=True):
            config = get_email_config()
        self.assertIsInstance(config['EMAIL_PORT'], int)
        self.assertEqual(config['EMAIL_PORT'], 465)


class TestGetRateLimitingSettings(unittest.TestCase):
    def test_returns_rest_framework_key(self):
        from helper.settings_helper import get_rate_limiting_settings
        settings = get_rate_limiting_settings()
        self.assertIn('REST_FRAMEWORK', settings)

    def test_throttle_classes_defined(self):
        from helper.settings_helper import get_rate_limiting_settings
        rf = get_rate_limiting_settings()['REST_FRAMEWORK']
        self.assertIn('DEFAULT_THROTTLE_CLASSES', rf)
        self.assertTrue(len(rf['DEFAULT_THROTTLE_CLASSES']) > 0)

    def test_throttle_rates_defined(self):
        from helper.settings_helper import get_rate_limiting_settings
        rf = get_rate_limiting_settings()['REST_FRAMEWORK']
        self.assertIn('DEFAULT_THROTTLE_RATES', rf)
        rates = rf['DEFAULT_THROTTLE_RATES']
        self.assertIn('anon', rates)
        self.assertIn('user', rates)


class TestGetSecurityMiddlewareSettings(unittest.TestCase):
    def test_development_returns_empty_dict(self):
        from helper.settings_helper import get_security_middleware_settings
        with patch.dict(os.environ, {'PRODUCTION': 'false'}, clear=False):
            settings = get_security_middleware_settings()
        self.assertEqual(settings, {})

    def test_production_returns_hsts_settings(self):
        from helper.settings_helper import get_security_middleware_settings
        with patch.dict(os.environ, {'PRODUCTION': 'true'}, clear=False):
            settings = get_security_middleware_settings()
        self.assertIn('SECURE_HSTS_SECONDS', settings)
        self.assertGreater(settings['SECURE_HSTS_SECONDS'], 0)

    def test_production_ssl_redirect_enabled(self):
        from helper.settings_helper import get_security_middleware_settings
        with patch.dict(os.environ, {'PRODUCTION': 'true'}, clear=False):
            settings = get_security_middleware_settings()
        self.assertTrue(settings.get('SECURE_SSL_REDIRECT'))


if __name__ == '__main__':
    unittest.main()
