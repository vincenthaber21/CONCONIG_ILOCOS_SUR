"""Walk-in customer sections for PDF and Excel daily reports."""

from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

PDF_TOP_CUSTOMERS_LIMIT = 10


def walk_in_excel_metric_rows(summary):
    """Rows for the Walk-in Summary Excel sheet."""
    return [
        ['Total Registered (all time)', summary['total_registered']],
        ['New Customers in Period', summary['new_in_period']],
        ['Walk-in Transactions', summary['period_txn_count']],
        ['Walk-in Revenue', summary['period_revenue']],
    ]


def walk_in_excel_customer_rows(summary):
    """Rows for the Walk-in Customers Excel sheet."""
    return [
        [
            idx,
            c['display_name'],
            c['txn_count'],
            c['revenue'],
            c['last_seen_at'],
        ]
        for idx, c in enumerate(summary.get('top_customers') or [], start=1)
    ]


def append_walk_in_summary_pdf(
    elements,
    summary,
    *,
    heading_style,
    styles,
    currency_symbol,
    header_color,
    header_dark_color,
    row_alt_color,
    period_label='this period',
):
    """Append walk-in customers summary tables to a ReportLab elements list."""
    elements.append(Paragraph('Walk-in Customers Summary', heading_style))

    metrics_data = [
        ['Metric', 'Value'],
        ['Total Registered (all time)', f"{summary['total_registered']:,}"],
        ['New Customers in Period', f"{summary['new_in_period']:,}"],
        ['Walk-in Transactions', f"{summary['period_txn_count']:,}"],
        ['Walk-in Revenue', f"{currency_symbol}{summary['period_revenue']:,.2f}"],
    ]
    metrics_table = Table(metrics_data, colWidths=[3 * inch, 2 * inch])
    metrics_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), header_color),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), row_alt_color),
        ('GRID', (0, 0), (-1, -1), 1, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, row_alt_color]),
    ]))
    elements.append(metrics_table)
    elements.append(Spacer(1, 0.15 * inch))

    top_customers = (summary.get('top_customers') or [])[:PDF_TOP_CUSTOMERS_LIMIT]
    if top_customers:
        elements.append(Paragraph('Top Walk-in Customers', heading_style))
        customer_data = [['#', 'Customer Name', 'Orders', 'Revenue', 'Last Visit']]
        for idx, customer in enumerate(top_customers, start=1):
            customer_data.append([
                str(idx),
                customer['display_name'][:30],
                f"{customer['txn_count']:,}",
                f"{currency_symbol}{customer['revenue']:,.2f}",
                customer['last_seen_at'],
            ])
        totals_idx = len(customer_data)
        total_orders = sum(c['txn_count'] for c in top_customers)
        total_revenue = sum(c['revenue'] for c in top_customers)
        customer_data.append([
            '', 'TOTAL (listed)', f"{total_orders:,}",
            f"{currency_symbol}{total_revenue:,.2f}", '',
        ])
        customer_table = Table(
            customer_data,
            colWidths=[0.35 * inch, 2.0 * inch, 0.75 * inch, 1.15 * inch, 1.25 * inch],
            repeatRows=1,
        )
        customer_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), header_color),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
            ('ALIGN', (4, 1), (4, totals_idx - 1), 'CENTER'),
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
        elements.append(customer_table)
    else:
        elements.append(
            Paragraph(f'No walk-in customer sales recorded for {period_label}.', styles['Normal'])
        )

    elements.append(Spacer(1, 0.2 * inch))
