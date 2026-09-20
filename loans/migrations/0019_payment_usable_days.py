from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("loans", "0018_loanapplication_usable_days"),
    ]

    operations = [
        migrations.AddField(
            model_name="payment",
            name="usable_from",
            field=models.DateField(
                blank=True,
                help_text="Start of the interest period covered by this payment.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="payment",
            name="usable_to",
            field=models.DateField(
                blank=True,
                help_text="End of the interest period covered by this payment.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="payment",
            name="usable_days",
            field=models.PositiveIntegerField(
                blank=True,
                help_text="To − From. Used to compute period interest on the balance.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="payment",
            name="period_interest",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                help_text=(
                    "Interest for this usable-days period: "
                    "(rate ÷ 30) × outstanding balance × usable_days (rounded)."
                ),
                max_digits=12,
            ),
        ),
    ]
