"""Settle outstanding member credit (utang) from the admin dashboard."""

from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Iterable, List, Tuple

from django.db import transaction as db_transaction
from django.db.models import DecimalField, Exists, F, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce, Greatest
from django.utils import timezone

from members.models import BalanceTransaction, Member
from transactions.models import CreditPayment, CreditPaymentLine, Transaction, TransactionItem

if TYPE_CHECKING:
    pass


def _credit_outstanding_expression():
    """DB expression: remaining utang principal per line (vat + vatable − already paid)."""
    return Greatest(
        F("vat_amount")
        + F("vatable_sale")
        - Coalesce(F("credit_amount_paid"), Value(Decimal("0"))),
        Value(Decimal("0")),
        output_field=DecimalField(max_digits=12, decimal_places=2),
    )


def _interest_outstanding_expression():
    """DB expression: unpaid interest on a credit sale Transaction."""
    return Greatest(
        Coalesce(F("credit_interest_accrued"), Value(Decimal("0")))
        - Coalesce(F("credit_interest_paid"), Value(Decimal("0"))),
        Value(Decimal("0")),
        output_field=DecimalField(max_digits=12, decimal_places=2),
    )


def _open_credit_sale_filter(prefix="transaction__"):
    return Q(
        **{
            f"{prefix}payment_method": "credit",
            f"{prefix}status": "completed",
            f"{prefix}credit_settled_at__isnull": True,
        }
    )


def unsettled_credit_items(member: Member):
    """Line items on open credit sales that still have an outstanding balance."""
    return (
        TransactionItem.objects.filter(
            transaction__member=member,
            credit_settled_at__isnull=True,
        )
        .filter(_open_credit_sale_filter())
        .annotate(outstanding=_credit_outstanding_expression())
        .filter(outstanding__gt=Decimal("0"))
        .select_related("transaction", "product")
        .order_by("transaction__created_at", "transaction_id", "id")
    )


def unsettled_credit_sales(member: Member):
    """Credit sales with unsettled principal and/or unpaid interest."""
    from helper.credit_interest_helper import ensure_credit_interest_up_to_date

    ensure_credit_interest_up_to_date(member_id=member.pk)
    unsettled = unsettled_credit_items(member)
    interest_open = Transaction.objects.filter(
        member=member,
        payment_method="credit",
        status="completed",
        credit_settled_at__isnull=True,
    ).annotate(interest_out=_interest_outstanding_expression()).filter(
        interest_out__gt=Decimal("0")
    )
    return (
        Transaction.objects.filter(member=member)
        .filter(_open_credit_sale_filter(prefix=""))
        .filter(
            Exists(unsettled.filter(transaction_id=OuterRef("pk")))
            | Exists(interest_open.filter(pk=OuterRef("pk")))
        )
        .prefetch_related("items")
        .order_by("created_at", "id")
    )


def member_credit_principal_outstanding(member: Member) -> Decimal:
    total = unsettled_credit_items(member).aggregate(t=Sum("outstanding"))["t"]
    return Decimal(total or 0).quantize(Decimal("0.01"))


def member_credit_outstanding_amount(member: Member) -> Decimal:
    """Principal + unpaid interest for *member* (accrues interest first)."""
    from helper.credit_interest_helper import (
        ensure_credit_interest_up_to_date,
        member_credit_interest_outstanding,
    )

    ensure_credit_interest_up_to_date(member_id=member.pk)
    principal = member_credit_principal_outstanding(member)
    interest = member_credit_interest_outstanding(member.pk)
    return (principal + interest).quantize(Decimal("0.01"))


def unsettled_credit_items_queryset():
    """Unsettled credit line items across all members (for aggregates and annotations)."""
    return (
        TransactionItem.objects.filter(credit_settled_at__isnull=True)
        .filter(_open_credit_sale_filter())
        .annotate(outstanding=_credit_outstanding_expression())
        .filter(outstanding__gt=Decimal("0"))
    )


def credit_outstanding_subquery():
    """Scalar subquery: sum of unsettled credit principal for the outer Member row."""
    return (
        unsettled_credit_items_queryset()
        .filter(transaction__member_id=OuterRef("pk"))
        .values("transaction__member_id")
        .annotate(total=Sum("outstanding"))
        .values("total")[:1]
    )


def credit_interest_outstanding_subquery():
    """Scalar subquery: unpaid interest on open credit sales for the outer Member."""
    return (
        Transaction.objects.filter(
            member_id=OuterRef("pk"),
            payment_method="credit",
            status="completed",
            credit_settled_at__isnull=True,
        )
        .annotate(unpaid=_interest_outstanding_expression())
        .values("member_id")
        .annotate(total=Sum("unpaid"))
        .values("total")[:1]
    )


def annotate_members_credit_outstanding(queryset):
    """Annotate Member queryset with ``credit_outstanding`` (principal + interest)."""
    return queryset.annotate(
        credit_principal_outstanding=Coalesce(
            Subquery(
                credit_outstanding_subquery(),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            ),
            Value(Decimal("0")),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        ),
        credit_interest_outstanding=Coalesce(
            Subquery(
                credit_interest_outstanding_subquery(),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            ),
            Value(Decimal("0")),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        ),
        credit_outstanding=F("credit_principal_outstanding")
        + F("credit_interest_outstanding"),
    )


def members_with_unsettled_credit_filter():
    """Exists filter: member has unsettled principal or unpaid interest."""
    principal_exists = Exists(
        unsettled_credit_items_queryset().filter(transaction__member_id=OuterRef("pk"))
    )
    interest_exists = Exists(
        Transaction.objects.filter(
            member_id=OuterRef("pk"),
            payment_method="credit",
            status="completed",
            credit_settled_at__isnull=True,
        )
        .annotate(unpaid=_interest_outstanding_expression())
        .filter(unpaid__gt=Decimal("0"))
    )
    return principal_exists | interest_exists


def _item_sort_key(item: TransactionItem):
    return (item.transaction.created_at, item.transaction_id, item.id)


def _line_outstanding(item: TransactionItem) -> Decimal:
    if hasattr(item, "outstanding"):
        return Decimal(item.outstanding).quantize(Decimal("0.01"))
    return item.credit_line_outstanding


def _sale_interest_outstanding(sale: Transaction) -> Decimal:
    return sale.credit_interest_outstanding


def _allocate_payment_fifo(
    items: List[TransactionItem],
    amount_paid: Decimal,
    *,
    interest_by_sale: dict | None = None,
) -> Tuple[List[Tuple[Transaction, Decimal]], List[Tuple[TransactionItem, Decimal]]]:
    """
    Apply *amount_paid* first to interest (FIFO by sale), then to principal (FIFO by item).

    Example: principal ₱500 + interest ₱15 = ₱515, pay ₱100
      → ₱15 interest + ₱85 principal → remaining principal ₱415.
    Next month on ₱415: (415 × rate) + 415.

    Returns (interest_allocations, principal_allocations).
    """
    amount_paid = Decimal(amount_paid).quantize(Decimal("0.01"))
    if amount_paid <= 0:
        raise ValueError("Amount to pay must be greater than zero.")

    interest_by_sale = interest_by_sale or {}
    ordered = sorted(items, key=_item_sort_key)
    sale_ids_ordered: List[int] = []
    sales_map: dict = {}
    for item in ordered:
        sale = item.transaction
        if sale.id not in sales_map:
            sales_map[sale.id] = sale
            sale_ids_ordered.append(sale.id)

    selected_principal = sum((_line_outstanding(i) for i in ordered), Decimal("0")).quantize(
        Decimal("0.01")
    )
    selected_interest = sum(
        (Decimal(interest_by_sale.get(sid, Decimal("0"))) for sid in sale_ids_ordered),
        Decimal("0"),
    ).quantize(Decimal("0.01"))
    for sid, amt in interest_by_sale.items():
        if sid not in sale_ids_ordered:
            selected_interest = (selected_interest + Decimal(amt)).quantize(Decimal("0.01"))
            sale_ids_ordered.append(sid)

    selected_max = (selected_principal + selected_interest).quantize(Decimal("0.01"))
    if amount_paid > selected_max:
        raise ValueError(
            f"Amount cannot exceed ₱{selected_max} (outstanding on selected products/interest)."
        )

    remaining = amount_paid
    interest_allocations: List[Tuple[Transaction, Decimal]] = []
    for sid in sale_ids_ordered:
        if remaining <= 0:
            break
        due = Decimal(interest_by_sale.get(sid, Decimal("0"))).quantize(Decimal("0.01"))
        if due <= 0:
            continue
        applied = min(due, remaining).quantize(Decimal("0.01"))
        sale = sales_map.get(sid)
        if sale is None:
            sale = Transaction.objects.get(pk=sid)
            sales_map[sid] = sale
        interest_allocations.append((sale, applied))
        remaining = (remaining - applied).quantize(Decimal("0.01"))

    principal_allocations: List[Tuple[TransactionItem, Decimal]] = []
    for item in ordered:
        if remaining <= 0:
            break
        outstanding = _line_outstanding(item)
        if outstanding <= 0:
            continue
        applied = min(outstanding, remaining).quantize(Decimal("0.01"))
        principal_allocations.append((item, applied))
        remaining = (remaining - applied).quantize(Decimal("0.01"))

    if not interest_allocations and not principal_allocations:
        raise ValueError("No outstanding balance on the selected products.")

    return interest_allocations, principal_allocations


def _finalize_transaction_if_fully_settled(sale: Transaction, payment: CreditPayment, settled_at) -> None:
    if sale.credit_settled_at:
        return
    sale.refresh_from_db(
        fields=["credit_interest_accrued", "credit_interest_paid", "credit_settled_at"]
    )
    if sale.credit_interest_outstanding > 0:
        return
    if sale.items.filter(credit_settled_at__isnull=True).exists():
        still_owing = False
        for item in sale.items.filter(credit_settled_at__isnull=True):
            if item.credit_line_outstanding > 0:
                still_owing = True
                break
        if still_owing:
            return
    sale.credit_settled_at = settled_at
    sale.credit_payment = payment
    sale.save(update_fields=["credit_settled_at", "credit_payment", "updated_at"])


def settle_member_credit(
    *,
    member: Member,
    payment_method: str,
    performed_by,
    authorizing_member: Member | None,
    notes: str = "",
    transaction_ids: Iterable[int] | None = None,
    item_ids: Iterable[int] | None = None,
    amount_paid: Decimal | None = None,
) -> Tuple[CreditPayment, List[Transaction], List[TransactionItem]]:
    """
    Pay off unsettled credit for *member*.

    Payment applies to interest first, then principal. Interest is not waived.
    After a partial pay, future months charge (remaining_principal × rate) on
    the reduced principal only.

    Example: ₱500 + ₱15 interest = ₱515, pay ₱100
      → pay ₱15 interest + ₱85 principal → ₱415 principal left
      → next month: (415 × 0.015) + 415 = ₱421.23
    """
    if payment_method not in ("cash", "debit"):
        raise ValueError("Invalid payment method")

    from helper.credit_interest_helper import ensure_credit_interest_up_to_date

    with db_transaction.atomic():
        member = Member.objects.select_for_update().get(pk=member.pk)
        ensure_credit_interest_up_to_date(member_id=member.pk)

        items_qs = unsettled_credit_items(member).select_for_update()
        open_sales_qs = Transaction.objects.select_for_update().filter(
            member=member,
            payment_method="credit",
            status="completed",
            credit_settled_at__isnull=True,
        )

        if item_ids is not None:
            id_list = list(item_ids)
            if not id_list:
                raise ValueError("Select at least one product to pay.")
            items = list(items_qs.filter(id__in=id_list))
            if len(items) != len(set(id_list)):
                raise ValueError(
                    "One or more selected products are invalid or already settled."
                )
            selected_sale_ids = {i.transaction_id for i in items}
        elif transaction_ids is not None:
            id_list = list(transaction_ids)
            if not id_list:
                raise ValueError("Select at least one credit sale to pay.")
            selected_sales = list(open_sales_qs.filter(id__in=id_list))
            if len(selected_sales) != len(set(id_list)):
                raise ValueError(
                    "One or more selected sales are invalid or already settled."
                )
            selected_sale_ids = {s.id for s in selected_sales}
            items = list(items_qs.filter(transaction_id__in=selected_sale_ids))
        else:
            items = list(items_qs)
            selected_sales = list(open_sales_qs)
            selected_sale_ids = {s.id for s in selected_sales}

        sales_for_interest = {
            s.id: s for s in open_sales_qs.filter(id__in=selected_sale_ids)
        }
        for item in items:
            sales_for_interest.setdefault(item.transaction_id, item.transaction)

        interest_by_sale = {
            sid: _sale_interest_outstanding(sale)
            for sid, sale in sales_for_interest.items()
            if _sale_interest_outstanding(sale) > 0 or sid in {i.transaction_id for i in items}
        }
        for item in items:
            interest_by_sale.setdefault(item.transaction_id, Decimal("0.00"))

        if not items and not any(v > 0 for v in interest_by_sale.values()):
            raise ValueError("This member has no outstanding credit to pay.")

        selected_principal = sum(
            (_line_outstanding(i) for i in items), Decimal("0")
        ).quantize(Decimal("0.01"))
        selected_interest = sum(
            (Decimal(v) for v in interest_by_sale.values()), Decimal("0")
        ).quantize(Decimal("0.01"))
        selected_total = (selected_principal + selected_interest).quantize(Decimal("0.01"))

        if amount_paid is None:
            pay_amount = selected_total
        else:
            try:
                pay_amount = Decimal(str(amount_paid)).quantize(Decimal("0.01"))
            except (InvalidOperation, TypeError) as exc:
                raise ValueError("Invalid amount to pay.") from exc

        interest_allocations, principal_allocations = _allocate_payment_fifo(
            items, pay_amount, interest_by_sale=interest_by_sale
        )

        amount = pay_amount
        interest_portion = sum((a for _, a in interest_allocations), Decimal("0")).quantize(
            Decimal("0.01")
        )
        balance_before = None
        balance_after = None
        balance_txn = None

        if payment_method == "debit":
            balance_before = member.balance
            if balance_before < amount:
                raise ValueError(
                    f"Insufficient balance. Available: ₱{balance_before}, required: ₱{amount}"
                )
            member.deduct_balance(amount)
            member.refresh_from_db(fields=["balance"])
            balance_after = member.balance
            note_parts = ["Credit settlement via member debit balance"]
            if notes:
                note_parts.append(notes)
            if authorizing_member:
                note_parts.append(
                    f"(PIN authorised by {authorizing_member.full_name} — "
                    f"{authorizing_member.get_role_display()})"
                )
            balance_txn = BalanceTransaction.objects.create(
                member=member,
                transaction_type="deduction",
                amount=amount,
                balance_before=balance_before,
                balance_after=balance_after,
                notes=". ".join(note_parts),
            )

        payment = CreditPayment.objects.create(
            member=member,
            amount_paid=amount,
            interest_amount=interest_portion,
            payment_method=payment_method,
            balance_before=balance_before,
            balance_after=balance_after,
            performed_by=performed_by,
            notes=notes,
        )

        settled_at = timezone.now()
        settled_items: List[TransactionItem] = []
        payment_lines: List[CreditPaymentLine] = []

        for sale, applied in interest_allocations:
            new_paid = (
                Decimal(sale.credit_interest_paid or 0) + applied
            ).quantize(Decimal("0.01"))
            sale.credit_interest_paid = new_paid
            sale.save(update_fields=["credit_interest_paid", "updated_at"])

        for item, applied in principal_allocations:
            new_paid = (
                Decimal(item.credit_amount_paid or 0) + applied
            ).quantize(Decimal("0.01"))
            item.credit_amount_paid = new_paid
            item.credit_payment = payment
            update_fields = ["credit_amount_paid", "credit_payment"]
            if new_paid >= item.credit_line_amount:
                item.credit_settled_at = settled_at
                update_fields.append("credit_settled_at")
            item.save(update_fields=update_fields)
            settled_items.append(item)
            payment_lines.append(
                CreditPaymentLine(
                    payment=payment,
                    item=item,
                    amount_applied=applied,
                )
            )

        if payment_lines:
            CreditPaymentLine.objects.bulk_create(payment_lines)

        affected_sale_ids = {i.transaction_id for i in settled_items} | {
            s.id for s, _ in interest_allocations
        }
        sales = list(
            Transaction.objects.filter(id__in=affected_sale_ids).order_by(
                "created_at", "id"
            )
        )
        for sale in sales:
            _finalize_transaction_if_fully_settled(sale, payment, settled_at)

        if balance_txn:
            payment.notes = (payment.notes or "").strip()
            extra = f"Balance txn: {balance_txn.transaction_number}"
            payment.notes = f"{payment.notes}\n{extra}".strip() if payment.notes else extra
            payment.save(update_fields=["notes"])

        return payment, sales, settled_items
