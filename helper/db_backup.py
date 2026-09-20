"""
Weekly database backup utilities.

Backs up the active Django database from settings.DATABASES:
- MySQL/MariaDB -> backups/mysql_weekly/kiosk_database_2026-W20.sql
- SQLite       -> backups/sqlite_weekly/db_2026-W20.sqlite3
"""
from __future__ import annotations

import logging
import re
import shutil
import sqlite3
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Tuple

from django.conf import settings

logger = logging.getLogger(__name__)

SQLITE_WEEKLY_PATTERN = re.compile(r'^db_\d{4}-W\d{2}\.sqlite3$')
MYSQL_WEEKLY_PATTERN = re.compile(r'^.+_\d{4}-W\d{2}\.sql$')


def get_week_label(when: Optional[date] = None) -> str:
    """Return ISO year-week label, e.g. 2026-W20."""
    d = when or date.today()
    iso = d.isocalendar()
    return f'{iso[0]}-W{iso[1]:02d}'


def get_default_database_config() -> dict:
    return settings.DATABASES.get('default', {})


def get_database_engine() -> str:
    return get_default_database_config().get('ENGINE', '')


def is_weekly_backup_enabled() -> bool:
    if hasattr(settings, 'WEEKLY_DB_BACKUP_ENABLED'):
        return bool(settings.WEEKLY_DB_BACKUP_ENABLED)
    return bool(getattr(settings, 'SQLITE_WEEKLY_BACKUP_ENABLED', True))


def get_retention_weeks() -> int:
    return int(
        getattr(
            settings,
            'WEEKLY_DB_BACKUP_RETENTION_WEEKS',
            getattr(settings, 'SQLITE_WEEKLY_BACKUP_RETENTION_WEEKS', 52),
        )
    )


def _resolve_folder(setting_name: str, default_relative: str) -> Path:
    folder = getattr(settings, setting_name, Path(settings.BASE_DIR) / default_relative)
    if not isinstance(folder, Path):
        folder = Path(folder)
    if not folder.is_absolute():
        folder = Path(settings.BASE_DIR) / folder
    return folder


def get_sqlite_backup_folder() -> Path:
    return _resolve_folder('SQLITE_WEEKLY_BACKUP_FOLDER', 'backups/sqlite_weekly')


def get_mysql_backup_folder() -> Path:
    return _resolve_folder('MYSQL_WEEKLY_BACKUP_FOLDER', 'backups/mysql_weekly')


def resolve_mysqldump_executable() -> Optional[str]:
    custom = getattr(settings, 'MYSQLDUMP_PATH', None) or ''
    if custom:
        path = Path(custom)
        if path.is_file():
            return str(path)
    found = shutil.which('mysqldump')
    return found


# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------

def resolve_sqlite_source_path() -> Optional[Path]:
    custom = getattr(settings, 'SQLITE_WEEKLY_BACKUP_SOURCE', None)
    if custom:
        path = Path(custom)
        if not path.is_absolute():
            path = Path(settings.BASE_DIR) / path
        return path if path.is_file() else None

    db = get_default_database_config()
    engine = db.get('ENGINE', '')
    if 'sqlite3' in engine:
        name = db.get('NAME')
        if name:
            path = Path(name)
            if not path.is_absolute():
                path = Path(settings.BASE_DIR) / path
            return path if path.is_file() else None

    fallback = Path(settings.BASE_DIR) / 'db.sqlite3'
    if fallback.is_file():
        return fallback
    return None


def sqlite_weekly_backup_filename(when: Optional[date] = None) -> str:
    return f'db_{get_week_label(when)}.sqlite3'


def sqlite_weekly_backup_path(when: Optional[date] = None) -> Path:
    return get_sqlite_backup_folder() / sqlite_weekly_backup_filename(when)


def _copy_sqlite_safe(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = destination.with_suffix('.sqlite3.tmp')
    if tmp_path.exists():
        tmp_path.unlink()

    src_conn = sqlite3.connect(f'file:{source}?mode=ro', uri=True, timeout=30)
    dst_conn = sqlite3.connect(str(tmp_path), timeout=30)
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()

    tmp_path.replace(destination)


def create_weekly_sqlite_backup(
    when: Optional[date] = None,
    *,
    force: bool = False,
) -> Tuple[Optional[Path], str]:
    if not is_weekly_backup_enabled():
        return None, 'Weekly database backup is disabled.'

    source = resolve_sqlite_source_path()
    if source is None:
        return None, (
            'No SQLite database file found. Use sqlite3 as DATABASE engine, '
            'place db.sqlite3 in the project root, or set SQLITE_WEEKLY_BACKUP_SOURCE.'
        )

    backup_dir = get_sqlite_backup_folder()
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = sqlite_weekly_backup_path(when)

    if dest.exists() and not force:
        return dest, f'Backup already exists for this week: {dest.name}'

    try:
        _copy_sqlite_safe(source, dest)
        removed = _prune_folder(get_sqlite_backup_folder(), SQLITE_WEEKLY_PATTERN)
        msg = f'Created weekly SQLite backup {dest.name} ({dest.stat().st_size:,} bytes)'
        if removed:
            msg += f'; removed {removed} old backup(s)'
        logger.info(msg)
        return dest, msg
    except Exception as exc:
        logger.exception('Weekly SQLite backup failed')
        return None, f'SQLite backup failed: {exc}'


# ---------------------------------------------------------------------------
# MySQL / MariaDB
# ---------------------------------------------------------------------------

def mysql_weekly_backup_filename(db_name: str, when: Optional[date] = None) -> str:
    safe_name = re.sub(r'[^\w\-]', '_', db_name)
    return f'{safe_name}_{get_week_label(when)}.sql'


def mysql_weekly_backup_path(db_name: str, when: Optional[date] = None) -> Path:
    return get_mysql_backup_folder() / mysql_weekly_backup_filename(db_name, when)


def create_weekly_mysql_backup(
    when: Optional[date] = None,
    *,
    force: bool = False,
) -> Tuple[Optional[Path], str]:
    if not is_weekly_backup_enabled():
        return None, 'Weekly database backup is disabled.'

    mysqldump = resolve_mysqldump_executable()
    if not mysqldump:
        return None, (
            'mysqldump not found. Install MySQL/MariaDB client tools or set '
            'MYSQLDUMP_PATH in settings (e.g. C:\\Program Files\\MariaDB 10.11\\bin\\mysqldump.exe).'
        )

    db = get_default_database_config()
    db_name = db.get('NAME')
    if not db_name:
        return None, 'DATABASE NAME is not configured.'

    host = db.get('HOST') or '127.0.0.1'
    port = str(db.get('PORT') or '3306')
    user = db.get('USER') or 'root'
    password = db.get('PASSWORD') or ''

    backup_dir = get_mysql_backup_folder()
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = mysql_weekly_backup_path(db_name, when)
    tmp_path = dest.with_suffix('.sql.tmp')

    if dest.exists() and not force:
        return dest, f'Backup already exists for this week: {dest.name}'

    cmd = [
        mysqldump,
        f'--host={host}',
        f'--port={port}',
        f'--user={user}',
        '--single-transaction',
        '--routines',
        '--triggers',
        '--default-character-set=utf8mb4',
        db_name,
    ]
    if password:
        cmd.insert(4, f'--password={password}')

    try:
        if tmp_path.exists():
            tmp_path.unlink()
        with tmp_path.open('w', encoding='utf-8', newline='\n') as outfile:
            result = subprocess.run(
                cmd,
                stdout=outfile,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
        if result.returncode != 0:
            if tmp_path.exists():
                tmp_path.unlink()
            err = (result.stderr or '').strip() or f'mysqldump exited with code {result.returncode}'
            return None, f'MySQL backup failed: {err}'

        tmp_path.replace(dest)
        removed = _prune_folder(get_mysql_backup_folder(), MYSQL_WEEKLY_PATTERN)
        msg = (
            f'Created weekly MySQL backup {dest.name} '
            f'from {db_name}@{host}:{port} ({dest.stat().st_size:,} bytes)'
        )
        if removed:
            msg += f'; removed {removed} old backup(s)'
        logger.info(msg)
        return dest, msg
    except Exception as exc:
        if tmp_path.exists():
            tmp_path.unlink()
        logger.exception('Weekly MySQL backup failed')
        return None, f'MySQL backup failed: {exc}'


# ---------------------------------------------------------------------------
# Unified entry (uses settings.DATABASES engine)
# ---------------------------------------------------------------------------

def _upload_to_google_drive_if_enabled(backup_path: Path) -> str:
    try:
        from helper.google_drive_upload import (
            is_google_drive_upload_enabled,
            upload_backup_to_drive,
        )
    except ImportError:
        return ''

    if not is_google_drive_upload_enabled():
        return ''

    ok, message = upload_backup_to_drive(backup_path)
    if ok:
        logger.info(message)
        return f'; {message}'
    logger.warning('Google Drive upload skipped/failed: %s', message)
    return f'; Google Drive: {message}'


def create_weekly_database_backup(
    when: Optional[date] = None,
    *,
    force: bool = False,
) -> Tuple[Optional[Path], str]:
    """Back up the database configured in Django settings."""
    engine = get_database_engine()
    if 'mysql' in engine:
        path, msg = create_weekly_mysql_backup(when=when, force=force)
    elif 'sqlite3' in engine:
        path, msg = create_weekly_sqlite_backup(when=when, force=force)
    elif 'postgresql' in engine:
        return None, 'PostgreSQL weekly backup is not configured yet.'
    else:
        return None, f'Unsupported database engine for weekly backup: {engine or "unknown"}'

    if path is not None:
        msg += _upload_to_google_drive_if_enabled(path)
    return path, msg


def describe_active_database() -> str:
    db = get_default_database_config()
    engine = db.get('ENGINE', 'unknown')
    name = db.get('NAME', '')
    host = db.get('HOST', '')
    port = db.get('PORT', '')
    if 'mysql' in engine:
        return f'MySQL {name} @ {host}:{port}'
    if 'sqlite3' in engine:
        path = resolve_sqlite_source_path()
        return f'SQLite {path or name}'
    return f'{engine} ({name})'


def _prune_folder(backup_dir: Path, pattern: re.Pattern[str]) -> int:
    if not backup_dir.is_dir():
        return 0
    retention = get_retention_weeks()
    files = sorted(
        (p for p in backup_dir.iterdir() if p.is_file() and pattern.match(p.name)),
        key=lambda p: p.name,
        reverse=True,
    )
    removed = 0
    for old in files[retention:]:
        try:
            old.unlink()
            removed += 1
            logger.info('Removed old weekly backup: %s', old.name)
        except OSError as exc:
            logger.warning('Could not remove %s: %s', old, exc)
    return removed


def prune_old_weekly_backups() -> int:
    """Prune old backups for the active database engine."""
    engine = get_database_engine()
    if 'mysql' in engine:
        return _prune_folder(get_mysql_backup_folder(), MYSQL_WEEKLY_PATTERN)
    if 'sqlite3' in engine:
        return _prune_folder(get_sqlite_backup_folder(), SQLITE_WEEKLY_PATTERN)
    return 0


def list_weekly_backups() -> list[dict]:
    """List weekly backups for the active database engine."""
    engine = get_database_engine()
    if 'mysql' in engine:
        backup_dir = get_mysql_backup_folder()
        pattern = MYSQL_WEEKLY_PATTERN
    elif 'sqlite3' in engine:
        backup_dir = get_sqlite_backup_folder()
        pattern = SQLITE_WEEKLY_PATTERN
    else:
        return []

    if not backup_dir.is_dir():
        return []

    rows = []
    for path in backup_dir.iterdir():
        if not path.is_file() or not pattern.match(path.name):
            continue
        stat = path.stat()
        rows.append({
            'filename': path.name,
            'path': str(path),
            'size_bytes': stat.st_size,
            'modified': datetime.fromtimestamp(stat.st_mtime),
        })
    rows.sort(key=lambda r: r['filename'], reverse=True)
    return rows
