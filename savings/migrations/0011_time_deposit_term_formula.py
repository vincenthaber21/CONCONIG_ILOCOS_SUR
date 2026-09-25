from decimal import Decimal

from django.db import migrations, models


def set_six_month_rate(apps, schema_editor):
    Product = apps.get_model("savings", "SavingsProduct")
    Product.objects.filter(rate_6_months=Decimal("0.020")).update(
        rate_6_months=Decimal("0.010")
    )


class Migration(migrations.Migration):

    dependencies = [
        ("savings", "0010_time_deposit_high_balance_terms"),
    ]

    operations = [
        migrations.AlterField(
            model_name="savingsproduct",
            name="rate_3_months",
            field=models.DecimalField(
                decimal_places=3,
                default=Decimal("0.010"),
                help_text="Time deposit of ₱100,001 and above, 3 months: savings × this rate × (3/12).",
                max_digits=6,
            ),
        ),
        migrations.AlterField(
            model_name="savingsproduct",
            name="rate_6_months",
            field=models.DecimalField(
                decimal_places=3,
                default=Decimal("0.010"),
                help_text="Time deposit of ₱100,001 and above, 6 months: savings × this rate × (6/12).",
                max_digits=6,
            ),
        ),
        migrations.AlterField(
            model_name="savingsproduct",
            name="rate_1_year",
            field=models.DecimalField(
                decimal_places=3,
                default=Decimal("0.030"),
                help_text="Time deposit of ₱100,001 and above, 1 year: savings × this rate.",
                max_digits=6,
            ),
        ),
        migrations.RunPython(set_six_month_rate, migrations.RunPython.noop),
    ]
