"""Management command: scan active loans for overdue installments.

Usage:
    python manage.py check_delinquencies
"""

from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone

from loans.models import AmortizationSchedule, DelinquencyRecord, LoanApplication


class Command(BaseCommand):
    help = "Scan ACTIVE loans for unpaid, past-due installments and flag delinquencies."

    def handle(self, *args, **options):
        today = timezone.localdate()
        flagged_count = 0

        active_applications = LoanApplication.objects.filter(
            status=LoanApplication.Status.ACTIVE
        )

        for application in active_applications:
            overdue_installments = AmortizationSchedule.objects.filter(
                application=application, is_paid=False, due_date__lt=today
            ).order_by("due_date")

            if not overdue_installments.exists():
                continue

            earliest_due = overdue_installments.first().due_date
            days_overdue = (today - earliest_due).days
            amount_overdue = sum(
                (installment.total_due for installment in overdue_installments),
                start=0,
            )

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

            member_email = getattr(application.member, "email", "") or ""
            if member_email:
                send_mail(
                    subject=f"Loan payment overdue - {days_overdue} day(s)",
                    message=(
                        f"Dear {application.member},\n\n"
                        f"Your loan #{application.id} has an overdue balance of "
                        f"{amount_overdue} ({days_overdue} days overdue). "
                        "Please settle at your earliest convenience.\n\n"
                        "Thank you."
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[member_email],
                    fail_silently=True,
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
