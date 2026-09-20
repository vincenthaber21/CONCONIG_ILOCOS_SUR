"""Open accounts and post savings ledger movements."""

from datetime import datetime, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from . import models
from .policy import (
    ANNUAL_INTEREST_RATE,
    MAX_INTEREST_PERIODS,
    format_rate,
    interest_amount,
    next_interest_credit_on,
)

ZERO = Decimal("0.00")


def _money(value):
    return Decimal(value).quantize(Decimal("0.01"))


def resolve_opened_at(opening_date=None):
    """Aware datetime for the official account opening date.

    Defaults to now. A past calendar date keeps today's local time-of-day so
    interest anniversaries fall on that date. Future dates are rejected.
    """
    now = timezone.now()
    if opening_date is None:
        return now
    if isinstance(opening_date, datetime):
        dt = opening_date
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_current_timezone())
        if dt > now:
            raise ValidationError("Opening date cannot be in the future.")
        return dt
    today = timezone.localdate()
    if opening_date > today:
        raise ValidationError("Opening date cannot be in the future.")
    if opening_date == today:
        return now
    local_now = timezone.localtime(now)
    naive = datetime.combine(opening_date, local_now.time().replace(microsecond=0))
    return timezone.make_aware(naive, timezone.get_current_timezone())


def compute_maturity_date(product, opened_at=None):
    if not product.term_months:
        return None
    when = opened_at or timezone.now()
    if isinstance(when, datetime):
        start = timezone.localtime(when).date() if timezone.is_aware(when) else when.date()
    else:
        start = when
    # Approximate month length; cooperative terms are calendar months.
    return start + timedelta(days=int(product.term_months) * 30)


def _ensure_within_max_balance(account, credit_amount):
    """Reject credits that would push the balance above the product maximum."""
    max_bal = _money(getattr(account.product, "max_balance", ZERO) or ZERO)
    if max_bal <= ZERO:
        return
    projected = _money(account.balance) + _money(credit_amount)
    if projected > max_bal:
        raise ValidationError(
            f"Balance cannot exceed ₱{max_bal:,.2f} for this savings product "
            f"(current ₱{_money(account.balance):,.2f})."
        )


def member_has_closed_savings(member) -> bool:
    """True when the member has ever closed a savings account (permanent bar)."""
    return models.MemberSavingsAccount.objects.filter(
        member_id=getattr(member, "pk", member),
        status=models.MemberSavingsAccount.Status.CLOSED,
    ).exists()


def assert_member_can_open_savings(member, product=None):
    """Closed savings is permanent — member may not open another account."""
    if member_has_closed_savings(member):
        raise ValidationError(
            "This member previously closed a savings account and cannot open "
            "another one."
        )
    if product is None:
        return
    open_existing = (
        models.MemberSavingsAccount.objects.filter(
            member_id=getattr(member, "pk", member),
            product_id=getattr(product, "pk", product),
        )
        .exclude(status=models.MemberSavingsAccount.Status.CLOSED)
        .exists()
    )
    if open_existing:
        raise ValidationError(
            "This member already has an open savings account for this product."
        )


@transaction.atomic
def open_account(*, member, product, opening_amount, performed_by=None, notes="", opening_date=None):
    if not product.is_active:
        raise ValidationError("This savings product is not active.")
    assert_member_can_open_savings(member, product)
    amount = _money(opening_amount)
    if amount < _money(product.min_opening_deposit):
        raise ValidationError(
            f"Opening deposit must be at least ₱{product.min_opening_deposit}."
        )
    max_bal = _money(getattr(product, "max_balance", ZERO) or ZERO)
    if max_bal > ZERO and amount > max_bal:
        raise ValidationError(
            f"Opening deposit cannot exceed the maximum balance of ₱{max_bal:,.2f}."
        )

    opened_at = resolve_opened_at(opening_date)
    account = models.MemberSavingsAccount(
        member=member,
        product=product,
        balance=ZERO,
        status=models.MemberSavingsAccount.Status.ACTIVE,
        opened_at=opened_at,
        maturity_date=compute_maturity_date(product, opened_at),
        notes=notes or "",
    )
    account.save()
    _post(
        account,
        models.SavingsTransaction.TxnType.OPENING,
        amount,
        performed_by=performed_by,
        notes=notes or "Opening deposit",
        posted_at=opened_at,
    )
    return account


@transaction.atomic
def deposit(*, account, amount, performed_by=None, notes=""):
    account = models.MemberSavingsAccount.objects.select_for_update().select_related(
        "product"
    ).get(pk=account.pk)
    _ensure_active(account)
    money = _money(amount)
    if money <= ZERO:
        raise ValidationError("Deposit amount must be greater than zero.")
    min_add = _money(account.product.min_additional_deposit)
    if min_add > ZERO and money < min_add:
        raise ValidationError(f"Additional deposits must be at least ₱{min_add}.")
    _ensure_within_max_balance(account, money)
    return _post(
        account,
        models.SavingsTransaction.TxnType.DEPOSIT,
        money,
        performed_by=performed_by,
        notes=notes,
    )


@transaction.atomic
def withdraw(*, account, amount, performed_by=None, notes=""):
    account = models.MemberSavingsAccount.objects.select_for_update().get(pk=account.pk)
    _ensure_active(account)
    product = account.product
    if not product.allows_withdrawal:
        raise ValidationError("Withdrawals are not allowed on this savings product.")
    money = _money(amount)
    if money <= ZERO:
        raise ValidationError("Withdrawal amount must be greater than zero.")
    remaining = _money(account.balance) - money
    min_bal = _money(product.min_maintaining_balance)
    if remaining < min_bal:
        raise ValidationError(
            f"Balance after withdrawal must stay at least ₱{min_bal}."
        )
    return _post(
        account,
        models.SavingsTransaction.TxnType.WITHDRAWAL,
        money,
        performed_by=performed_by,
        notes=notes,
        credit=False,
    )


@transaction.atomic
def post_admin_transaction(*, account, txn_type, amount, performed_by=None, notes=""):
    """Post a ledger row from Django admin while keeping the account balance in sync."""
    account = models.MemberSavingsAccount.objects.select_for_update().select_related("product").get(
        pk=account.pk
    )
    if txn_type == models.SavingsTransaction.TxnType.OPENING:
        raise ValidationError("Use Open account (with an opening deposit) instead of this type.")
    if txn_type == models.SavingsTransaction.TxnType.DEPOSIT:
        return deposit(account=account, amount=amount, performed_by=performed_by, notes=notes)
    if txn_type == models.SavingsTransaction.TxnType.WITHDRAWAL:
        return withdraw(account=account, amount=amount, performed_by=performed_by, notes=notes)

    _ensure_active(account)
    money = _money(amount)
    if money <= ZERO:
        raise ValidationError("Amount must be greater than zero.")
    credit = txn_type != models.SavingsTransaction.TxnType.PENALTY
    return _post(
        account,
        txn_type,
        money,
        performed_by=performed_by,
        notes=notes,
        credit=credit,
    )


def _ensure_active(account):
    if account.status != models.MemberSavingsAccount.Status.ACTIVE:
        raise ValidationError("This savings account is not active.")


def last_withdrawal_at(account):
    return (
        models.SavingsTransaction.objects.filter(
            account_id=account.pk,
            transaction_type=models.SavingsTransaction.TxnType.WITHDRAWAL,
        )
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first()
    )


def last_interest_at(account):
    return (
        models.SavingsTransaction.objects.filter(
            account_id=account.pk,
            transaction_type=models.SavingsTransaction.TxnType.INTEREST,
        )
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first()
    )


def effective_interest_rate(account, as_of=None):
    """Flat 5% annual rate, applied monthly as (balance * 5%) / 12."""
    return ANNUAL_INTEREST_RATE


def months_of_interest_due(account, as_of=None):
    """How many monthly anniversary interest dates have passed since opening / last credit."""
    as_of = as_of or timezone.now()
    cursor = last_interest_at(account) or account.opened_at
    if not cursor:
        return 0
    due = 0
    nxt = next_interest_credit_on(cursor)
    while due < MAX_INTEREST_PERIODS and nxt is not None and as_of >= nxt:
        due += 1
        nxt = next_interest_credit_on(nxt)
    return due


# Backwards-compatible alias used by older call sites / tests.
years_of_interest_due = months_of_interest_due


def next_unpaid_interest_on(account, as_of=None):
    """First monthly anniversary interest date that has not been credited yet."""
    cursor = last_interest_at(account) or account.opened_at
    return next_interest_credit_on(cursor) if cursor else None


def interest_snapshot(account, as_of=None):
    """Template-ready interest status for one savings account."""
    as_of = as_of or timezone.now()
    last_wd = last_withdrawal_at(account)
    rate = effective_interest_rate(account, as_of=as_of)
    rate_display = format_rate(rate)
    last_credit = last_interest_at(account)
    next_credit_on = next_unpaid_interest_on(account, as_of=as_of)
    months_due = months_of_interest_due(account, as_of=as_of)
    due = bool(
        account.can_transact
        and _money(account.balance) > ZERO
        and months_due > 0
    )
    estimated = interest_amount(account.balance, rate)
    return {
        "annual_rate": rate,
        "annual_rate_display": rate_display,
        "base_rate": rate,
        "loyalty_rate": rate,
        "base_rate_display": rate_display,
        "loyalty_rate_display": rate_display,
        "effective_rate": rate,
        "effective_rate_display": rate_display,
        "qualifies_loyalty": True,
        "last_withdrawal_at": last_wd,
        "loyalty_eligible_on": None,
        "last_interest_at": last_credit,
        "next_credit_on": next_credit_on,
        "years_due": months_due,
        "months_due": months_due,
        "interest_due": due,
        "estimated_interest": estimated,
    }


@transaction.atomic
def credit_due_interest(*, account, performed_by=None, as_of=None):
    """Post monthly interest that is already due (catches up missed months)."""
    account = (
        models.MemberSavingsAccount.objects.select_for_update()
        .select_related("product")
        .get(pk=account.pk)
    )
    _ensure_active(account)
    as_of = as_of or timezone.now()
    months_due = months_of_interest_due(account, as_of=as_of)
    rate = effective_interest_rate(account, as_of=as_of)
    posted = []
    cursor = last_interest_at(account) or account.opened_at
    if months_due < 1 or _money(account.balance) <= ZERO:
        next_on = next_interest_credit_on(cursor) if cursor else None
        when = (
            timezone.localtime(next_on).strftime("%b %d, %Y")
            if next_on
            else "one month after opening"
        )
        raise ValidationError(
            f"No interest is due yet. Monthly interest can be credited on {when}."
        )
    for month_n in range(1, months_due + 1):
        period_on = next_interest_credit_on(cursor)
        money = interest_amount(account.balance, rate)
        if money <= ZERO or period_on is None:
            break
        when = timezone.localtime(period_on).strftime("%b %d, %Y")
        note = (
            f"Monthly interest at {format_rate(rate)} / 12 "
            f"({format_rate(rate)} annual) for {when}."
        )
        if months_due > 1:
            note = f"{note} Month {month_n} of {months_due}."
        posted.append(
            _post(
                account,
                models.SavingsTransaction.TxnType.INTEREST,
                money,
                performed_by=performed_by,
                notes=note,
                posted_at=period_on,
            )
        )
        cursor = period_on
    if not posted:
        raise ValidationError("Interest amount is zero; nothing was credited.")
    return posted


def auto_credit_due_interest(*, account, performed_by=None, as_of=None):
    """Credit interest if already due; return posted txns (empty if nothing due).

    Does not raise when interest is not yet due — safe to call on every page view.
    """
    as_of = as_of or timezone.now()
    if not account or not getattr(account, "can_transact", False):
        return []
    if _money(getattr(account, "balance", ZERO)) <= ZERO:
        return []
    if months_of_interest_due(account, as_of=as_of) < 1:
        return []
    try:
        return credit_due_interest(
            account=account,
            performed_by=performed_by,
            as_of=as_of,
        )
    except ValidationError:
        return []


def accrue_due_savings_interest(*, as_of=None, performed_by=None):
    """Credit monthly interest on every active account that is due."""
    as_of = as_of or timezone.now()
    credited = 0
    skipped = 0
    qs = models.MemberSavingsAccount.objects.filter(
        status=models.MemberSavingsAccount.Status.ACTIVE,
        balance__gt=ZERO,
    ).select_related("product")
    for account in qs:
        snap = interest_snapshot(account, as_of=as_of)
        if not snap["interest_due"]:
            continue
        try:
            posted = credit_due_interest(
                account=account,
                performed_by=performed_by,
                as_of=as_of,
            )
        except ValidationError:
            skipped += 1
            continue
        credited += len(posted)
    return credited, skipped


@transaction.atomic
def delete_transaction(txn, *, performed_by=None):
    """
    Remove a savings ledger row and reverse its effect on the account balance.

    Only the latest transaction for that account may be deleted so earlier
    ``balance_before`` / ``balance_after`` values stay consistent.
    """
    txn = (
        models.SavingsTransaction.objects.select_related("account")
        .select_for_update()
        .get(pk=txn.pk)
    )
    account = models.MemberSavingsAccount.objects.select_for_update().get(pk=txn.account_id)

    latest = (
        models.SavingsTransaction.objects.filter(account_id=account.pk)
        .order_by("-created_at", "-id")
        .first()
    )
    if not latest or latest.pk != txn.pk:
        raise ValidationError(
            f"Only the latest transaction for {account.account_number} can be deleted "
            f"(latest is {latest.reference if latest else 'none'}). "
            "Delete newer rows first."
        )

    amount = _money(txn.amount)
    before = _money(account.balance)
    if txn.is_credit:
        after = before - amount
    else:
        after = before + amount
    if after < ZERO:
        raise ValidationError(
            f"Cannot delete {txn.reference}: reversing it would make the balance negative "
            f"(current ₱{before}, transaction ₱{amount})."
        )

    account.balance = after
    account.save(update_fields=["balance", "updated_at"])
    reference = txn.reference
    txn.delete()
    return reference, account


@transaction.atomic
def close_account(*, account, performed_by=None, notes="", mark_member_resign=True):
    """
    Close a savings account and optionally set the member status to Resign.

    Any remaining balance is withdrawn in full (closing payout), then the
    account is marked Closed. Product withdrawal / maintaining-balance rules
    do not block this payout.

    Closing is permanent for savings eligibility: the member cannot open
    another savings account afterward (enforced by
    ``assert_member_can_open_savings``). When *mark_member_resign* is True,
    membership status becomes Resign but the member stays active so other
    coop services (loans, credit, kiosk, etc.) remain available.
    """
    from members.models import Member, MemberStatus

    account = (
        models.MemberSavingsAccount.objects.select_for_update()
        .select_related("member", "product")
        .get(pk=account.pk)
    )
    if account.status == models.MemberSavingsAccount.Status.CLOSED:
        raise ValidationError("This savings account is already closed.")

    payout = None
    remaining = _money(account.balance)
    closing_note = (notes or "").strip() or "Closing payout — full remaining balance withdrawn."
    if remaining > ZERO:
        payout = _post(
            account,
            models.SavingsTransaction.TxnType.WITHDRAWAL,
            remaining,
            performed_by=performed_by,
            notes=closing_note,
            credit=False,
        )

    now = timezone.now()
    account.status = models.MemberSavingsAccount.Status.CLOSED
    account.closed_at = now
    if notes:
        existing = (account.notes or "").strip()
        account.notes = f"{existing}\n{notes}".strip() if existing else notes
    account.save(update_fields=["status", "closed_at", "notes", "updated_at"])

    member = Member.objects.select_for_update().get(pk=account.member_id)
    if mark_member_resign:
        # Savings-only resign: status label reflects savings exit, but the
        # member stays active so loans, credit, kiosk, and other services
        # remain available. Permanent savings bar is via closed accounts.
        resign = MemberStatus.resolve_slug(MemberStatus.SLUG_RESIGN)
        member.apply_member_status(resign, deactivate=False)
        member.is_active = True
        member.inactive_remark = ""
        member.save(
            update_fields=[
                "member_status",
                "membership_status",
                "is_active",
                "inactive_remark",
                "updated_at",
            ]
        )

    return account, payout


def _post(account, txn_type, amount, *, performed_by=None, notes="", credit=True, posted_at=None):
    amount = _money(amount)
    before = _money(account.balance)
    if credit:
        _ensure_within_max_balance(account, amount)
    after = before + amount if credit else before - amount
    if after < ZERO:
        raise ValidationError("Insufficient savings balance.")
    account.balance = after
    account.save(update_fields=["balance", "updated_at"])
    txn = models.SavingsTransaction.objects.create(
        account=account,
        transaction_type=txn_type,
        amount=amount,
        balance_before=before,
        balance_after=after,
        notes=notes or "",
        performed_by=performed_by if getattr(performed_by, "pk", None) else None,
    )
    if posted_at is not None:
        models.SavingsTransaction.objects.filter(pk=txn.pk).update(
            created_at=posted_at,
            updated_at=posted_at,
        )
        txn.created_at = posted_at
        txn.updated_at = posted_at
    return txn
