from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("savings", "0009_savingsproduct_interest_rate_help"),
    ]

    operations = [
        migrations.AddField(
            model_name="savingsproduct",
            name="rate_3_months",
            field=models.DecimalField(
                decimal_places=3,
                default=Decimal("0.010"),
                help_text="Time deposit of ₱100,001 and above, when the member selects 3 months.",
                max_digits=6,
            ),
        ),
        migrations.AddField(
            model_name="savingsproduct",
            name="rate_6_months",
            field=models.DecimalField(
                decimal_places=3,
                default=Decimal("0.020"),
                help_text="Time deposit of ₱100,001 and above, when the member selects 6 months.",
                max_digits=6,
            ),
        ),
        migrations.AddField(
            model_name="savingsproduct",
            name="rate_1_year",
            field=models.DecimalField(
                decimal_places=3,
                default=Decimal("0.030"),
                help_text="Time deposit of ₱100,001 and above, when the member selects 1 year.",
                max_digits=6,
            ),
        ),
        migrations.AddField(
            model_name="membersavingsaccount",
            name="deposit_term_months",
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text="Member's term when the time deposit is ₱100,001 or above: 3, 6, or 12.",
                null=True,
            ),
        ),
    ]
