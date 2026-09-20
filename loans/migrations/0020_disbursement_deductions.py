from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("loans", "0019_payment_usable_days"),
    ]

    operations = [
        migrations.AddField(
            model_name="disbursement",
            name="other_deduction_amount",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                help_text="Other fees withheld at disbursement (e.g. processing fee).",
                max_digits=12,
            ),
        ),
        migrations.AddField(
            model_name="disbursement",
            name="other_deduction_label",
            field=models.CharField(
                blank=True,
                help_text="Description of the other deduction, shown on the disbursement voucher.",
                max_length=120,
            ),
        ),
        migrations.AddField(
            model_name="disbursement",
            name="transaction_fee",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                help_text="Transaction or service fee withheld at disbursement.",
                max_digits=12,
            ),
        ),
        migrations.AlterField(
            model_name="disbursement",
            name="amount_released",
            field=models.DecimalField(
                decimal_places=2,
                help_text="Net cash/check/transfer given to the member after deductions.",
                max_digits=12,
            ),
        ),
    ]
