"""Savings interest helpers.

Each account uses its savings product's annual rate and compounding.
Interest is credited on the opening anniversary for that schedule:

    period_interest = (balance * annual_rate%) / periods_per_year

``ANNUAL_INTEREST_RATE`` is only the fallback when a product has no rate.
"""

import calendar
from datetime import date, datetime, time
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

ANNUAL_INTEREST_RATE = Decimal("5.000")
# Aliases kept for existing imports / product defaults.
BASE_INTEREST_RATE = ANNUAL_INTEREST_RATE
LOYALTY_INTEREST_RATE = ANNUAL_INTEREST_RATE
TWO_PLACES = Decimal("0.01")
HUNDRED = Decimal("100")
MONTHS_PER_YEAR = Decimal("12")
MAX_INTEREST_PERIODS = 120
# Interest is not credited when the remaining savings are at or below this amount.
MINIMUM_BALANCE_FOR_INTEREST = Decimal("1000.00")


def format_rate(rate):
    quantized = Decimal(rate).quantize(Decimal("0.001"))
    text = format(quantized, "f").rstrip("0").rstrip(".")
    return f"{text}%"


def add_calendar_years(dt, years=1):
    if dt is None:
        return None
    base = timezone.localtime(dt) if timezone.is_aware(dt) else dt
    year = base.year + int(years)
    try:
        return base.replace(year=year)
    except ValueError:
        # 29 Feb → 28 Feb on non-leap years
        return base.replace(year=year, month=2, day=28)


def _as_local_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            return timezone.localtime(value).date()
        return value.date()
    if isinstance(value, date):
        return value
    return timezone.localtime(value).date()


def _add_months(day, months=1):
    """Same day-of-month, ``months`` later (clamped to the target month's length)."""
    month_index = day.year * 12 + (day.month - 1) + int(months)
    year, month0 = divmod(month_index, 12)
    month = month0 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last_day))


def interest_credit_datetime(day):
    """Aware datetime for a monthly interest credit date (local midnight)."""
    local_day = _as_local_date(day)
    naive = datetime.combine(local_day, time.min)
    return timezone.make_aware(naive, timezone.get_current_timezone())


# Months between credits, and how many credits make one year.
COMPOUNDING_SCHEDULE = {
    "none": (12, 1),
    "monthly": (1, 12),
    "quarterly": (3, 4),
    "annually": (12, 1),
}

COMPOUNDING_PHRASE = {
    "none": "annually on the opening anniversary (simple)",
    "monthly": "monthly on the opening anniversary",
    "quarterly": "quarterly on the opening anniversary",
    "annually": "annually on the opening anniversary",
}


def compounding_schedule(compounding):
    """Return ``(step_months, periods_per_year, phrase)`` for a product compounding value."""
    key = compounding or "monthly"
    step_months, periods = COMPOUNDING_SCHEDULE.get(key, COMPOUNDING_SCHEDULE["monthly"])
    phrase = COMPOUNDING_PHRASE.get(key, COMPOUNDING_PHRASE["monthly"])
    return step_months, periods, phrase


def schedule_for_months(months):
    """Interest credit every ``months`` months. Amount is annual rate × months / 12."""
    step = int(months or 12)
    if step < 1:
        step = 1
    periods = Decimal(12) / Decimal(step)
    if step == 1:
        phrase = "monthly on the opening anniversary"
    elif step == 3:
        phrase = "quarterly on the opening anniversary"
    elif step == 12:
        phrase = "annually on the opening anniversary"
    else:
        phrase = f"every {step} months on the opening anniversary"
    return step, periods, phrase


def next_interest_credit_on(after, months=1):
    """Next credit date: ``months`` calendar months after ``after``."""
    local_day = _as_local_date(after)
    if local_day is None:
        return None
    return interest_credit_datetime(_add_months(local_day, months))


def earns_savings_interest(balance):
    """False when remaining savings are ₱1,000.00 or below."""
    return Decimal(balance or 0) > MINIMUM_BALANCE_FOR_INTEREST


# Time deposit: not the regular savings months ÷ 12 formula.
TIME_DEPOSIT_YEAR_MONTHS = 12
TIME_DEPOSIT_MIN_BALANCE = Decimal("5000.00")
TIME_DEPOSIT_HIGH_BALANCE = Decimal("100001.00")
TIME_DEPOSIT_RATE_3_MONTHS = Decimal("0.010")
TIME_DEPOSIT_RATE_6_MONTHS = Decimal("0.010")
TIME_DEPOSIT_RATE_1_YEAR = Decimal("0.030")
TIME_DEPOSIT_TERM_MONTHS = (3, 6, 12)


def time_deposit_min_amount(product=None):
    """Lowest amount that earns time-deposit interest."""
    stored = getattr(product, "min_amount", None) if product is not None else None
    if stored is None:
        return TIME_DEPOSIT_MIN_BALANCE
    return Decimal(stored)


def time_deposit_max_amount(product=None):
    """Highest amount that uses savings × interest rate.

    Above this amount the member selects a term. When the product has no
    maximum saved, the split stays at ₱100,000 so ₱100,001 still uses a term.
    """
    stored = getattr(product, "max_amount", None) if product is not None else None
    if stored is None:
        return TIME_DEPOSIT_HIGH_BALANCE - Decimal("0.01")
    return Decimal(stored)


def earns_time_deposit_interest(balance, product=None):
    """True when the time deposit is at least the product minimum amount."""
    return Decimal(balance or 0) >= time_deposit_min_amount(product)


def time_deposit_uses_term(balance, product=None):
    """True above the product maximum amount (default: ₱100,001.00 and up)."""
    return Decimal(balance or 0) > time_deposit_max_amount(product)


def time_deposit_term_rate(term_months, product=None):
    """Rate for the term the member selected. 3 months, 6 months, or 1 year."""
    try:
        term = int(term_months or 0)
    except (TypeError, ValueError):
        return None
    fields = {
        3: ("rate_3_months", TIME_DEPOSIT_RATE_3_MONTHS),
        6: ("rate_6_months", TIME_DEPOSIT_RATE_6_MONTHS),
        12: ("rate_1_year", TIME_DEPOSIT_RATE_1_YEAR),
    }
    pair = fields.get(term)
    if pair is None:
        return None
    attr, fallback = pair
    stored = getattr(product, attr, None) if product is not None else None
    if stored is None:
        return fallback
    return Decimal(stored)


def time_deposit_term_label(term_months):
    return {3: "3 months", 6: "6 months", 12: "1 year"}.get(int(term_months or 0), "")


def time_deposit_interest_amount(balance, rate, term_months=None, product=None):
    """Time deposit interest. Regular savings (× months ÷ 12) is not used.

    ₱5,000 up to ₱100,000: savings × interest rate.
    ₱100,001 and above, for the term the member selected:
    3 months = savings × 0.01 × (3/12)
    6 months = savings × 0.01 × (6/12)
    1 year = savings × 0.03
    """
    amount = Decimal(balance or 0)
    if time_deposit_uses_term(amount, product):
        term_rate = time_deposit_term_rate(term_months, product)
        if term_rate is None:
            return Decimal("0.00")
        try:
            term = int(term_months or 0)
        except (TypeError, ValueError):
            return Decimal("0.00")
        if term in (3, 6):
            interest = amount * term_rate * Decimal(term) / MONTHS_PER_YEAR
        else:
            interest = amount * term_rate
    elif time_deposit_min_amount(product) <= amount <= time_deposit_max_amount(product):
        interest = amount * Decimal(rate)
    else:
        return Decimal("0.00")
    return interest.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def interest_amount(balance, rate, periods_per_year=12, months=None):
    """Interest for one period: savings × interest × (months ÷ 12).

    ``rate`` is the product figure used as a multiplier (not percent ÷ 100).
    Example: 2000 at 0.07 every 3 months → 2000 × 0.07 × 3 ÷ 12 = 35.00
    """
    if months is None:
        periods = Decimal(periods_per_year or 12)
        if periods <= 0:
            periods = MONTHS_PER_YEAR
        months = MONTHS_PER_YEAR / periods
    amount = Decimal(balance) * Decimal(rate) * Decimal(months) / MONTHS_PER_YEAR
    return amount.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def regular_interest_help(rate, months, savings=Decimal("2000.00")):
    """Example line for the regular-savings form, using the product's admin rate."""
    months = int(months or 12)
    if months < 1:
        months = 1
    rate = Decimal(rate if rate is not None else ANNUAL_INTEREST_RATE)
    amount = interest_amount(savings, rate, months=months)
    rate_text = format(rate.quantize(Decimal("0.001")), "f").rstrip("0").rstrip(".") or "0"
    return (
        "Interest = savings × rate × these months ÷ 12, and only if the member "
        "made no withdrawal during that period. "
        f"Example: ₱{savings:,.2f} × {rate_text} × {months} ÷ 12 = ₱{amount:,.2f}."
    )


def _active_regular_product():
    try:
        from .models import SavingsProduct

        return (
            SavingsProduct.objects.filter(
                is_active=True,
                product_type=SavingsProduct.ProductType.REGULAR,
            )
            .order_by("created_at")
            .first()
        )
    except Exception:
        return None


def regular_savings_policy(product=None):
    """Display policy for the active Regular Savings product, or the 5% fallback."""
    rate = ANNUAL_INTEREST_RATE
    compounding = "monthly"
    apply_months = 12
    if product is None:
        product = _active_regular_product()
    if product is not None:
        product_rate = getattr(product, "interest_rate", None)
        if product_rate is not None:
            rate = Decimal(product_rate)
        compounding = getattr(product, "compounding", None) or compounding
        stored_months = getattr(product, "interest_apply_months", None)
        if stored_months:
            apply_months = int(stored_months)
    _, _, phrase = schedule_for_months(apply_months)
    display = format_rate(rate)
    return {
        "annual_rate": rate,
        "annual_rate_display": display,
        "base_rate": rate,
        "loyalty_rate": rate,
        "base_rate_display": display,
        "loyalty_rate_display": display,
        "compounding": compounding,
        "interest_apply_months": apply_months,
        "schedule_phrase": phrase,
    }
