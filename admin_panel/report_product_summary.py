"""Product sales summary for Generate Report (PDF / Excel).

Columns: Product | Selling Price | Qty Sold | Subtotal
  subtotal = Sum(total_price) from non-refunded DB line items
  selling_price = effective average (subtotal / qty) so price × qty matches subtotal
"""

from __future__ import annotations

from decimal import Decimal
from typing import TypedDict

from django.db.models import Sum
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import KeepTogether, Paragraph, Spacer, Table, TableStyle

from admin_panel.report_utils import REPORT_SALE_STATUSES, get_report_sale_items


class ProductSalesSummaryRow(TypedDict):
    """One line in the product sales summary report."""

    product: str
    selling_price: Decimal
    qty_sold: int
    subtotal: Decimal


class ProductSalesSummary(TypedDict):
    products: list[ProductSalesSummaryRow]
    total_qty_sold: int
    total_subtotal: Decimal


def get_product_sales_summary_for_period(
    date_from,
    date_to=None,
    sale_statuses=REPORT_SALE_STATUSES,
) -> ProductSalesSummary:
    """
    Build product sales summary rows from actual DB line totals.

    Uses non-refunded TransactionItem.total_price sums (not Max(unit_price) × qty).
    """
    if date_to is None:
        date_to = date_from

    rows = (
        get_report_sale_items(date_from, date_to, sale_statuses)
        .values('product_name', 'product_barcode')
        .annotate(
            qty_sold=Sum('quantity'),
            subtotal=Sum('total_price'),
        )
        .order_by('-qty_sold', 'product_name')
    )

    products: list[ProductSalesSummaryRow] = []
    total_qty_sold = 0
    total_subtotal = Decimal('0.00')

    for row in rows:
        qty = int(row['qty_sold'] or 0)
        subtotal = Decimal(str(row['subtotal'] or 0)).quantize(Decimal('0.01'))
        if qty > 0:
            selling_price = (subtotal / Decimal(qty)).quantize(Decimal('0.01'))
        else:
            selling_price = Decimal('0.00')
        products.append({
            'product': row['product_name'] or '',
            'selling_price': selling_price,
            'qty_sold': qty,
            'subtotal': subtotal,
        })
        total_qty_sold += qty
        total_subtotal += subtotal

    return {
        'products': products,
        'total_qty_sold': total_qty_sold,
        'total_subtotal': total_subtotal.quantize(Decimal('0.01')),
    }


def product_sales_summary_excel_rows(summary: ProductSalesSummary):
    """Rows for the Product Sales Summary Excel sheet."""
    return [
        [
            idx,
            p['product'],
            float(p['selling_price']),
            p['qty_sold'],
            float(p['subtotal']),
        ]
        for idx, p in enumerate(summary.get('products') or [], start=1)
    ]


def append_product_sales_summary_pdf(
    elements,
    summary: ProductSalesSummary,
    *,
    heading_style,
    styles,
    currency_symbol,
    header_color,
    header_dark_color,
    row_alt_color,
    period_label='this period',
):
    """Append Product Sales Summary table to a ReportLab elements list."""
    heading = Paragraph('Product Sales Summary', heading_style)
    products = summary.get('products') or []
    if not products:
        # Keep title with empty-state text so it is not left alone on a page.
        elements.append(KeepTogether([
            heading,
            Paragraph(f'No product sales recorded for {period_label}.', styles['Normal']),
        ]))
        elements.append(Spacer(1, 0.2 * inch))
        return

    table_data = [['#', 'Product', 'Selling Price', 'Qty Sold', 'Subtotal']]
    for idx, product in enumerate(products, start=1):
        table_data.append([
            str(idx),
            product['product'][:40],
            f"{currency_symbol}{float(product['selling_price']):,.2f}",
            f"{product['qty_sold']:,}",
            f"{currency_symbol}{float(product['subtotal']):,.2f}",
        ])

    totals_idx = len(table_data)
    table_data.append([
        '',
        'TOTAL',
        '',
        f"{summary['total_qty_sold']:,}",
        f"{currency_symbol}{float(summary['total_subtotal']):,.2f}",
    ])

    table = Table(
        table_data,
        colWidths=[0.35 * inch, 3.0 * inch, 1.2 * inch, 0.85 * inch, 1.2 * inch],
        repeatRows=1,
    )
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), header_color),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        ('ALIGN', (0, 0), (0, -1), 'CENTER'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
        ('FONTSIZE', (0, 1), (-1, totals_idx - 1), 9),
        ('TOPPADDING', (0, 1), (-1, totals_idx - 1), 4),
        ('BOTTOMPADDING', (0, 1), (-1, totals_idx - 1), 4),
        ('ROWBACKGROUNDS', (0, 1), (-1, totals_idx - 1), [colors.white, row_alt_color]),
        ('BACKGROUND', (0, totals_idx), (-1, totals_idx), header_dark_color),
        ('TEXTCOLOR', (0, totals_idx), (-1, totals_idx), colors.whitesmoke),
        ('FONTNAME', (0, totals_idx), (-1, totals_idx), 'Helvetica-Bold'),
        ('FONTSIZE', (0, totals_idx), (-1, totals_idx), 9),
        ('TOPPADDING', (0, totals_idx), (-1, totals_idx), 7),
        ('BOTTOMPADDING', (0, totals_idx), (-1, totals_idx), 7),
        ('LINEABOVE', (0, totals_idx), (-1, totals_idx), 1.5, header_dark_color),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    # Keep title with table so the heading is not stranded alone before a page break.
    elements.append(KeepTogether([heading, table]))
    elements.append(Spacer(1, 0.2 * inch))
