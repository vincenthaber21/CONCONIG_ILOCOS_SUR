import datetime
from decimal import Decimal

from django.db import migrations, models


def backfill_sample_loan_usable_days(apps, schema_editor):
    """Set usable days so ₱50,000 @ 0.015 → ₱51,400 (56 days)."""
    LoanApplication = apps.get_model("loans", "LoanApplication")
    app = LoanApplication.objects.filter(
        pk="e0928a86-d837-4a63-880a-4fb31ecf54b1"
    ).first()
    if app is None:
        return
    app.usable_from = datetime.date(2026, 8, 1)
    app.usable_to = datetime.date(2026, 9, 26)  # 56 days
    app.usable_days = 56
    if app.interest_rate is None:
        app.interest_rate = Decimal("0.015")
    app.save(
        update_fields=["usable_from", "usable_to", "usable_days", "interest_rate"]
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("loans", "0017_loansettings_committee_single_approver"),
    ]

    operations = [
        migrations.AddField(
            model_name="loanapplication",
            name="usable_from",
            field=models.DateField(
                blank=True,
                help_text="Start date used to compute usable days for interest.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="loanapplication",
            name="usable_to",
            field=models.DateField(
                blank=True,
                help_text="End date used to compute usable days for interest.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="loanapplication",
            name="usable_days",
            field=models.PositiveIntegerField(
                blank=True,
                help_text=(
                    "Days the loan principal earns interest (To − From). "
                    "Interest = (rate ÷ 30) × principal × usable_days."
                ),
                null=True,
            ),
        ),
        migrations.RunPython(backfill_sample_loan_usable_days, noop_reverse),
    ]
