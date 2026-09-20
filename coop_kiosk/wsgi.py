"""
WSGI config for coop_kiosk project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os
import sys
import logging

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'coop_kiosk.settings')

# Get the base WSGI application
base_application = get_wsgi_application()

# Wrap application to handle broken pipe errors gracefully
# This creates a pipeline tunnel for mobile app users
def application(environ, start_response):
    """
    WSGI application wrapper that handles broken pipe errors.
    Suppresses broken pipe errors from mobile clients that disconnect early.
    """
    try:
        return base_application(environ, start_response)
    except (BrokenPipeError, ConnectionResetError, OSError) as e:
        # Check if it's a broken pipe error (common with mobile apps)
        error_str = str(e).lower()
        if 'broken pipe' in error_str or 'connection reset' in error_str:
            # Client disconnected - this is normal for mobile apps
            # Log at debug level instead of error
            logger = logging.getLogger('django.server')
            logger.debug(
                f"Client disconnected: {environ.get('PATH_INFO', 'unknown')} "
                f"from {environ.get('REMOTE_ADDR', 'unknown')}"
            )
            # Return empty response to prevent error propagation
            try:
                start_response('200 OK', [('Content-Type', 'text/plain')])
                return [b'']
            except:
                # If start_response fails, client already disconnected
                pass
            return []
        # Re-raise other errors
        raise
