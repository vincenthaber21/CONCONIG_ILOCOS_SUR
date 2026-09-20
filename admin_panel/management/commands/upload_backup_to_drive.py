from pathlib import Path

from django.core.management.base import BaseCommand

from helper.db_backup import list_weekly_backups
from helper.google_drive_upload import (
    credentials_setup_hint,
    get_auth_mode,
    get_google_drive_folder_id,
    get_oauth_credentials,
    is_google_drive_upload_enabled,
    resolve_oauth_client_path,
    resolve_oauth_token_path,
    upload_backup_to_drive,
)


class Command(BaseCommand):
    help = 'Upload the latest weekly database backup (or a given file) to Google Drive.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            help='Path to a specific backup file to upload.',
        )

    def handle(self, *args, **options):
        if not is_google_drive_upload_enabled():
            self.stdout.write(self.style.WARNING('GOOGLE_DRIVE_UPLOAD_ENABLED is False.'))
            return

        folder = get_google_drive_folder_id()
        client = resolve_oauth_client_path()
        token = resolve_oauth_token_path()
        self.stdout.write(f'Auth mode: {get_auth_mode()}')
        self.stdout.write(f'Drive folder ID: {folder}')
        self.stdout.write(f'OAuth client: {client or "(not found)"}')
        self.stdout.write(f'OAuth token: {token if token.is_file() else "(not authorized yet)"}')

        if get_auth_mode() == 'oauth' and not client:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(credentials_setup_hint()))
            return

        if get_auth_mode() == 'oauth' and not get_oauth_credentials():
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                'Not authorized yet. Run: python manage.py authorize_google_drive'
            ))
            return

        if options['file']:
            target = Path(options['file'])
        else:
            backups = list_weekly_backups()
            if not backups:
                self.stdout.write(self.style.ERROR('No weekly backup files found.'))
                return
            target = Path(backups[0]['path'])

        self.stdout.write(f'Uploading: {target}')
        ok, message = upload_backup_to_drive(target)
        if ok:
            self.stdout.write(self.style.SUCCESS(message))
        else:
            self.stdout.write(self.style.ERROR(message))
