from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("savings", "0011_time_deposit_term_formula"),
    ]

    operations = [
        migrations.AddField(
            model_name="savingsproduct",
            name="min_amount",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("5000.00"),
                help_text=(
                    "Time deposit feature: from this amount through the maximum, "
                    "interest = time deposit × interest rate."
                ),
                max_digits=12,
            ),
        ),
        migrations.AddField(
            model_name="savingsproduct",
            name="max_amount",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("100000.00"),
                help_text=(
                    "Time deposit feature: above this amount, the member selects "
                    "3 months, 6 months, or 1 year."
                ),
                max_digits=14,
            ),
        ),
    ]
