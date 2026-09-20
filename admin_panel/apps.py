from django.apps import AppConfig, apps
import logging
import os
import threading
import time

logger = logging.getLogger(__name__)


class AdminPanelConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'admin_panel'
    
    def ready(self):
        """Called when Django starts. Start the scheduler here."""
        # Prevent running in migrations, tests, or shell
        import sys

        # Wire site-wide audit signals (login / logout / failed login).
        try:
            from . import signals  # noqa: F401
        except Exception as e:
            logger.error(f"Failed to load audit signals: {str(e)}", exc_info=True)
        
        # Check if we're in a management command context
        is_management_command = any([
            'migrate' in sys.argv,
            'makemigrations' in sys.argv,
            'test' in sys.argv,
            'shell' in sys.argv,
            'shell_plus' in sys.argv,
            'collectstatic' in sys.argv,
        ])
        
        # Only start scheduler when running the server.
        # Defer DB access until after AppConfig.ready() finishes — querying
        # ReportScheduleConfig here triggers Django's APPS_NOT_READY warning.
        if not is_management_command and (
            'runserver' in sys.argv or 
            'gunicorn' in sys.argv or 
            'uwsgi' in sys.argv or
            os.environ.get('RUN_MAIN') == 'true'  # Django auto-reload check
        ):
            threading.Thread(
                target=self._start_scheduler_when_apps_ready,
                name='admin-panel-scheduler-start',
                daemon=True,
            ).start()

        # Initialize performance helpers (safe after app registry is ready)
        try:
            from admin_panel_helper import initialize_performance_helpers
            initialize_performance_helpers()
        except Exception as e:
            logger.error(f"Failed to initialize performance helpers: {str(e)}", exc_info=True)

    @staticmethod
    def _start_scheduler_when_apps_ready():
        """Wait until django.apps is fully ready, then start APScheduler."""
        try:
            for _ in range(200):  # ~2s max
                if apps.ready:
                    break
                time.sleep(0.01)
            else:
                logger.error("Timed out waiting for Django apps to become ready; scheduler not started")
                return

            from .scheduler import start_scheduler
            start_scheduler()
        except Exception as e:
            logger.error(f"Failed to start scheduler: {str(e)}", exc_info=True)
