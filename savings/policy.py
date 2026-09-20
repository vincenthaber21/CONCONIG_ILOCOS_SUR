"""Fixed Regular Savings interest policy for every member account.

Annual rate is a flat 5%. Interest is credited monthly on the anniversary
of the account opening date (same calendar day each month):

    interest_per_month = (balance * 0.05) / 12
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


def next_interest_credit_on(after):
    """Next monthly credit date: one calendar month after ``after``."""
    local_day = _as_local_date(after)
    if local_day is None:
        return None
    return interest_credit_datetime(_add_months(local_day, 1))


def interest_amount(balance, rate):
    """Monthly interest: (balance * rate% / 100) / 12.

    Example: 5000 at 5% → (5000 * 0.05) / 12 = 20.83
    """
    annual = Decimal(balance) * Decimal(rate) / HUNDRED
    return (annual / MONTHS_PER_YEAR).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def regular_savings_policy():
    display = format_rate(ANNUAL_INTEREST_RATE)
    return {
        "annual_rate": ANNUAL_INTEREST_RATE,
        "annual_rate_display": display,
        "base_rate": ANNUAL_INTEREST_RATE,
        "loyalty_rate": ANNUAL_INTEREST_RATE,
        "base_rate_display": display,
        "loyalty_rate_display": display,
        "compounding": "monthly",
    }
