"""
Upload weekly database backups to Google Drive.

Personal Google Drive folders must use OAuth (your Google account).
Service accounts have no storage quota on personal Drive.

Setup (OAuth — recommended):
1. Google Cloud → APIs → enable Google Drive API.
2. Credentials → Create OAuth client ID → Desktop app → download JSON.
3. Save as google_drive_oauth_client.json in the project root.
4. Run: python manage.py authorize_google_drive
5. Run: python manage.py upload_backup_to_drive
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional, Tuple, Union

from django.conf import settings

logger = logging.getLogger(__name__)

# Per-file access to files created/opened by this app (works for uploads to a folder you own)
DRIVE_SCOPES = ['https://www.googleapis.com/auth/drive.file']


def is_google_drive_upload_enabled() -> bool:
    return bool(getattr(settings, 'GOOGLE_DRIVE_UPLOAD_ENABLED', False))


def get_google_drive_folder_id() -> str:
    return str(getattr(settings, 'GOOGLE_DRIVE_FOLDER_ID', '') or '').strip()


def get_auth_mode() -> str:
    """oauth (personal Drive) or service_account (Shared Drive / Workspace)."""
    mode = str(getattr(settings, 'GOOGLE_DRIVE_AUTH_MODE', 'oauth')).lower().strip()
    if mode in ('oauth', 'service_account'):
        return mode
    return 'oauth'


def get_service_account_email() -> str:
    return str(
        getattr(settings, 'GOOGLE_DRIVE_SERVICE_ACCOUNT_EMAIL', '') or ''
    ).strip()


def _base_dir() -> Path:
    return Path(settings.BASE_DIR)


def _resolve_path(setting_name: str, default_name: str) -> Path:
    raw = getattr(settings, setting_name, None) or ''
    path = Path(raw) if raw else _base_dir() / default_name
    if not path.is_absolute():
        path = _base_dir() / path
    return path


def resolve_oauth_client_path() -> Optional[Path]:
    path = _resolve_path('GOOGLE_DRIVE_OAUTH_CLIENT_JSON', 'google_drive_oauth_client.json')
    if not path.is_file():
        # Auto-detect client_secret*.json from Google download
        for candidate in sorted(_base_dir().glob('client_secret*.json')):
            if _is_oauth_client_json(candidate):
                return candidate
    return path if path.is_file() and _is_oauth_client_json(path) else None


def resolve_oauth_token_path() -> Path:
    return _resolve_path('GOOGLE_DRIVE_TOKEN_JSON', 'google_drive_token.json')


def _is_oauth_client_json(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return False
    if 'installed' in data or 'web' in data:
        return True
    return bool(data.get('client_id') and data.get('client_secret'))


def credentials_setup_hint() -> str:
    folder_id = get_google_drive_folder_id()
    client_path = _base_dir() / 'google_drive_oauth_client.json'
    redirect_uris = '  and  '.join(get_oauth_redirect_uris())
    lines = [
        'Google Drive OAuth setup (required for personal Drive):',
        '  1. Google Cloud - Credentials - OAuth client (Desktop app preferred)',
        f'  2. Save the JSON as:\n     {client_path}',
        '     If using Web client, add Authorized redirect URIs:',
        f'     {redirect_uris}',
        '  3. Run: python manage.py authorize_google_drive',
        '     (sign in with the Google account that owns the backup folder)',
    ]
    if folder_id:
        lines.append(
            f'  4. Folder: https://drive.google.com/drive/folders/{folder_id}'
        )
    lines.append('  5. Run: python manage.py upload_backup_to_drive')
    return '\n'.join(lines)


def _is_service_account_key(path: Path, expected_email: str = '') -> bool:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return False
    if data.get('type') != 'service_account':
        return False
    if not data.get('private_key') or not data.get('client_email'):
        return False
    if expected_email and data.get('client_email') != expected_email:
        return False
    return True


def resolve_service_account_path() -> Optional[Path]:
    base_dir = _base_dir()
    expected_email = get_service_account_email()
    configured = (
        getattr(settings, 'GOOGLE_DRIVE_CREDENTIALS_JSON', None)
        or getattr(settings, 'GOOGLE_APPLICATION_CREDENTIALS', None)
        or ''
    )
    candidates: list[Path] = []
    if configured:
        p = Path(configured)
        candidates.append(p if p.is_absolute() else base_dir / p)
    candidates.append(base_dir / 'google_drive_service_account.json')

    skip_names = {'package-lock.json', 'package.json', 'app.json', 'eas.json'}
    for path in sorted(base_dir.glob('*.json')):
        if path.name not in skip_names and path not in candidates:
            candidates.append(path)

    for path in candidates:
        if path.is_file() and _is_service_account_key(path, expected_email):
            return path
    return None


def get_oauth_credentials():
    """Load or refresh OAuth user credentials."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    token_path = resolve_oauth_token_path()
    if not token_path.is_file():
        return None

    creds = Credentials.from_authorized_user_file(str(token_path), DRIVE_SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json(), encoding='utf-8')
        logger.info('Refreshed Google Drive OAuth token.')
    return creds


def get_oauth_port() -> int:
    return int(getattr(settings, 'GOOGLE_DRIVE_OAUTH_PORT', 8090))


def get_oauth_host() -> str:
    return str(getattr(settings, 'GOOGLE_DRIVE_OAUTH_HOST', '127.0.0.1')).strip()


def get_oauth_redirect_uris() -> list[str]:
    port = get_oauth_port()
    host = get_oauth_host()
    uris = [f'http://{host}:{port}/']
    if host != 'localhost':
        uris.append(f'http://localhost:{port}/')
    return uris


def get_oauth_redirect_uri() -> str:
    return get_oauth_redirect_uris()[0]


def _load_oauth_client_config(client_path: Path) -> dict:
    return json.loads(client_path.read_text(encoding='utf-8'))


def _to_installed_client_config(client_config: dict) -> dict:
    """Convert web or installed client JSON for InstalledAppFlow local server."""
    redirect_uris = get_oauth_redirect_uris()
    if 'installed' in client_config:
        installed = dict(client_config['installed'])
        installed['redirect_uris'] = redirect_uris
        return {'installed': installed}
    if 'web' in client_config:
        web = client_config['web']
        return {
            'installed': {
                'client_id': web['client_id'],
                'client_secret': web['client_secret'],
                'auth_uri': web.get('auth_uri', 'https://accounts.google.com/o/oauth2/auth'),
                'token_uri': web.get('token_uri', 'https://oauth2.googleapis.com/token'),
                'redirect_uris': redirect_uris,
            }
        }
    raise ValueError('Invalid OAuth client JSON (expected "installed" or "web" section).')


def run_oauth_authorization() -> Tuple[bool, str]:
    """Open browser once so the user can authorize their Google account."""
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        return False, 'Install: pip install google-auth-oauthlib'

    client_path = resolve_oauth_client_path()
    if client_path is None:
        return False, credentials_setup_hint()

    token_path = resolve_oauth_token_path()
    port = get_oauth_port()
    host = get_oauth_host()
    client_config = _load_oauth_client_config(client_path)

    try:
        installed_config = _to_installed_client_config(client_config)
        flow = InstalledAppFlow.from_client_config(installed_config, DRIVE_SCOPES)
        creds = flow.run_local_server(
            host=host,
            port=port,
            prompt='consent',
            access_type='offline',
            redirect_uri_trailing_slash=True,
            open_browser=True,
        )
    except ValueError as exc:
        return False, str(exc)
    except OSError as exc:
        if getattr(exc, 'winerror', None) == 10048 or 'Address already in use' in str(exc):
            return False, (
                f'Port {port} is already in use (often Django runserver on 8000). '
                f'Stop the other app or set GOOGLE_DRIVE_OAUTH_PORT=8090 in settings, '
                f'then add http://127.0.0.1:8090/ to Google Cloud redirect URIs.'
            )
        return False, str(exc)
    except Exception as exc:
        err = str(exc)
        if 'redirect_uri_mismatch' in err:
            uris = '\n     '.join(get_oauth_redirect_uris())
            return False, (
                'redirect_uri_mismatch: In Google Cloud Console add these redirect URIs, '
                'save, wait 1 minute, then retry:\n'
                f'     {uris}'
            )
        if 'access_denied' in err or 'access blocked' in err.lower():
            return False, (
                'Google blocked sign-in: app is in Testing mode. Fix in Google Cloud Console:\n'
                '  1. APIs & Services -> OAuth consent screen\n'
                '  2. Under Test users -> Add users\n'
                '  3. Add: vicnehaber21@gmail.com (your Google account)\n'
                '  4. Save, wait 1 minute, run authorize_google_drive again'
            )
        return False, err

    token_path.write_text(creds.to_json(), encoding='utf-8')
    return True, f'Authorized. Token saved to {token_path}'


def _build_drive_service(credentials):
    from googleapiclient.discovery import build
    return build('drive', 'v3', credentials=credentials, cache_discovery=False)


def _get_drive_service() -> Tuple[Optional[object], Union[str, dict]]:
    folder_id = get_google_drive_folder_id()
    if not folder_id:
        return None, 'GOOGLE_DRIVE_FOLDER_ID is not configured.'

    try:
        from google.oauth2 import service_account
    except ImportError:
        return None, (
            'Google Drive libraries not installed. Run: pip install '
            'google-api-python-client google-auth google-auth-oauthlib'
        )

    mode = get_auth_mode()

    if mode == 'oauth':
        creds = get_oauth_credentials()
        if creds is None:
            return None, (
                'Google Drive not authorized yet.\n' + credentials_setup_hint()
            )
        service = _build_drive_service(creds)
        return service, folder_id

    # service_account — only works with Google Workspace Shared Drives
    creds_path = resolve_service_account_path()
    if creds_path is None:
        return None, 'Service account JSON not found.'

    credentials = service_account.Credentials.from_service_account_file(
        str(creds_path),
        scopes=DRIVE_SCOPES,
    )
    service = _build_drive_service(credentials)
    return service, folder_id


def _escape_drive_query_value(value: str) -> str:
    return value.replace("'", "\\'")


def upload_backup_to_drive(file_path: Path) -> Tuple[bool, str]:
    """Upload or update a backup file in the configured Google Drive folder."""
    if not is_google_drive_upload_enabled():
        return False, 'Google Drive upload is disabled.'

    file_path = Path(file_path)
    if not file_path.is_file():
        return False, f'Backup file not found: {file_path}'

    service, folder_id = _get_drive_service()
    if service is None:
        return False, folder_id

    try:
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        return False, 'googleapiclient is not installed.'

    safe_name = _escape_drive_query_value(file_path.name)
    query = f"name='{safe_name}' and '{folder_id}' in parents and trashed=false"

    try:
        existing = (
            service.files()
            .list(q=query, fields='files(id, name)', supportsAllDrives=True)
            .execute()
            .get('files', [])
        )

        media = MediaFileUpload(
            str(file_path),
            resumable=True,
            mimetype='application/sql' if file_path.suffix == '.sql' else None,
        )

        if existing:
            file_id = existing[0]['id']
            service.files().update(
                fileId=file_id,
                media_body=media,
                supportsAllDrives=True,
            ).execute()
            return True, f'Updated on Google Drive: {file_path.name}'

        metadata = {'name': file_path.name, 'parents': [folder_id]}
        created = (
            service.files()
            .create(
                body=metadata,
                media_body=media,
                fields='id',
                supportsAllDrives=True,
            )
            .execute()
        )
        file_id = created.get('id', '')
        return True, f'Uploaded to Google Drive: {file_path.name} (id={file_id})'
    except Exception as exc:
        logger.exception('Google Drive upload failed for %s', file_path.name)
        err = str(exc)
        if 'storageQuotaExceeded' in err or 'do not have storage quota' in err:
            return False, (
                'Service accounts cannot upload to personal Google Drive. '
                'Set GOOGLE_DRIVE_AUTH_MODE=oauth, add google_drive_oauth_client.json, '
                'then run: python manage.py authorize_google_drive'
            )
        if 'accessNotConfigured' in err or 'has not been used in project' in err:
            return False, (
                'Enable Google Drive API in Google Cloud Console, wait a few minutes, retry.'
            )
        if 'invalid_grant' in err.lower():
            return False, (
                'OAuth token expired. Run: python manage.py authorize_google_drive'
            )
        return False, err


# Back-compat alias used by upload command
def resolve_credentials_path() -> Optional[Path]:
    if get_auth_mode() == 'oauth':
        token = resolve_oauth_token_path()
        return token if token.is_file() else resolve_oauth_client_path()
    return resolve_service_account_path()
