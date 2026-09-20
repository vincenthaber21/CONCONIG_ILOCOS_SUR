"""Management command: scan active loans for overdue installments.

Usage:
    python manage.py check_delinquencies
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from loans.models import AmortizationSchedule, DelinquencyRecord, LoanApplication
from loans.notifications import notify_loan_member
from loans.services import overdue_cutoff_date, refresh_schedule_interest


class Command(BaseCommand):
    help = (
        "Scan ACTIVE loans for unpaid, past-due installments, apply late interest, "
        "and flag delinquencies."
    )

    def handle(self, *args, **options):
        today = timezone.localdate()
        flagged_count = 0

        active_applications = LoanApplication.objects.filter(
            status=LoanApplication.Status.ACTIVE
        ).select_related("loan_product")

        for application in active_applications:
            refresh_schedule_interest(application, as_of_date=today)

            overdue_installments = AmortizationSchedule.objects.filter(
                application=application,
                is_paid=False,
                due_date__lt=overdue_cutoff_date(today),
            ).order_by("due_date")

            if not overdue_installments.exists():
                continue

            earliest_due = overdue_installments.first().due_date
            days_overdue = (today - earliest_due).days
            amount_overdue = sum(
                (installment.total_due for installment in overdue_installments),
                start=0,
            )

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
            flagged_count += 1

            if created or previous_days != days_overdue:
                notify_loan_member(
                    application,
                    "overdue",
                    extra={
                        "days_overdue": days_overdue,
                        "amount_overdue": amount_overdue,
                    },
                )

            verb = "Flagged" if created else "Updated"
            self.stdout.write(
                self.style.WARNING(
                    f"{verb} delinquency for application {application.id}: "
                    f"{days_overdue} days overdue, {amount_overdue} due."
                )
            )

        self.stdout.write(
            self.style.SUCCESS(f"Delinquency scan complete. {flagged_count} loan(s) flagged.")
        )
