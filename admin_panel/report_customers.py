"""Top customers sections for PDF and Excel daily reports."""

from django.db.models import Count, Max, Sum
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import KeepTogether, Paragraph, Spacer, Table, TableStyle

from admin_panel.report_utils import REPORT_SALE_STATUSES, get_report_transactions

TOP_CUSTOMERS_LIMIT = 10


def get_top_customers_for_period(
    date_from,
    date_to=None,
    limit=TOP_CUSTOMERS_LIMIT,
    sale_statuses=REPORT_SALE_STATUSES,
):
    """
    Rank customers by revenue for a report period (members, walk-ins, and guests).
    """
    from members.models import Member
    from transactions.models import WalkInCustomer

    if date_to is None:
        date_to = date_from

    current_tz = timezone.get_current_timezone()
    txn_qs = get_report_transactions(date_from, date_to, sale_statuses)

    buckets = {}

    def _bucket(key, display_name, customer_type):
        if key not in buckets:
            buckets[key] = {
                'display_name': display_name,
                'customer_type': customer_type,
                'txn_count': 0,
                'revenue': 0.0,
                'last_seen_at': None,
            }
        return buckets[key]

    member_rows = list(
        txn_qs.filter(member__isnull=False)
        .values('member_id')
        .annotate(
            txn_count=Count('id'),
            revenue=Sum('total_amount'),
            last_seen=Max('created_at'),
        )
    )
    if member_rows:
        member_names = {
            m.id: m.full_name
            for m in Member.objects.filter(
                id__in=[row['member_id'] for row in member_rows]
            )
        }
        for row in member_rows:
            mid = row['member_id']
            bucket = _bucket(f'm:{mid}', member_names.get(mid, 'Member'), 'Member')
            bucket['txn_count'] += row['txn_count'] or 0
            bucket['revenue'] += float(row['revenue'] or 0)
            last_seen = row['last_seen']
            if last_seen and (
                bucket['last_seen_at'] is None or last_seen > bucket['last_seen_at']
            ):
                bucket['last_seen_at'] = last_seen

    walkin_rows = list(
        txn_qs.filter(walk_in_customer__isnull=False)
        .values('walk_in_customer_id')
        .annotate(
            txn_count=Count('id'),
            revenue=Sum('total_amount'),
            last_seen=Max('created_at'),
        )
    )
    if walkin_rows:
        walkin_names = {
            c['id']: c['display_name']
            for c in WalkInCustomer.objects.filter(
                id__in=[row['walk_in_customer_id'] for row in walkin_rows]
            ).values('id', 'display_name')
        }
        for row in walkin_rows:
            wid = row['walk_in_customer_id']
            bucket = _bucket(
                f'w:{wid}',
                walkin_names.get(wid, 'Walk-in Customer'),
                'Walk-in',
            )
            bucket['txn_count'] += row['txn_count'] or 0
            bucket['revenue'] += float(row['revenue'] or 0)
            last_seen = row['last_seen']
            if last_seen and (
                bucket['last_seen_at'] is None or last_seen > bucket['last_seen_at']
            ):
                bucket['last_seen_at'] = last_seen

    guest_rows = list(
        txn_qs.filter(
            member__isnull=True,
            walk_in_customer__isnull=True,
        )
        .exclude(guest_customer_name='')
        .values('guest_customer_name')
        .annotate(
            txn_count=Count('id'),
            revenue=Sum('total_amount'),
            last_seen=Max('created_at'),
        )
    )
    for row in guest_rows:
        name = (row['guest_customer_name'] or '').strip() or 'Walk-in'
        key = f"g:{name.casefold()}"
        bucket = _bucket(key, name, 'Walk-in')
        bucket['txn_count'] += row['txn_count'] or 0
        bucket['revenue'] += float(row['revenue'] or 0)
        last_seen = row['last_seen']
        if last_seen and (
            bucket['last_seen_at'] is None or last_seen > bucket['last_seen_at']
        ):
            bucket['last_seen_at'] = last_seen

    anon_stats = txn_qs.filter(
        member__isnull=True,
        walk_in_customer__isnull=True,
        guest_customer_name='',
    ).aggregate(
        txn_count=Count('id'),
        revenue=Sum('total_amount'),
        last_seen=Max('created_at'),
    )
    if anon_stats['txn_count']:
        bucket = _bucket('guest', 'Guest', 'Guest')
        bucket['txn_count'] += anon_stats['txn_count'] or 0
        bucket['revenue'] += float(anon_stats['revenue'] or 0)
        bucket['last_seen_at'] = anon_stats['last_seen']

    ranked = sorted(
        buckets.values(),
        key=lambda item: (-item['revenue'], item['display_name'].lower()),
    )
    if limit is not None:
        ranked = ranked[:limit]

    for customer in ranked:
        last_seen = customer.pop('last_seen_at', None)
        customer['last_seen_at'] = (
            timezone.localtime(last_seen, current_tz).strftime('%b %d, %Y %H:%M')
            if last_seen
            else ''
        )
        customer['revenue'] = round(customer['revenue'], 2)

    return ranked


def top_customers_excel_rows(customers):
    """Rows for the Top Customers Excel sheet."""
    return [
        [
            idx,
            c['display_name'],
            c['customer_type'],
            c['txn_count'],
            c['revenue'],
            c['last_seen_at'],
        ]
        for idx, c in enumerate(customers or [], start=1)
    ]


def append_top_customers_pdf(
    elements,
    customers,
    *,
    heading_style,
    styles,
    currency_symbol,
    header_color,
    header_dark_color,
    row_alt_color,
    period_label='this period',
    limit=TOP_CUSTOMERS_LIMIT,
):
    """Append top customers table to a ReportLab elements list."""
    top_customers = (customers or [])[:limit]
    heading = Paragraph('Top 10 Customers', heading_style)

    if not top_customers:
        elements.append(KeepTogether([
            heading,
            Paragraph(f'No customer sales recorded for {period_label}.', styles['Normal']),
        ]))
        elements.append(Spacer(1, 0.2 * inch))
        return

    customer_data = [['#', 'Customer Name', 'Type', 'Orders', 'Revenue', 'Last Visit']]
    for idx, customer in enumerate(top_customers, start=1):
        customer_data.append([
            str(idx),
            customer['display_name'][:28],
            customer['customer_type'],
            f"{customer['txn_count']:,}",
            f"{currency_symbol}{customer['revenue']:,.2f}",
            customer['last_seen_at'],
        ])

    totals_idx = len(customer_data)
    total_orders = sum(c['txn_count'] for c in top_customers)
    total_revenue = sum(c['revenue'] for c in top_customers)
    customer_data.append([
        '', 'TOTAL (listed)', '', f"{total_orders:,}",
        f"{currency_symbol}{total_revenue:,.2f}", '',
    ])

    customer_table = Table(
        customer_data,
        colWidths=[0.35 * inch, 1.75 * inch, 0.85 * inch, 0.7 * inch, 1.1 * inch, 1.05 * inch],
        repeatRows=1,
    )
    customer_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), header_color),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (0, -1), 'CENTER'),
        ('ALIGN', (1, 0), (2, -1), 'LEFT'),
        ('ALIGN', (3, 0), (-1, -1), 'RIGHT'),
        ('ALIGN', (5, 1), (5, totals_idx - 1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('FONTSIZE', (0, 1), (-1, totals_idx - 1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('ROWBACKGROUNDS', (0, 1), (-1, totals_idx - 1), [colors.white, row_alt_color]),
        ('BACKGROUND', (0, totals_idx), (-1, totals_idx), header_dark_color),
        ('TEXTCOLOR', (0, totals_idx), (-1, totals_idx), colors.whitesmoke),
        ('FONTNAME', (0, totals_idx), (-1, totals_idx), 'Helvetica-Bold'),
        ('LINEABOVE', (0, totals_idx), (-1, totals_idx), 1.5, header_dark_color),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    elements.append(KeepTogether([heading, customer_table]))
    elements.append(Spacer(1, 0.2 * inch))
