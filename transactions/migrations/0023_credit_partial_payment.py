from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("transactions", "0022_walkin_product_discount"),
    ]

    operations = [
        migrations.AddField(
            model_name="transactionitem",
            name="credit_amount_paid",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                help_text="Peso amount already paid toward this line on open credit sales.",
                max_digits=10,
            ),
        ),
        migrations.CreateModel(
            name="CreditPaymentLine",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("amount_applied", models.DecimalField(decimal_places=2, max_digits=10)),
                (
                    "item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="credit_payment_lines",
                        to="transactions.transactionitem",
                    ),
                ),
                (
                    "payment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="payment_lines",
                        to="transactions.creditpayment",
                    ),
                ),
            ],
            options={
                "verbose_name": "Credit payment line",
                "verbose_name_plural": "Credit payment lines",
                "ordering": [
                    "item__transaction__created_at",
                    "item__transaction_id",
                    "item_id",
                ],
            },
        ),
    ]
