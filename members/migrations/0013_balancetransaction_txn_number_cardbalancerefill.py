import secrets

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def backfill_balance_transaction_numbers(apps, schema_editor):
    BalanceTransaction = apps.get_model("members", "BalanceTransaction")
    for bt in BalanceTransaction.objects.all().iterator():
        if bt.transaction_number:
            continue
        for _ in range(16):
            candidate = secrets.token_hex(12).upper()
            if not BalanceTransaction.objects.filter(transaction_number=candidate).exists():
                bt.transaction_number = candidate
                bt.save(update_fields=["transaction_number"])
                break


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("members", "0012_role_model_member_member_role"),
    ]

    operations = [
        migrations.AddField(
            model_name="balancetransaction",
            name="transaction_number",
            field=models.CharField(
                db_index=True,
                editable=False,
                help_text="Unique reference for this ledger row (audit / support).",
                max_length=32,
                null=True,
                unique=False,
            ),
        ),
        migrations.RunPython(backfill_balance_transaction_numbers, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="balancetransaction",
            name="transaction_number",
            field=models.CharField(
                db_index=True,
                editable=False,
                help_text="Unique reference for this ledger row (audit / support).",
                max_length=32,
                unique=True,
            ),
        ),
        migrations.CreateModel(
            name="CardBalanceRefill",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", models.DecimalField(decimal_places=2, max_digits=10)),
                ("balance_before", models.DecimalField(decimal_places=2, editable=False, max_digits=10)),
                ("balance_after", models.DecimalField(decimal_places=2, editable=False, max_digits=10)),
                ("notes", models.TextField(blank=True, help_text="Optional note shown on the ledger entry.")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "balance_transaction",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="card_refill",
                        to="members.balancetransaction",
                    ),
                ),
                (
                    "member",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="card_balance_refills",
                        to="members.member",
                    ),
                ),
                (
                    "performed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="card_balance_refills",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Refill card balance",
                "verbose_name_plural": "Refill card balance",
                "ordering": ["-created_at"],
            },
        ),
    ]
