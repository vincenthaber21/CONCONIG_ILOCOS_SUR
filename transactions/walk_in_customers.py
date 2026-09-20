"""Walk-in / kiosk customer name registry (non-member buyers)."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone

from admin_panel.report_utils import REPORT_SALE_STATUSES, report_period_bounds

# Re-export for report helpers; completed + partially_refunded (net of refunded lines).
DEFAULT_REPORT_SALE_STATUSES = REPORT_SALE_STATUSES


def normalize_customer_name(name: str) -> str:
    return " ".join((name or "").split()).strip().casefold()


def is_operator_default_customer_name(entered: str, operator_default: str) -> bool:
    entered_n = normalize_customer_name(entered)
    default_n = normalize_customer_name(operator_default)
    if not entered_n or not default_n:
        return False
    return entered_n == default_n


def register_walk_in_customer(name: str):
    """
    Create or update a walk-in customer record. Returns the model instance or None.
    """
    from .models import WalkInCustomer

    display = " ".join((name or "").split()).strip()
    if len(display) < 2:
        return None

    name_key = normalize_customer_name(display)
    now = timezone.now()
    obj, created = WalkInCustomer.objects.get_or_create(
        name_key=name_key,
        defaults={
            "display_name": display[:200],
            "last_seen_at": now,
        },
    )
    if not created:
        update_fields = ["last_seen_at", "updated_at"]
        if obj.display_name != display[:200]:
            obj.display_name = display[:200]
            update_fields.append("display_name")
        obj.last_seen_at = now
        obj.save(update_fields=update_fields)
    return obj


def sync_walk_in_customer_discounts(walk_in_customer):
    """
    Rebuild per-product manual discount totals from completed transaction line items.
  """
    from .models import TransactionItem, WalkInCustomerProductDiscount

    if not walk_in_customer:
        return

    items = (
        TransactionItem.objects.filter(
            transaction__walk_in_customer=walk_in_customer,
            transaction__status__in=DEFAULT_REPORT_SALE_STATUSES,
            refunded_at__isnull=True,
            manual_discount_php__gt=0,
        )
        .exclude(transaction__transaction_number__startswith='DUMMY-')
        .select_related('transaction', 'product')
        .order_by('transaction__created_at')
    )

    buckets = defaultdict(
        lambda: {
            'product_id': None,
            'product_name': '',
            'total': Decimal('0.00'),
            'line_count': 0,
            'last_sale_at': None,
        }
    )
    for item in items:
        name = (item.product_name or '').strip() or '—'
        key = name.casefold()
        bucket = buckets[key]
        bucket['product_name'] = name
        if item.product_id and not bucket['product_id']:
            bucket['product_id'] = item.product_id
        disc = Decimal(str(item.manual_discount_php or 0)).quantize(Decimal('0.01'))
        bucket['total'] += disc
        bucket['line_count'] += 1
        sale_at = item.transaction.created_at
        if bucket['last_sale_at'] is None or sale_at > bucket['last_sale_at']:
            bucket['last_sale_at'] = sale_at

    WalkInCustomerProductDiscount.objects.filter(walk_in_customer=walk_in_customer).delete()

    grand_total = Decimal('0.00')
    for bucket in buckets.values():
        total = bucket['total'].quantize(Decimal('0.01'))
        grand_total += total
        WalkInCustomerProductDiscount.objects.create(
            walk_in_customer=walk_in_customer,
            product_id=bucket['product_id'],
            product_name=bucket['product_name'],
            total_manual_discount_php=total,
            line_count=bucket['line_count'],
            last_sale_at=bucket['last_sale_at'],
        )

    walk_in_customer.total_manual_discount_php = grand_total.quantize(Decimal('0.01'))
    walk_in_customer.save(update_fields=['total_manual_discount_php', 'updated_at'])


def get_walk_in_summary_for_period(
    date_from,
    date_to=None,
    sale_statuses=DEFAULT_REPORT_SALE_STATUSES,
    top_limit=10,
):
    """
    Walk-in customer metrics for daily / range reports (PDF, Excel, email).
    Matches dashboard walk-in insights but scoped to report date filters.
    """
    from .models import Transaction, WalkInCustomer

    if date_to is None:
        date_to = date_from

    start_datetime, end_datetime = report_period_bounds(date_from, date_to)

    txn_qs = Transaction.objects.filter(
        status__in=sale_statuses,
        created_at__gte=start_datetime,
        created_at__lt=end_datetime,
    ).exclude(transaction_number__startswith='DUMMY-')

    walk_in_filter = Q(member__isnull=True) & (
        Q(walk_in_customer__isnull=False) | ~Q(guest_customer_name='')
    )
    period_walk_in_txns = txn_qs.filter(walk_in_filter)
    period_stats = period_walk_in_txns.aggregate(
        txn_count=Count('id'),
        revenue=Sum('total_amount'),
        revenue_subtotal=Sum('subtotal'),
    )
    period_revenue = float(period_stats['revenue'] or 0)
    if period_revenue == 0:
        period_revenue = float(period_stats['revenue_subtotal'] or 0)

    txn_period_filter = Q(
        transactions__status__in=sale_statuses,
        transactions__created_at__gte=start_datetime,
        transactions__created_at__lt=end_datetime,
        transactions__member__isnull=True,
    ) & ~Q(transactions__transaction_number__startswith='DUMMY-')
    top_customers_qs = (
        WalkInCustomer.objects.annotate(
            period_txn_count=Count('transactions', filter=txn_period_filter),
            period_revenue=Sum('transactions__total_amount', filter=txn_period_filter),
            period_revenue_subtotal=Sum('transactions__subtotal', filter=txn_period_filter),
        )
        .filter(period_txn_count__gt=0)
        .order_by('-period_revenue', '-period_revenue_subtotal', 'display_name')
    )
    if top_limit is not None:
        top_customers_qs = top_customers_qs[:top_limit]

    current_tz = timezone.get_current_timezone()
    top_customers = []
    for c in top_customers_qs:
        rev = float(c.period_revenue or 0)
        if rev == 0:
            rev = float(c.period_revenue_subtotal or 0)
        top_customers.append(
            {
                'display_name': c.display_name,
                'txn_count': c.period_txn_count,
                'revenue': round(rev, 2),
                'last_seen_at': timezone.localtime(c.last_seen_at, current_tz).strftime('%b %d, %Y'),
            }
        )

    return {
        'total_registered': WalkInCustomer.objects.count(),
        'new_in_period': WalkInCustomer.objects.filter(
            created_at__gte=start_datetime,
            created_at__lt=end_datetime,
        ).count(),
        'period_txn_count': period_stats['txn_count'] or 0,
        'period_revenue': round(period_revenue, 2),
        'top_customers': top_customers,
    }
