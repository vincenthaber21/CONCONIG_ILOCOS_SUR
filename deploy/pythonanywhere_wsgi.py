"""
PythonAnywhere WSGI configuration for coop_kiosk.

Copy this into the PythonAnywhere Web tab → WSGI configuration file
(replace the default file contents), then update the values marked CHANGE ME.
"""

import os
import sys

# Project root on PythonAnywhere
path = '/home/dtikiosk/kiosk'
if path not in sys.path:
    sys.path.insert(0, path)

# --- Production environment (required for static files + security) ---
os.environ['DJANGO_SETTINGS_MODULE'] = 'coop_kiosk.settings'
os.environ['PRODUCTION'] = 'true'
os.environ['DEBUG'] = 'false'
os.environ['ALLOWED_HOSTS'] = 'dtikiosk.pythonanywhere.com'

# CHANGE ME: at least 50 random characters
os.environ['DJANGO_SECRET_KEY'] = 'replace-with-a-long-random-secret-key'

# SQLite (no MySQL DATABASE_URL needed)
os.environ['USE_SQLITE'] = 'true'
# Optional custom path (default: /home/dtikiosk/kiosk/db.sqlite3)
# os.environ['SQLITE_DB_PATH'] = '/home/dtikiosk/kiosk/db.sqlite3'

# For MySQL on PythonAnywhere instead, remove USE_SQLITE and set:
# os.environ['DATABASE_URL'] = 'mysql://dtikiosk:YOUR_DB_PASSWORD@dtikiosk.mysql.pythonanywhere-services.com/dtikiosk$default'

# Optional: email (uses defaults from settings.py if omitted)
# os.environ['MAIL_PASSWORD'] = 'your-app-password'

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
