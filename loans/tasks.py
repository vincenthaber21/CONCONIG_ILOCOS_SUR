"""Celery task stubs for asynchronous/background loan servicing work."""

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
    return str(notification.id) if notification else None


@shared_task
def check_delinquencies_task():
    """Celery entrypoint that mirrors the check_delinquencies management command.

    Scans ACTIVE loans for unpaid, past-due amortization installments, applies
    late interest, and creates/updates DelinquencyRecord rows.
    """
    from .models import AmortizationSchedule, DelinquencyRecord, LoanApplication
    from .services import overdue_cutoff_date, refresh_schedule_interest

    today = timezone.localdate()
    flagged = []

    active_applications = LoanApplication.objects.filter(
        status=LoanApplication.Status.ACTIVE
    ).select_related("loan_product")

    for application in active_applications:
        refresh_schedule_interest(application, as_of_date=today)

        overdue_installments = AmortizationSchedule.objects.filter(
            application=application,
            is_paid=False,
            due_date__lt=overdue_cutoff_date(today),
        )
        if not overdue_installments.exists():
            continue

        days_overdue = (today - overdue_installments.order_by("due_date").first().due_date).days
        amount_overdue = sum((i.total_due for i in overdue_installments), start=0)

        existing = DelinquencyRecord.objects.filter(
            application=application, resolved=False
        ).first()
        previous_days = existing.days_overdue if existing else None

        record, created = DelinquencyRecord.objects.update_or_create(
            application=application,
            resolved=False,
            defaults={
                "days_overdue": days_overdue,
                "amount_overdue": amount_overdue,
                "flagged_at": timezone.now(),
            },
        )
        if created or previous_days != days_overdue:
            from .notifications import notify_loan_member

            notify_loan_member(
                application,
                "overdue",
                extra={
                    "days_overdue": days_overdue,
                    "amount_overdue": amount_overdue,
                },
            )
        flagged.append(str(record.id))

    return flagged
