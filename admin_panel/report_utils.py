"""Shared date bounds and sale filters for Generate Report (PDF / Excel / email).

Keeps report totals aligned with the dashboard:
  - sale statuses: completed + partially_refunded
  - period bounds: store-local [start, end) datetimes
  - exclude dummy seed transactions
  - product lines: non-refunded items only
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.db.models import QuerySet
from django.utils import timezone

# Match dashboard DASHBOARD_SALE_STATUSES (header total_amount is net of refunded lines).
REPORT_SALE_STATUSES = ('completed', 'partially_refunded')


def report_period_bounds(date_from, date_to=None):
    """
    Convert inclusive calendar dates to aware [start, end) datetimes in the store TZ.

    Same convention as the dashboard period filters.
    """
    if date_to is None:
        date_to = date_from
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(
        datetime(date_from.year, date_from.month, date_from.day, 0, 0, 0),
        tz,
    )
    end_day = date_to + timedelta(days=1)
    end = timezone.make_aware(
        datetime(end_day.year, end_day.month, end_day.day, 0, 0, 0),
        tz,
    )
    return start, end


def get_report_transactions(
    date_from,
    date_to=None,
    sale_statuses=REPORT_SALE_STATUSES,
) -> QuerySet:
    """Sale transactions for the report period (excludes dummy seed sales)."""
    from transactions.models import Transaction

    start, end = report_period_bounds(date_from, date_to)
    return (
        Transaction.objects.filter(
            status__in=sale_statuses,
            created_at__gte=start,
            created_at__lt=end,
        ).exclude(transaction_number__startswith='DUMMY-')
    )


def get_report_sale_items(
    date_from,
    date_to=None,
    sale_statuses=REPORT_SALE_STATUSES,
) -> QuerySet:
    """Non-refunded line items for sales in the report period."""
    from transactions.models import TransactionItem

    txn_ids = get_report_transactions(date_from, date_to, sale_statuses).values_list(
        'id', flat=True
    )
    return TransactionItem.objects.filter(
        transaction_id__in=txn_ids,
        refunded_at__isnull=True,
    )
