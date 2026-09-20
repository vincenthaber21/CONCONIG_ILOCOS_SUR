import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("members", "0020_segment_discount_group_fk"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("transactions", "0019_add_credit_payment_method"),
    ]

    operations = [
        migrations.CreateModel(
            name="CreditPayment",
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
                (
                    "settlement_number",
                    models.CharField(db_index=True, editable=False, max_length=32, unique=True),
                ),
                ("amount_paid", models.DecimalField(decimal_places=2, max_digits=12)),
                (
                    "payment_method",
                    models.CharField(
                        choices=[
                            ("cash", "Cash"),
                            ("debit", "Debit (Member Balance)"),
                        ],
                        max_length=20,
                    ),
                ),
                (
                    "balance_before",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        help_text="Member balance before payment when paid via debit.",
                        max_digits=10,
                        null=True,
                    ),
                ),
                (
                    "balance_after",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        help_text="Member balance after payment when paid via debit.",
                        max_digits=10,
                        null=True,
                    ),
                ),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "member",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="credit_payments",
                        to="members.member",
                    ),
                ),
                (
                    "performed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="credit_payments_performed",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Credit payment",
                "verbose_name_plural": "Credit payments",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddField(
            model_name="transaction",
            name="credit_settled_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When this credit (utang) sale was paid off at the dashboard.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="transaction",
            name="credit_payment",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="settled_sales",
                to="transactions.creditpayment",
            ),
        ),
    ]
