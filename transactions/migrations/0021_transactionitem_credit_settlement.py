import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("transactions", "0020_credit_payment_settlement"),
    ]

    operations = [
        migrations.AddField(
            model_name="transactionitem",
            name="credit_settled_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When this line on a credit sale was paid off (partial utang settlement).",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="transactionitem",
            name="credit_payment",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="settled_items",
                to="transactions.creditpayment",
            ),
        ),
    ]
