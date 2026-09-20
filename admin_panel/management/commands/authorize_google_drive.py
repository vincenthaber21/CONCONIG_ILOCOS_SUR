from django.core.management.base import BaseCommand

import json

from helper.google_drive_upload import (
    credentials_setup_hint,
    get_auth_mode,
    get_oauth_redirect_uris,
    resolve_oauth_client_path,
    resolve_oauth_token_path,
    run_oauth_authorization,
)


class Command(BaseCommand):
    help = (
        'Authorize Google Drive with your personal Google account (OAuth). '
        'Required for uploading backups to a personal Drive folder.'
    )

    def handle(self, *args, **options):
        self.stdout.write(f'Auth mode: {get_auth_mode()}')
        client = resolve_oauth_client_path()
        token = resolve_oauth_token_path()

        if not client:
            self.stdout.write(self.style.ERROR('OAuth client JSON not found.'))
            self.stdout.write('')
            self.stdout.write(credentials_setup_hint())
            return

        self.stdout.write(f'OAuth client: {client}')
        self.stdout.write(f'Token file:   {token}')

        try:
            cfg = json.loads(client.read_text(encoding='utf-8'))
            if 'web' in cfg and 'installed' not in cfg:
                self.stdout.write('')
                self.stdout.write(self.style.WARNING(
                    'Web OAuth client detected. Add these redirect URIs in Google Cloud Console:'
                ))
                for uri in get_oauth_redirect_uris():
                    self.stdout.write(f'  {uri}')
                self.stdout.write(
                    '  (Credentials -> your OAuth client -> Authorized redirect URIs -> Save)'
                )
        except (OSError, json.JSONDecodeError):
            pass

        self.stdout.write('')
        self.stdout.write(
            'Opening browser - sign in with the Google account that owns the backup folder...'
        )
        self.stdout.write('')
        self.stdout.write(
            'If Google says "Access blocked" / app not verified: add your Gmail under '
            'OAuth consent screen -> Test users in Google Cloud Console.'
        )
        self.stdout.write('')

        ok, message = run_oauth_authorization()
        if ok:
            self.stdout.write(self.style.SUCCESS(message))
            self.stdout.write(self.style.SUCCESS('Next: python manage.py upload_backup_to_drive'))
        else:
            self.stdout.write(self.style.ERROR(message))
