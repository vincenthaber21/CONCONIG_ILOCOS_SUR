"""Accrue monthly interest on overdue store credit (utang) after grace period."""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from django.db import transaction as db_transaction
from django.db.models import F, Sum
from django.utils import timezone

from transactions.models import Transaction


def _open_credit_sales_qs(member_id: Optional[int] = None):
    qs = Transaction.objects.filter(
        payment_method="credit",
        status="completed",
        credit_settled_at__isnull=True,
        member__isnull=False,
    )
    if member_id is not None:
        qs = qs.filter(member_id=member_id)
    return qs


def _principal_outstanding_for_sale(sale: Transaction) -> Decimal:
    total = Decimal("0.00")
    for item in sale.items.all():
        if item.credit_settled_at is not None:
            continue
        total += item.credit_line_outstanding
    return total.quantize(Decimal("0.01"))


def interest_rate_as_multiplier(interest_rate: Decimal) -> Decimal:
    """
    Convert the stored rate into a decimal multiplier.

    Example: 0.015 → interest = principal × 0.015 each month.
    Values greater than 1 are treated as percents (1.5 → 0.015).
    """
    rate = Decimal(str(interest_rate or 0))
    if rate <= 0:
        return Decimal("0")
    if rate > Decimal("1"):
        return (rate / Decimal("100")).quantize(Decimal("0.000001"))
    return rate


def _add_months(d: date, months: int) -> date:
    """Add calendar months to *d*, clamping the day when needed."""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))


def interest_start_date(sale: Transaction, grace_period_days: int) -> date:
    """
    First calendar date after the grace period (eligible for interest).

    No interest is charged on this day — the first charge is one month later.
    """
    created = timezone.localtime(sale.created_at).date()
    return created + timedelta(days=int(grace_period_days or 0))


def first_interest_due_date(sale: Transaction, grace_period_days: int) -> date:
    """
    Date of the first monthly interest charge.

    Grace period first, then wait one full month before applying interest.
    Example: sale Jul 1, grace 2 days → eligible Jul 3 → first charge Aug 3.
    """
    return _add_months(interest_start_date(sale, grace_period_days), 1)


def monthly_periods_due(first_due: date, as_of: date) -> int:
    """How many monthly interest periods are due on or before *as_of*."""
    if as_of < first_due:
        return 0
    count = 0
    due = first_due
    while due <= as_of:
        count += 1
        due = _add_months(due, 1)
    return count


def _last_period_date(first_due: date, periods: int) -> Optional[date]:
    if periods <= 0:
        return None
    return _add_months(first_due, periods - 1)


def accrue_interest_on_sale(
    sale: Transaction,
    *,
    interest_rate: Decimal,
    grace_period_days: int,
    as_of: Optional[date] = None,
) -> Decimal:
    """
    Apply monthly interest on *sale* after the grace period.

    Rules:
      1. Within grace → no interest
      2. First charge = one full month after grace ends
      3. Each later unpaid month adds remaining principal × rate
      4. After a partial Pay Credit, unpaid interest stays until paid (interest first);
         later months add remaining_principal × rate only
         (e.g. ₱415 left → next month 415 + (415 × 0.015) = ₱421.23)

    Example (rate 0.015, principal ₱500, grace 2 days, sale Jul 1):
      Jul 1–Jul 2: grace (₱0 interest)
      Aug 3: first month → +₱7.50 (total due 507.50)
      Later months keep adding principal × rate while unpaid
    """
    as_of = as_of or timezone.localdate()
    multiplier = interest_rate_as_multiplier(interest_rate)
    if multiplier <= 0:
        return Decimal("0.00")

    grace_end = interest_start_date(sale, grace_period_days)
    if as_of < grace_end:
        return Decimal("0.00")

    first_due = first_interest_due_date(sale, grace_period_days)
    if as_of < first_due:
        paid = Decimal(sale.credit_interest_paid or 0).quantize(Decimal("0.01"))
        accrued = Decimal(sale.credit_interest_accrued or 0).quantize(Decimal("0.01"))
        if paid == 0 and accrued > 0:
            sale.credit_interest_accrued = Decimal("0.00")
            sale.credit_interest_last_applied_on = None
            sale.save(
                update_fields=[
                    "credit_interest_accrued",
                    "credit_interest_last_applied_on",
                    "updated_at",
                ]
            )
            return (-accrued).quantize(Decimal("0.01"))
        return Decimal("0.00")

    principal = _principal_outstanding_for_sale(sale)
    if principal <= 0:
        return Decimal("0.00")

    monthly_charge = (principal * multiplier).quantize(Decimal("0.01"))
    if monthly_charge <= 0:
        return Decimal("0.00")

    should_periods = monthly_periods_due(first_due, as_of)
    last_applied = sale.credit_interest_last_applied_on
    already_periods = (
        monthly_periods_due(first_due, last_applied) if last_applied is not None else 0
    )
    new_periods = should_periods - already_periods
    if new_periods <= 0:
        return Decimal("0.00")

    total_new = (monthly_charge * new_periods).quantize(Decimal("0.01"))
    accrued = Decimal(sale.credit_interest_accrued or 0).quantize(Decimal("0.01"))

    sale.credit_interest_accrued = (accrued + total_new).quantize(Decimal("0.01"))
    sale.credit_interest_last_applied_on = _last_period_date(first_due, should_periods)
    sale.save(
        update_fields=[
            "credit_interest_accrued",
            "credit_interest_last_applied_on",
            "updated_at",
        ]
    )
    return total_new


def ensure_credit_interest_up_to_date(
    *,
    member_id: Optional[int] = None,
    as_of: Optional[date] = None,
) -> Decimal:
    """
    Accrue overdue monthly credit interest for open sales.

    Safe to call before displaying or settling outstanding balances.
    """
    from admin_panel.models import CreditSettings

    settings = CreditSettings.get()
    if not settings.is_enabled:
        return Decimal("0.00")
    rate = Decimal(str(settings.interest_rate or 0))
    if rate <= 0:
        return Decimal("0.00")

    as_of = as_of or timezone.localdate()
    grace = int(settings.grace_period_days or 0)
    total_new = Decimal("0.00")

    sales = list(
        _open_credit_sales_qs(member_id=member_id)
        .prefetch_related("items")
        .order_by("created_at", "id")
    )
    for sale in sales:
        with db_transaction.atomic():
            locked = (
                Transaction.objects.select_for_update()
                .prefetch_related("items")
                .filter(pk=sale.pk, credit_settled_at__isnull=True)
                .first()
            )
            if not locked:
                continue
            total_new += accrue_interest_on_sale(
                locked,
                interest_rate=rate,
                grace_period_days=grace,
                as_of=as_of,
            )
    return total_new.quantize(Decimal("0.01"))


def member_credit_interest_outstanding(member_id: int) -> Decimal:
    """Sum of unpaid interest on open credit sales for a member."""
    rows = (
        _open_credit_sales_qs(member_id=member_id)
        .annotate(
            unpaid=F("credit_interest_accrued") - F("credit_interest_paid"),
        )
        .aggregate(t=Sum("unpaid"))
    )
    total = Decimal(rows["t"] or 0)
    return max(total, Decimal("0")).quantize(Decimal("0.01"))


def interest_outstanding_expression():
    """DB expression for unpaid interest on a Transaction row."""
    from django.db.models import DecimalField, Value
    from django.db.models.functions import Coalesce, Greatest

    return Greatest(
        Coalesce(F("credit_interest_accrued"), Value(Decimal("0")))
        - Coalesce(F("credit_interest_paid"), Value(Decimal("0"))),
        Value(Decimal("0")),
        output_field=DecimalField(max_digits=12, decimal_places=2),
    )
