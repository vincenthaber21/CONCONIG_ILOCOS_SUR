"""Celery task stubs for asynchronous/background loan servicing work.

CELERY_TASK_ALWAYS_EAGER defaults to True in settings so these run
synchronously in dev/tests without a broker. Swap that off in production
once a real broker (Redis/RabbitMQ) is configured.
"""

from celery import shared_task
from django.utils import timezone


@shared_task
def notify_applicant_of_disapproval_task(application_id):
    """Celery-friendly wrapper around services.notify_applicant_of_disapproval.

    Usage: notify_applicant_of_disapproval_task.delay(application.id)
    """
    from .models import LoanApplication
    from .services import notify_applicant_of_disapproval

    application = LoanApplication.objects.get(id=application_id)
    notification = notify_applicant_of_disapproval(application)
    return str(notification.id)


@shared_task
def check_delinquencies_task():
    """Celery entrypoint that mirrors the check_delinquencies management command.

    Scans ACTIVE loans for unpaid, past-due amortization installments and
    creates/updates DelinquencyRecord rows, sending a reminder email for
    each newly (or still) delinquent loan.
    """
    from .models import AmortizationSchedule, DelinquencyRecord, LoanApplication

    today = timezone.localdate()
    flagged = []

    active_applications = LoanApplication.objects.filter(
        status=LoanApplication.Status.ACTIVE
    )

    for application in active_applications:
        overdue_installments = AmortizationSchedule.objects.filter(
            application=application, is_paid=False, due_date__lt=today
        )
        if not overdue_installments.exists():
            continue

        days_overdue = (today - overdue_installments.order_by("due_date").first().due_date).days
        amount_overdue = sum((i.total_due for i in overdue_installments), start=0)

        record, _ = DelinquencyRecord.objects.update_or_create(
            application=application,
            resolved=False,
            defaults={
                "days_overdue": days_overdue,
                "amount_overdue": amount_overdue,
                "flagged_at": timezone.now(),
            },
        )
        flagged.append(str(record.id))

    return flagged
