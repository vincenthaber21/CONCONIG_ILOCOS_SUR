# Generated manually for partial refund line tracking

import re
from decimal import Decimal

from django.db import migrations, models
from django.utils import timezone


def _recalc_txn_totals(transaction):
    active = transaction.items.filter(refunded_at__isnull=True)
    subtotal = sum((i.total_price for i in active), Decimal("0.00"))
    vat_amount = sum((i.vat_amount for i in active), Decimal("0.00"))
    vatable_sale = sum((i.vatable_sale for i in active), Decimal("0.00"))
    transaction.subtotal = subtotal.quantize(Decimal("0.01"))
    transaction.vat_amount = vat_amount.quantize(Decimal("0.01"))
    transaction.vatable_sale = vatable_sale.quantize(Decimal("0.01"))
    transaction.total_amount = (vat_amount + vatable_sale).quantize(Decimal("0.01"))
    transaction.save(
        update_fields=["subtotal", "vat_amount", "vatable_sale", "total_amount", "updated_at"]
    )


def backfill_partial_refunds(apps, schema_editor):
    Transaction = apps.get_model("transactions", "Transaction")
    TransactionItem = apps.get_model("transactions", "TransactionItem")
    RefundReason = apps.get_model("transactions", "RefundReason")
    now = timezone.now()

    for txn in Transaction.objects.filter(status="refunded").iterator():
        notes = txn.notes or ""
        if not notes.startswith("Partially refunded"):
            continue

        refunded_ids = set()
        id_match = re.search(r"\[refund_items:([\d,]+)\]", notes)
        if id_match:
            refunded_ids = {
                int(x) for x in id_match.group(1).split(",") if x.strip().isdigit()
            }

        if not refunded_ids:
            try:
                rr = RefundReason.objects.get(transaction_id=txn.pk)
                refunded_ids = set(rr.refund_items.values_list("id", flat=True))
            except RefundReason.DoesNotExist:
                pass

        if not refunded_ids:
            txn.status = "partially_refunded"
            txn.save(update_fields=["status", "updated_at"])
            continue

        for item in TransactionItem.objects.filter(transaction_id=txn.pk, id__in=refunded_ids):
            if not item.refunded_at:
                item.refunded_at = now
                item.save(update_fields=["refunded_at"])

        remaining = TransactionItem.objects.filter(
            transaction_id=txn.pk, refunded_at__isnull=True
        ).count()
        if remaining:
            txn.status = "partially_refunded"
        else:
            txn.status = "refunded"
        txn.save(update_fields=["status", "updated_at"])
        _recalc_txn_totals(txn)


class Migration(migrations.Migration):

    dependencies = [
        ("transactions", "0023_credit_partial_payment"),
    ]

    operations = [
        migrations.AddField(
            model_name="transactionitem",
            name="refunded_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text="When this line was refunded (partial or full refund).",
            ),
        ),
        migrations.AlterField(
            model_name="transaction",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("completed", "Completed"),
                    ("cancelled", "Cancelled"),
                    ("refund_requested", "Refund Requested"),
                    ("return_window", "Return Window (Awaiting Item)"),
                    ("partially_refunded", "Partially Refunded"),
                    ("refunded", "Refunded"),
                    ("return_expired", "Return Expired (No Refund)"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
        migrations.RunPython(backfill_partial_refunds, migrations.RunPython.noop),
    ]
