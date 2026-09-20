"""Credit annual savings interest on accounts that have completed a year.

Usage:
    python manage.py accrue_savings_interest
"""

from django.core.management.base import BaseCommand

from savings.services import accrue_due_savings_interest


class Command(BaseCommand):
    help = (
        "Credit annual interest on active savings accounts. "
        "Uses a flat 5% annual rate credited monthly: (balance × 5%) ÷ 12."
    )

    def handle(self, *args, **options):
        credited, skipped = accrue_due_savings_interest()
        self.stdout.write(
            self.style.SUCCESS(
                f"Savings interest: {credited} credit(s) posted, {skipped} skipped."
            )
        )
