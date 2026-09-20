"""Post share-capital deposits and withdrawals against member balances."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from members.models import Member, ShareCapitalTransaction

from .models import active_share_capital_product

ZERO = Decimal("0.00")


def _money(value):
    return Decimal(value).quantize(Decimal("0.01"))


def _product_or_default(product=None):
    return product if product is not None else active_share_capital_product()


def _assert_within_product_limits(product, *, current, credit_amount=ZERO, is_opening=False):
    if product is None:
        return
    credit_amount = _money(credit_amount)
    projected = _money(current) + credit_amount
    min_open = _money(product.min_contribution or ZERO)
    min_paid = product.min_paid_up
    if is_opening:
        floor = min_open if min_open > ZERO else (min_paid or ZERO)
        if floor > ZERO and projected < floor:
            raise ValidationError(
                f"Opening contribution must be at least ₱{floor:,.2f}."
            )
    max_paid = product.max_paid_up
    if max_paid is not None and projected > max_paid:
        raise ValidationError(
            f"Paid-up share capital cannot exceed ₱{max_paid:,.2f} "
            f"({product.max_shares} shares × ₱{product.par_value:,.2f})."
        )


@transaction.atomic
def post_deposit(*, member, amount, performed_by=None, notes="", product=None):
    member = Member.objects.select_for_update().get(pk=member.pk)
    amount = _money(amount)
    if amount <= ZERO:
        raise ValidationError("Amount must be greater than zero.")

    product = _product_or_default(product)
    before = _money(member.share_capital or ZERO)
    is_opening = before <= ZERO and not member.share_capital_transactions.exists()
    _assert_within_product_limits(
        product,
        current=before,
        credit_amount=amount,
        is_opening=is_opening,
    )
    after = before + amount
    member.share_capital = after
    member.save(update_fields=["share_capital", "updated_at"])

    txn_type = "opening" if is_opening else "deposit"
    return ShareCapitalTransaction.objects.create(
        member=member,
        transaction_type=txn_type,
        amount=amount,
        balance_before=before,
        balance_after=after,
        notes=notes or ("Opening share capital" if is_opening else ""),
        performed_by=performed_by,
    )


@transaction.atomic
def post_withdrawal(*, member, amount, performed_by=None, notes="", product=None):
    member = Member.objects.select_for_update().get(pk=member.pk)
    amount = _money(amount)
    if amount <= ZERO:
        raise ValidationError("Amount must be greater than zero.")

    product = _product_or_default(product)
    if product is not None and not product.allows_withdrawal:
        raise ValidationError(
            f'"{product.name}" does not allow share-capital withdrawals.'
        )

    before = _money(member.share_capital or ZERO)
    if amount > before:
        raise ValidationError(
            f"Cannot withdraw ₱{amount:,.2f}: paid-up share capital is only ₱{before:,.2f}."
        )
    after = before - amount
    if product is not None:
        min_paid = product.min_paid_up
        if min_paid is not None and after < min_paid and after > ZERO:
            raise ValidationError(
                f"Balance after withdrawal cannot fall below the minimum of ₱{min_paid:,.2f} "
                f"unless the capital is fully withdrawn."
            )

    member.share_capital = after
    member.save(update_fields=["share_capital", "updated_at"])
    return ShareCapitalTransaction.objects.create(
        member=member,
        transaction_type="withdrawal",
        amount=amount,
        balance_before=before,
        balance_after=after,
        notes=notes or "",
        performed_by=performed_by,
    )
