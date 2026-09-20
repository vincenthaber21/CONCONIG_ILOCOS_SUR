from django.core.management.base import BaseCommand

from helper.db_backup import (
    create_weekly_database_backup,
    describe_active_database,
    get_database_engine,
    get_mysql_backup_folder,
    get_sqlite_backup_folder,
    get_week_label,
    list_weekly_backups,
    prune_old_weekly_backups,
    resolve_mysqldump_executable,
)


class Command(BaseCommand):
    help = (
        'Create a weekly backup of the active database from settings.DATABASES '
        '(MySQL .sql or SQLite .sqlite3).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Overwrite this week\'s backup if it already exists.',
        )
        parser.add_argument(
            '--list',
            action='store_true',
            help='List existing weekly backups and exit.',
        )
        parser.add_argument(
            '--prune-only',
            action='store_true',
            help='Only remove backups older than retention; do not create a new one.',
        )

    def handle(self, *args, **options):
        if options['list']:
            self._print_list()
            return

        engine = get_database_engine()
        week = get_week_label()
        folder = (
            get_mysql_backup_folder()
            if 'mysql' in engine
            else get_sqlite_backup_folder()
        )

        self.stdout.write(f'Week: {week}')
        self.stdout.write(f'Active database: {describe_active_database()}')
        self.stdout.write(f'Backup folder: {folder}')
        if 'mysql' in engine:
            dump = resolve_mysqldump_executable()
            if dump:
                self.stdout.write(f'mysqldump: {dump}')
            else:
                self.stdout.write(self.style.WARNING('mysqldump: not found'))

        if options['prune_only']:
            removed = prune_old_weekly_backups()
            self.stdout.write(self.style.SUCCESS(f'Pruned {removed} old backup(s).'))
            return

        path, message = create_weekly_database_backup(force=options['force'])
        if path:
            self.stdout.write(self.style.SUCCESS(message))
            self.stdout.write(self.style.SUCCESS(f'Path: {path}'))
        else:
            self.stdout.write(self.style.ERROR(message))

    def _print_list(self):
        backups = list_weekly_backups()
        if not backups:
            self.stdout.write('No weekly database backups found.')
            return
        self.stdout.write(f'{"File":<36} {"Size":>12}  Modified')
        self.stdout.write('-' * 66)
        for row in backups:
            size_kb = row['size_bytes'] / 1024
            modified = row['modified'].strftime('%Y-%m-%d %H:%M')
            self.stdout.write(
                f'{row["filename"]:<36} {size_kb:>10.1f} KB  {modified}'
            )
