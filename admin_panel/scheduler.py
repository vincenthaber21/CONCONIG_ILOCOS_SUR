"""
Scheduler module for running periodic tasks.
This module sets up APScheduler to run scheduled tasks when Django starts.
"""
import functools
import logging
import sys
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from django.core.management import call_command
from django.conf import settings
from django.db import close_old_connections
from django.db.utils import InterfaceError, OperationalError
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler = None


def _with_db_connection(func):
    """
    Ensure each APScheduler job uses a fresh DB connection.

    Background threads keep connections that MySQL/Windows may close after
    idle timeout ("MySQL server has gone away" / WinError 10053). Django's
    request middleware does not run in these threads, so we close stale
    connections before/after every job and retry once on connection errors.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        close_old_connections()
        try:
            return func(*args, **kwargs)
        except (OperationalError, InterfaceError) as e:
            logger.warning(
                "Stale DB connection in %s (%s); retrying once...",
                func.__name__,
                e,
            )
            # Force-drop the dead socket so the next query opens a new one
            from django.db import connections
            for conn in connections.all():
                conn.close()
            try:
                return func(*args, **kwargs)
            except Exception as retry_err:
                logger.error(
                    "Error in scheduled job %s after retry: %s",
                    func.__name__,
                    retry_err,
                    exc_info=True,
                )
                raise
        finally:
            close_old_connections()

    return wrapper


@_with_db_connection
def send_daily_report():
    """Function to call the send_daily_report management command"""
    try:
        logger.info("Starting scheduled daily report generation...")
        # Use call_command to execute the management command for today
        # The command defaults to today's date if no date is specified
        # Use force=True to ensure scheduled runs always send, even if one was already sent
        today = timezone.now().date()
        call_command('send_daily_report', date=today.strftime('%Y-%m-%d'), force=True, verbosity=1)
        logger.info(f"Daily report sent successfully for {today}")
    except (OperationalError, InterfaceError):
        raise  # Let _with_db_connection retry with a fresh connection
    except Exception as e:
        logger.error(f"Error sending daily report: {str(e)}", exc_info=True)
        # Print to stderr for visibility
        print(f"Error sending daily report: {str(e)}", file=sys.stderr)


@_with_db_connection
def check_and_send_missed_report():
    """Check if yesterday's report was missed and send it if needed"""
    try:
        from transactions.models import Transaction
        yesterday = (timezone.now() - timedelta(days=1)).date()
        
        # Check if there were any reportable sales yesterday
        from admin_panel.report_utils import get_report_transactions
        has_transactions = get_report_transactions(yesterday).exists()
        
        if has_transactions:
            logger.info(f"Checking if report for {yesterday} was missed...")
            logger.info(f"Report check completed for {yesterday}")
    except (OperationalError, InterfaceError):
        raise
    except Exception as e:
        logger.error(f"Error checking missed report: {str(e)}", exc_info=True)


@_with_db_connection
def backup_database_weekly():
    """Create weekly backup of the active database (MySQL .sql or SQLite .sqlite3)."""
    try:
        logger.info('Starting scheduled weekly database backup...')
        call_command('backup_database_weekly', verbosity=1)
    except (OperationalError, InterfaceError):
        raise
    except Exception as e:
        logger.error(f'Error during weekly database backup: {str(e)}', exc_info=True)
        print(f'Error during weekly database backup: {str(e)}', file=sys.stderr)


@_with_db_connection
def expire_overdue_return_windows():
    """Automatically expire return windows whose deadline has passed without item return."""
    try:
        from transactions.models import Transaction, RefundReturnWindow
        now = timezone.now()
        overdue = RefundReturnWindow.objects.filter(
            is_returned=False,
            return_deadline__lt=now,
            transaction__status='return_window',
        ).select_related('transaction')
        count = 0
        for rw in overdue:
            txn = rw.transaction
            txn.status = 'return_expired'
            txn.notes = (
                (txn.notes + ' | ' if txn.notes else '') +
                f'Return window automatically expired on {now.strftime("%b %d, %Y")} — no refund processed.'
            )
            txn.save()
            count += 1
        if count:
            logger.info(f"Auto-expired {count} overdue return window(s).")
    except (OperationalError, InterfaceError):
        raise  # Let _with_db_connection retry with a fresh connection
    except Exception as e:
        logger.error(f"Error expiring return windows: {str(e)}", exc_info=True)


@_with_db_connection
def accrue_credit_interest():
    """Apply monthly interest on overdue credit (utang) after the grace period."""
    try:
        from helper.credit_interest_helper import ensure_credit_interest_up_to_date
        newly = ensure_credit_interest_up_to_date()
        if newly and newly > 0:
            logger.info("Accrued ₱%s credit interest on overdue utang.", newly)
    except (OperationalError, InterfaceError):
        raise
    except Exception as e:
        logger.error(f"Error accruing credit interest: {str(e)}", exc_info=True)


@_with_db_connection
def accrue_savings_interest():
    """Credit monthly Regular Savings interest ((balance × 5%) ÷ 12)."""
    try:
        from savings.services import accrue_due_savings_interest
        credited, skipped = accrue_due_savings_interest()
        if credited:
            logger.info(
                "Credited %s savings interest transaction(s) (%s skipped).",
                credited,
                skipped,
            )
    except (OperationalError, InterfaceError):
        raise
    except Exception as e:
        logger.error(f"Error accruing savings interest: {str(e)}", exc_info=True)


def start_scheduler():
    """Start the scheduler and add the daily report job"""
    global scheduler
    
    # Check if scheduler is already running
    if scheduler is not None:
        if scheduler.running:
            logger.warning("Scheduler is already running")
            return
        else:
            # Clean up old scheduler instance
            try:
                scheduler.shutdown(wait=False)
            except:
                pass
            scheduler = None
    
    try:
        # Create scheduler instance with timezone support
        scheduler = BackgroundScheduler(timezone=settings.TIME_ZONE)
        
        # Load schedule config from the database (with safe fallback)
        try:
            from admin_panel.models import ReportScheduleConfig
            config = ReportScheduleConfig.get()
            sched_hour = config.send_time.hour
            sched_minute = config.send_time.minute
            is_enabled = config.is_enabled
        except Exception:
            # DB not ready yet (e.g. first migrate run) — use safe defaults
            sched_hour = 0
            sched_minute = 0
            is_enabled = True

        if is_enabled:
            # Schedule daily report using DB-configured time
            scheduler.add_job(
                send_daily_report,
                trigger=CronTrigger(hour=sched_hour, minute=sched_minute),
                id='send_daily_report',
                name=f'Send Daily Report at {sched_hour:02d}:{sched_minute:02d}',
                replace_existing=True,
                max_instances=1,
                misfire_grace_time=3600,
                coalesce=True,
            )
            logger.info(
                f"Scheduler started. Daily report will run at {sched_hour:02d}:{sched_minute:02d} every day."
            )
            print(
                f"Scheduler started: Daily report will run automatically at "
                f"{sched_hour:02d}:{sched_minute:02d} every day."
            )
        else:
            logger.info("Scheduler started, but daily report job is DISABLED via admin config.")
            print("Scheduler started: Daily report job is currently DISABLED.")

        # Schedule auto-expiry of overdue refund return windows (runs every hour)
        scheduler.add_job(
            expire_overdue_return_windows,
            trigger=CronTrigger(minute=0),  # Every hour at :00
            id='expire_overdue_return_windows',
            name='Auto-expire overdue refund return windows',
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=3600,
            coalesce=True,
        )
        logger.info("Scheduled: Auto-expire overdue return windows every hour.")

        # Accrue monthly credit (utang) interest daily at 00:15
        scheduler.add_job(
            accrue_credit_interest,
            trigger=CronTrigger(hour=0, minute=15),
            id='accrue_credit_interest',
            name='Accrue credit (utang) interest',
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=3600,
            coalesce=True,
        )
        logger.info("Scheduled: Accrue credit interest daily at 00:15.")

        # Accrue monthly Regular Savings interest every hour (opening-anniversary dates).
        scheduler.add_job(
            accrue_savings_interest,
            trigger=CronTrigger(minute=20),
            id='accrue_savings_interest',
            name='Accrue regular savings interest',
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=3600,
            coalesce=True,
        )
        logger.info("Scheduled: Accrue savings interest hourly at :20.")

        # Weekly database backup (Sunday 02:00 by default)
        weekly_enabled = getattr(
            settings,
            'WEEKLY_DB_BACKUP_ENABLED',
            getattr(settings, 'SQLITE_WEEKLY_BACKUP_ENABLED', True),
        )
        if weekly_enabled:
            backup_dow = getattr(
                settings,
                'WEEKLY_DB_BACKUP_DAY_OF_WEEK',
                getattr(settings, 'SQLITE_WEEKLY_BACKUP_DAY_OF_WEEK', 'sun'),
            )
            backup_hour = int(getattr(
                settings,
                'WEEKLY_DB_BACKUP_HOUR',
                getattr(settings, 'SQLITE_WEEKLY_BACKUP_HOUR', 2),
            ))
            backup_minute = int(getattr(
                settings,
                'WEEKLY_DB_BACKUP_MINUTE',
                getattr(settings, 'SQLITE_WEEKLY_BACKUP_MINUTE', 0),
            ))
            scheduler.add_job(
                backup_database_weekly,
                trigger=CronTrigger(
                    day_of_week=backup_dow,
                    hour=backup_hour,
                    minute=backup_minute,
                ),
                id='backup_database_weekly',
                name=(
                    f'Weekly database backup ({backup_dow} '
                    f'{backup_hour:02d}:{backup_minute:02d})'
                ),
                replace_existing=True,
                max_instances=1,
                misfire_grace_time=86400,
                coalesce=True,
            )
            logger.info(
                'Scheduled: Weekly database backup every %s at %02d:%02d.',
                backup_dow,
                backup_hour,
                backup_minute,
            )
            print(
                f'Scheduler: Weekly database backup every {backup_dow} '
                f'at {backup_hour:02d}:{backup_minute:02d}.'
            )
        
        # Start the scheduler
        scheduler.start()
        logger.info("Misfire grace time: 1 hour (reports will auto-send if missed after downtime)")
        print("Note: Reports will automatically send even if the server was down briefly.")

    except Exception as e:
        logger.error(f"Error starting scheduler: {str(e)}", exc_info=True)
        print(f"Error starting scheduler: {str(e)}", file=sys.stderr)


def stop_scheduler():
    """Stop the scheduler"""
    global scheduler
    
    if scheduler is not None and scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler stopped")
    else:
        logger.warning("Scheduler is not running")

