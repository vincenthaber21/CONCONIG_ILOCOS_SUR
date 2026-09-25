"""Open accounts and post savings ledger movements."""

from datetime import datetime, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from . import models
from .policy import (
    ANNUAL_INTEREST_RATE,
    MAX_INTEREST_PERIODS,
    MINIMUM_BALANCE_FOR_INTEREST,
    TIME_DEPOSIT_YEAR_MONTHS,
    time_deposit_min_amount,
    time_deposit_max_amount,
    compounding_schedule,
    earns_savings_interest,
    earns_time_deposit_interest,
    format_rate,
    interest_amount,
    next_interest_credit_on,
    schedule_for_months,
    time_deposit_interest_amount,
    time_deposit_term_label,
    time_deposit_term_rate,
    time_deposit_uses_term,
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
    """True when the member has ever closed a savings account (permanent bar).

    Covers primary-holder closures and joint accounts where the member was a
    co-owner when the account closed.
    """
    member_id = getattr(member, "pk", member)
    if models.MemberSavingsAccount.objects.filter(
        member_id=member_id,
        status=models.MemberSavingsAccount.Status.CLOSED,
    ).exists():
        return True
    return models.SavingsJointOwner.objects.filter(
        member_id=member_id,
        account__status=models.MemberSavingsAccount.Status.CLOSED,
    ).exists()


def member_open_product_accounts_qs(member, product=None):
    """Open (non-closed) accounts where *member* is primary or joint co-owner."""
    member_id = getattr(member, "pk", member)
    qs = models.MemberSavingsAccount.objects.filter(
        Q(member_id=member_id) | Q(joint_owners__id=member_id)
    ).exclude(status=models.MemberSavingsAccount.Status.CLOSED)
    if product is not None:
        qs = qs.filter(product_id=getattr(product, "pk", product))
    return qs.distinct()


def accounts_for_member_qs(member):
    """All savings accounts visible to a member (primary or joint co-owner)."""
    member_id = getattr(member, "pk", member)
    return (
        models.MemberSavingsAccount.objects.filter(
            Q(member_id=member_id) | Q(joint_owners__id=member_id)
        )
        .distinct()
        .select_related("member", "product")
        .prefetch_related("joint_owner_links__member")
        .order_by("-opened_at")
    )


def assert_member_can_open_savings(member, product=None):
    """Closed savings is permanent — member may not open another account."""
    if member_has_closed_savings(member):
        raise ValidationError(
            "This member previously closed a savings account and cannot open "
            "another one."
        )
    if product is None:
        return
    if member_open_product_accounts_qs(member, product).exists():
        raise ValidationError(
            "This member already has an open savings account for this product "
            "(as primary or joint co-owner)."
        )


def _normalize_joint_owners(*, primary, joint_owners):
    """Return a de-duplicated list of co-owners (never including the primary)."""
    if not joint_owners:
        return []
    seen = {getattr(primary, "pk", primary)}
    owners = []
    for owner in joint_owners:
        owner_id = getattr(owner, "pk", owner)
        if owner_id in seen:
            continue
        seen.add(owner_id)
        owners.append(owner)
    return owners


@transaction.atomic
def open_account(
    *,
    product,
    member=None,
    opening_amount,
    performed_by=None,
    notes="",
    opening_date=None,
    is_joint=False,
    joint_owners=None,
    deposit_term_months=None,
    passbook_serial=None,
    walk_in=None,
    beneficiaries=None,
):
    if not product.is_active:
        raise ValidationError("This savings product is not active.")

    co_owners = _normalize_joint_owners(primary=member, joint_owners=joint_owners or [])
    if is_joint and not co_owners:
        raise ValidationError(
            "A joint account needs at least one co-owner member "
            "(different from the primary holder)."
        )
    if walk_in and member is not None:
        raise ValidationError("A walk-in account does not use a member profile.")
    if walk_in and is_joint:
        raise ValidationError("A walk-in savings account cannot be a joint account.")
    if member is None and not walk_in:
        raise ValidationError("Select a member or enter the walk-in name.")
    if not is_joint and co_owners:
        raise ValidationError("Co-owners can only be added on a joint account.")
    for co_owner in co_owners:
        if getattr(co_owner, "pk", co_owner) == getattr(member, "pk", member):
            raise ValidationError(
                "Duplicate member: the co-owner must be different from the primary holder."
            )

    if member is not None:
        assert_member_can_open_savings(member, product)
    for co_owner in co_owners:
        assert_member_can_open_savings(co_owner, product)

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
    term = int(deposit_term_months) if deposit_term_months else None
    if (
        getattr(product, "product_type", None) == models.SavingsProduct.ProductType.TIME_DEPOSIT
        and time_deposit_uses_term(amount, product)
        and term not in (3, 6, 12)
    ):
        ceiling = time_deposit_max_amount(product)
        raise ValidationError(
            f"Above ₱{ceiling:,.2f}, select 3 months, 6 months, or 1 year."
        )
    serial = (passbook_serial or "").strip() or None
    if serial and models.MemberSavingsAccount.objects.filter(
        passbook_serial__iexact=serial
    ).exists():
        raise ValidationError(
            "That passbook serial number is already assigned to another savings account."
        )
    maturity = compute_maturity_date(product, opened_at)
    if term:
        start = timezone.localtime(opened_at).date() if timezone.is_aware(opened_at) else opened_at.date()
        from .policy import _add_months

        maturity = _add_months(start, term)
    walk_in_row = None
    if walk_in:
        walk_in_row = models.SavingsWalkIn.objects.create(
            first_name=(walk_in.get("first_name") or "").strip(),
            middle_name=(walk_in.get("middle_name") or "").strip(),
            last_name=(walk_in.get("last_name") or "").strip(),
            phone=(walk_in.get("phone") or "").strip(),
            address=(walk_in.get("address") or "").strip(),
        )
    account = models.MemberSavingsAccount(
        member=member,
        walk_in=walk_in_row,
        product=product,
        is_joint=bool(is_joint),
        balance=ZERO,
        status=models.MemberSavingsAccount.Status.ACTIVE,
        opened_at=opened_at,
        maturity_date=maturity,
        deposit_term_months=term,
        passbook_serial=serial,
        notes=notes or "",
    )
    account.save()
    for row in beneficiaries or []:
        models.SavingsBeneficiary.objects.create(
            account=account,
            member=row.get("member"),
            first_name=(row.get("first_name") or "").strip(),
            last_name=(row.get("last_name") or "").strip(),
            relationship=row.get("relationship") or models.SavingsBeneficiary.Relationship.OTHER,
        )
    if co_owners:
        models.SavingsJointOwner.objects.bulk_create(
            [
                models.SavingsJointOwner(
                    account=account,
                    member=co_owner,
                    added_at=opened_at,
                )
                for co_owner in co_owners
            ]
        )
    opening_note = notes or (
        "Joint opening deposit" if account.is_joint else "Opening deposit"
    )
    _post(
        account,
        models.SavingsTransaction.TxnType.OPENING,
        amount,
        performed_by=performed_by,
        notes=opening_note,
        posted_at=opened_at,
    )
    return account


def _transaction_posted_at(account, posted_on):
    """Aware datetime for a deposit or withdrawal date chosen by staff.

    Past dates are allowed from the enrollment calendar date through today.
    The enrollment time of day does not block that same date: a movement on
    the enrollment date is posted after the account was opened, still on that day.
    """
    if posted_on is None:
        return None
    moment = resolve_opened_at(posted_on)
    opened_at = getattr(account, "opened_at", None)
    if not opened_at:
        return moment
    if timezone.is_naive(opened_at):
        opened_at = timezone.make_aware(opened_at, timezone.get_current_timezone())
    enrolled_on = timezone.localtime(opened_at).date()
    posted_day = (
        posted_on if not isinstance(posted_on, datetime) else timezone.localtime(moment).date()
    )
    if posted_day < enrolled_on:
        raise ValidationError(
            "Date cannot be before this account was enrolled "
            f"({enrolled_on.strftime('%b %d, %Y')})."
        )
    if moment < opened_at:
        shifted = opened_at + timedelta(seconds=1)
        if timezone.localtime(shifted).date() != enrolled_on:
            return opened_at
        return shifted
    return moment


@transaction.atomic
def deposit(*, account, amount, performed_by=None, notes="", posted_on=None):
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
        posted_at=_transaction_posted_at(account, posted_on),
    )


@transaction.atomic
def withdraw(*, account, amount, performed_by=None, notes="", posted_on=None):
    account = models.MemberSavingsAccount.objects.select_for_update().select_related(
        "product"
    ).get(pk=account.pk)
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
        posted_at=_transaction_posted_at(account, posted_on),
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


def balance_at(account, moment):
    """Ledger balance at ``moment``, including that moment's transactions.

    Deposits posted after ``moment`` are not included. That is the savings
    amount used for the period's interest.
    """
    account_id = getattr(account, "pk", None)
    if not account_id or moment is None:
        return _money(getattr(account, "balance", ZERO))
    balance = (
        models.SavingsTransaction.objects.filter(
            account_id=account_id,
            created_at__lte=moment,
        )
        .order_by("-created_at", "-id")
        .values_list("balance_after", flat=True)
        .first()
    )
    if balance is None:
        return ZERO
    return _money(balance)


def deposits_between(account, start, end):
    """Deposits posted after ``start`` and on or before ``end``."""
    account_id = getattr(account, "pk", None)
    if not account_id or start is None:
        return ZERO
    qs = models.SavingsTransaction.objects.filter(
        account_id=account_id,
        transaction_type=models.SavingsTransaction.TxnType.DEPOSIT,
        created_at__gt=start,
    )
    if end is not None:
        qs = qs.filter(created_at__lte=end)
    total = qs.aggregate(total=Sum("amount"))["total"]
    return _money(total or ZERO)


def has_withdrawal_between(account, start, end):
    """True when a withdrawal was posted after ``start`` and on or before ``end``."""
    account_id = getattr(account, "pk", None)
    if not account_id or start is None or end is None:
        return False
    return models.SavingsTransaction.objects.filter(
        account_id=account_id,
        transaction_type=models.SavingsTransaction.TxnType.WITHDRAWAL,
        created_at__gt=start,
        created_at__lte=end,
    ).exists()


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
    """Latest interest row, including a ₱0 skip, so the next period can start."""
    return (
        models.SavingsTransaction.objects.filter(
            account_id=account.pk,
            transaction_type=models.SavingsTransaction.TxnType.INTEREST,
        )
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first()
    )


def interest_period_started_at(account):
    """Start of the current interest period.

    On regular savings, a withdrawal inside the open period resets the count.
    Time deposits keep the yearly date and do not restart after a withdrawal.
    """
    started = getattr(account, "opened_at", None)
    moments = [last_interest_at(account)]
    if not is_time_deposit_account(account):
        moments.append(last_withdrawal_at(account))
    for moment in moments:
        if moment and (started is None or moment > started):
            started = moment
    return started


def effective_interest_rate(account, as_of=None):
    """Annual percent from the account's savings product (admin Interest field)."""
    product = getattr(account, "product", None)
    rate = getattr(product, "interest_rate", None)
    if rate is None:
        return ANNUAL_INTEREST_RATE
    return Decimal(rate)


def is_time_deposit_account(account):
    product = getattr(account, "product", None)
    return getattr(product, "product_type", None) == models.SavingsProduct.ProductType.TIME_DEPOSIT


def interest_schedule(account):
    """How often this account's product credits interest.

    Time deposits always credit once a year (12 months). Regular savings uses
    ``interest_apply_months``, or the compounding choice when that is missing.
    """
    if is_time_deposit_account(account):
        balance = getattr(account, "balance", 0)
        if time_deposit_uses_term(balance, getattr(account, "product", None)):
            term = int(getattr(account, "deposit_term_months", 0) or 0)
            label = time_deposit_term_label(term)
            if label:
                step, periods, _phrase = schedule_for_months(term)
                return step, periods, f"every {label} (savings × term interest)"
            return (
                TIME_DEPOSIT_YEAR_MONTHS,
                Decimal("1"),
                "select 3 months, 6 months, or 1 year",
            )
        step, periods, _phrase = schedule_for_months(TIME_DEPOSIT_YEAR_MONTHS)
        return step, periods, "once a year (time deposit × interest rate)"
    product = getattr(account, "product", None)
    months = getattr(product, "interest_apply_months", None)
    if months:
        return schedule_for_months(months)
    compounding = getattr(product, "compounding", None) or "monthly"
    return compounding_schedule(compounding)


def period_interest_amount(account, principal, rate, step_months):
    """Interest for one credit. Time deposits do not use months ÷ 12."""
    if is_time_deposit_account(account):
        return time_deposit_interest_amount(
            principal,
            rate,
            term_months=getattr(account, "deposit_term_months", None),
            product=getattr(account, "product", None),
        )
    return interest_amount(principal, rate, months=step_months)


def months_of_interest_due(account, as_of=None):
    """How many compounding-period anniversaries have passed since opening / last credit."""
    as_of = as_of or timezone.now()
    cursor = interest_period_started_at(account)
    if not cursor:
        return 0
    step_months, _, _ = interest_schedule(account)
    due = 0
    nxt = next_interest_credit_on(cursor, months=step_months)
    while due < MAX_INTEREST_PERIODS and nxt is not None and as_of >= nxt:
        due += 1
        nxt = next_interest_credit_on(nxt, months=step_months)
    return due


# Backwards-compatible alias used by older call sites / tests.
years_of_interest_due = months_of_interest_due


def next_unpaid_interest_on(account, as_of=None):
    """First compounding anniversary that has not been credited yet."""
    cursor = interest_period_started_at(account)
    if not cursor:
        return None
    step_months, _, _ = interest_schedule(account)
    return next_interest_credit_on(cursor, months=step_months)


def interest_snapshot(account, as_of=None):
    """Template-ready interest status for one savings account."""
    as_of = as_of or timezone.now()
    last_wd = last_withdrawal_at(account)
    product_rate = effective_interest_rate(account, as_of=as_of)
    rate = product_rate
    term_months = getattr(account, "deposit_term_months", None)
    if is_time_deposit_account(account) and time_deposit_uses_term(
        getattr(account, "balance", 0), getattr(account, "product", None)
    ):
        term_rate = time_deposit_term_rate(term_months, getattr(account, "product", None))
        if term_rate is not None:
            rate = term_rate
    step_months, periods_per_year, schedule_phrase = interest_schedule(account)
    rate_display = format_rate(rate)
    last_credit = last_interest_at(account)
    next_credit_on = next_unpaid_interest_on(account, as_of=as_of)
    months_due = months_of_interest_due(account, as_of=as_of)
    due = bool(
        account.can_transact
        and _money(account.balance) > ZERO
        and months_due > 0
    )
    period_start = interest_period_started_at(account)
    interest_base = balance_at(account, period_start) if period_start else _money(account.balance)
    period_deposits = deposits_between(account, period_start, next_credit_on)
    is_time_deposit = is_time_deposit_account(account)
    estimated = period_interest_amount(account, interest_base, product_rate, step_months)
    if is_time_deposit:
        below_minimum = not earns_time_deposit_interest(
            interest_base, getattr(account, "product", None)
        )
    else:
        below_minimum = not earns_savings_interest(interest_base) or not earns_savings_interest(
            account.balance
        )
    if below_minimum:
        estimated = ZERO
    no_withdrawal = (
        True
        if is_time_deposit
        else not has_withdrawal_between(account, period_start, next_credit_on)
    )
    period_reset = (
        False
        if is_time_deposit
        else bool(last_wd and period_start == last_wd)
    )
    rate_factor_display = format(Decimal(rate).quantize(Decimal("0.001")), "f").rstrip("0").rstrip(".")
    # A successful period's new balance (savings + deposits in the period + interest)
    # is the savings amount for the next period's formula.
    if no_withdrawal and not below_minimum:
        next_balance = _money(account.balance) + estimated
    else:
        next_balance = _money(account.balance)
    next_period_interest = period_interest_amount(account, next_balance, product_rate, step_months)
    if is_time_deposit:
        if not earns_time_deposit_interest(next_balance, getattr(account, "product", None)):
            next_period_interest = ZERO
    elif not earns_savings_interest(next_balance):
        next_period_interest = ZERO
    return {
        "annual_rate": rate,
        "annual_rate_display": rate_display,
        "base_rate": rate,
        "loyalty_rate": rate,
        "base_rate_display": rate_display,
        "loyalty_rate_display": rate_display,
        "effective_rate": rate,
        "effective_rate_display": rate_display,
        "qualifies_loyalty": no_withdrawal,
        "no_withdrawal": no_withdrawal,
        "period_reset": period_reset,
        "below_minimum": below_minimum,
        "rate_factor_display": rate_factor_display,
        "last_withdrawal_at": last_wd,
        "loyalty_eligible_on": None,
        "last_interest_at": last_credit,
        "next_credit_on": next_credit_on,
        "years_due": months_due,
        "months_due": months_due,
        "interest_due": due,
        "estimated_interest": estimated,
        "interest_base": interest_base,
        "period_deposits": period_deposits,
        "next_balance": next_balance,
        "next_period_interest": next_period_interest,
        "schedule_phrase": schedule_phrase,
        "step_months": step_months,
        "periods_per_year": periods_per_year,
        "is_time_deposit": is_time_deposit,
        "high_amount": bool(
            is_time_deposit
            and time_deposit_uses_term(interest_base, getattr(account, "product", None))
        ),
        "deposit_term_months": term_months,
        "deposit_term_label": time_deposit_term_label(term_months),
        "needs_term": bool(
            is_time_deposit
            and time_deposit_uses_term(interest_base, getattr(account, "product", None))
            and time_deposit_term_rate(term_months, getattr(account, "product", None)) is None
        ),
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
    step_months, _periods_per_year, _schedule_phrase = interest_schedule(account)
    posted = []
    cursor = interest_period_started_at(account)
    if months_due < 1 or _money(account.balance) <= ZERO:
        next_on = (
            next_interest_credit_on(cursor, months=step_months) if cursor else None
        )
        when = (
            timezone.localtime(next_on).strftime("%b %d, %Y")
            if next_on
            else "the next anniversary after opening"
        )
        raise ValidationError(
            f"No interest is due yet. Interest at {format_rate(rate)} can be credited on {when}."
        )
    for month_n in range(1, months_due + 1):
        period_on = next_interest_credit_on(cursor, months=step_months)
        principal = balance_at(account, cursor)
        withdrew = has_withdrawal_between(account, cursor, period_on)
        if period_on is None:
            break
        when = timezone.localtime(period_on).strftime("%b %d, %Y")
        rate_text = format(Decimal(rate).quantize(Decimal("0.001")), "f").rstrip("0").rstrip(".")
        time_deposit = is_time_deposit_account(account)
        if time_deposit and not earns_time_deposit_interest(principal, account.product):
            floor = time_deposit_min_amount(account.product)
            note = (
                f"No interest for {when}. Time deposit is ₱{principal:,.2f}. "
                f"Interest starts at ₱{floor:,.2f}."
            )
            money = ZERO
        elif time_deposit and time_deposit_uses_term(principal, account.product):
            term = account.deposit_term_months
            term_rate = time_deposit_term_rate(term, account.product)
            label = time_deposit_term_label(term)
            if term_rate is None:
                break
            money = time_deposit_interest_amount(
                principal, rate, term_months=term, product=account.product
            )
            if money <= ZERO:
                break
            term_text = format(Decimal(term_rate).quantize(Decimal("0.001")), "f").rstrip("0").rstrip(".")
            if int(term or 0) in (3, 6):
                note = (
                    f"Interest ₱{money:,.2f} = ₱{principal:,.2f} × {term_text} "
                    f"× ({int(term)}/12) for {label} on {when}."
                )
            else:
                note = (
                    f"Interest ₱{money:,.2f} = ₱{principal:,.2f} × {term_text} "
                    f"for {label} on {when}."
                )
        elif time_deposit:
            money = time_deposit_interest_amount(principal, rate, product=account.product)
            if money <= ZERO:
                break
            note = (
                f"Interest ₱{money:,.2f} = ₱{principal:,.2f} × {rate_text} "
                f"for the year ({TIME_DEPOSIT_YEAR_MONTHS} months) on {when}."
            )
        elif not earns_savings_interest(principal):
            note = (
                f"No interest for {when}. Remaining balance is ₱{principal:,.2f}. "
                f"Interest is not applied at ₱{MINIMUM_BALANCE_FOR_INTEREST:,.2f} or below."
            )
            money = ZERO
        elif withdrew:
            note = (
                f"No interest for {when}. A withdrawal fell within these "
                f"{step_months} months, so the {step_months}-month count starts again "
                f"from the withdrawal."
            )
            money = ZERO
        else:
            money = interest_amount(principal, rate, months=step_months)
            if money <= ZERO:
                break
            deposits_now = deposits_between(account, cursor, period_on)
            next_base = _money(principal) + deposits_now + money
            note = (
                f"Interest ₱{money:,.2f} = ₱{principal:,.2f} × {rate_text} × "
                f"{step_months} ÷ 12 for {when}. "
                f"Deposits in this period stay in the balance and are not included. "
                f"This period succeeded, so the next period uses the new balance "
                f"₱{next_base:,.2f}."
            )
        if months_due > 1:
            label = "Month" if step_months == 1 else "Period"
            note = f"{note} {label} {month_n} of {months_due}."
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

    if not account.member_id:
        return account, payout

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
        has_later = (
            models.SavingsTransaction.objects.filter(account_id=account.pk)
            .exclude(pk=txn.pk)
            .filter(created_at__gte=txn.created_at)
            .exists()
        )
        if has_later:
            _rebuild_running_balances(account, focus=txn)
            txn.refresh_from_db()
            account.refresh_from_db()
    return txn


def _rebuild_running_balances(account, focus=None):
    """Rewrite balance columns in ledger order after a backdated movement.

    A past deposit or withdrawal sits between older rows. Later rows keep
    their amounts and shift so ``balance_after`` stays the true balance on
    each date. Interest reads that column, so the chain has to stay honest.
    """
    txns = list(
        models.SavingsTransaction.objects.filter(account_id=account.pk).order_by(
            "created_at", "id"
        )
    )
    product = account.product
    min_bal = _money(getattr(product, "min_maintaining_balance", ZERO) or ZERO)
    max_bal = _money(getattr(product, "max_balance", ZERO) or ZERO)
    focus_id = getattr(focus, "pk", None)
    focus_at = getattr(focus, "created_at", None)
    focus_is_credit = bool(focus and focus.is_credit)
    running = ZERO
    for txn in txns:
        before = running
        signed = txn.amount if txn.is_credit else -txn.amount
        after = _money(before + signed)
        follows_focus = False
        if focus_id and focus_at:
            follows_focus = (
                txn.pk == focus_id
                or txn.created_at > focus_at
                or (txn.created_at == focus_at and str(txn.pk) > str(focus_id))
            )
        if after < ZERO:
            raise ValidationError(
                "That date would make the ledger balance negative. "
                "Choose a later date or a smaller amount."
            )
        if (
            follows_focus
            and txn.transaction_type == models.SavingsTransaction.TxnType.WITHDRAWAL
            and after < min_bal
        ):
            raise ValidationError(
                f"Balance after withdrawal would be ₱{after:,.2f} on "
                f"{timezone.localtime(txn.created_at).date().strftime('%b %d, %Y')}, "
                f"below the minimum of ₱{min_bal:,.2f}."
            )
        if follows_focus and focus_is_credit and max_bal > ZERO and after > max_bal:
            raise ValidationError(
                f"Balance would be ₱{after:,.2f} on "
                f"{timezone.localtime(txn.created_at).date().strftime('%b %d, %Y')}, "
                f"above the maximum of ₱{max_bal:,.2f}."
            )
        if txn.balance_before != before or txn.balance_after != after:
            models.SavingsTransaction.objects.filter(pk=txn.pk).update(
                balance_before=before,
                balance_after=after,
            )
        running = after
    if account.balance != running:
        account.balance = running
        account.save(update_fields=["balance", "updated_at"])
