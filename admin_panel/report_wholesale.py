"""Wholesale sale unit sections for PDF and Excel daily reports."""

from django.db.models import Max, Sum
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from admin_panel.report_utils import REPORT_SALE_STATUSES, get_report_sale_items
from inventory.models import ProductSaleUnit


def get_wholesale_sales_for_period(
    date_from,
    date_to=None,
    sale_statuses=REPORT_SALE_STATUSES,
):
    """
    Aggregate wholesale (box / bulk) line items sold in a report period.

    Wholesale lines are identified by matching ``TransactionItem.product_barcode``
    to active ``ProductSaleUnit`` rows with ``sale_mode=wholesale``.
    Revenue uses Sum(total_price) from non-refunded DB lines.
    """
    if date_to is None:
        date_to = date_from

    wholesale_units = {
        unit['barcode']: unit
        for unit in ProductSaleUnit.objects.filter(
            sale_mode=ProductSaleUnit.SALE_MODE_WHOLESALE,
        ).values('barcode', 'unit_label', 'units_per_package', 'product_id')
    }

    empty = {
        'total_packages': 0,
        'total_pieces': 0,
        'total_revenue': 0.0,
        'products': [],
    }
    if not wholesale_units:
        return empty

    rows = list(
        get_report_sale_items(date_from, date_to, sale_statuses)
        .filter(product_barcode__in=wholesale_units.keys())
        .values('product_name', 'product_barcode')
        .annotate(
            packages_sold=Sum('quantity'),
            total_revenue=Sum('total_price'),
            unit_price=Max('unit_price'),
        )
        .order_by('-packages_sold', 'product_name')
    )

    products = []
    total_packages = 0
    total_pieces = 0
    total_revenue = 0.0

    for row in rows:
        unit_info = wholesale_units.get(row['product_barcode'], {})
        units_per_package = unit_info.get('units_per_package') or 1
        packages = row['packages_sold'] or 0
        revenue = float(row['total_revenue'] or 0)
        pieces = packages * units_per_package
        # Prefer effective average so price × packages ≈ revenue when discounts apply.
        if packages > 0:
            unit_price = round(revenue / packages, 2)
        else:
            unit_price = float(row['unit_price'] or 0)

        products.append({
            'product_name': row['product_name'],
            'barcode': row['product_barcode'],
            'unit_label': unit_info.get('unit_label') or 'Wholesale',
            'units_per_package': units_per_package,
            'unit_price': unit_price,
            'packages_sold': packages,
            'pieces_sold': pieces,
            'revenue': round(revenue, 2),
        })
        total_packages += packages
        total_pieces += pieces
        total_revenue += revenue

    return {
        'total_packages': total_packages,
        'total_pieces': total_pieces,
        'total_revenue': round(total_revenue, 2),
        'products': products,
    }


def wholesale_excel_metric_rows(summary):
    """Rows for the Wholesale Summary Excel sheet."""
    return [
        ['Packages / Boxes Sold', summary['total_packages']],
        ['Base Pieces Sold', summary['total_pieces']],
        ['Wholesale Revenue', summary['total_revenue']],
        ['Distinct Products', len(summary['products'])],
    ]


def wholesale_excel_product_rows(summary):
    """Rows for the Wholesale Products Excel sheet."""
    return [
        [
            idx,
            p['product_name'],
            p['barcode'],
            p['unit_label'],
            p['units_per_package'],
            p['unit_price'],
            p['packages_sold'],
            p['pieces_sold'],
            p['revenue'],
        ]
        for idx, p in enumerate(summary.get('products') or [], start=1)
    ]


def append_wholesale_sales_pdf(
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
    """Append wholesale sales summary tables to a ReportLab elements list."""
    elements.append(Paragraph('Wholesale Sales Summary', heading_style))

    metrics_data = [
        ['Metric', 'Value'],
        ['Packages / Boxes Sold', f"{summary['total_packages']:,}"],
        ['Base Pieces Sold', f"{summary['total_pieces']:,}"],
        ['Wholesale Revenue', f"{currency_symbol}{summary['total_revenue']:,.2f}"],
        ['Distinct Products', f"{len(summary['products']):,}"],
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

    products = summary.get('products') or []
    if not products:
        elements.append(
            Paragraph(f'No wholesale sales recorded for {period_label}.', styles['Normal'])
        )
        elements.append(Spacer(1, 0.2 * inch))
        return

    elements.append(Paragraph('Wholesale Products Sold', heading_style))
    product_data = [
        ['#', 'Product Name', 'Barcode', 'Unit', 'Price', 'Packages', 'Pieces', 'Revenue'],
    ]
    for idx, product in enumerate(products, start=1):
        product_data.append([
            str(idx),
            product['product_name'][:28],
            product['barcode'],
            product['unit_label'][:14],
            f"{currency_symbol}{product['unit_price']:,.2f}",
            f"{product['packages_sold']:,}",
            f"{product['pieces_sold']:,}",
            f"{currency_symbol}{product['revenue']:,.2f}",
        ])

    totals_idx = len(product_data)
    product_data.append([
        '', 'TOTAL', '', '', '',
        f"{summary['total_packages']:,}",
        f"{summary['total_pieces']:,}",
        f"{currency_symbol}{summary['total_revenue']:,.2f}",
    ])

    product_table = Table(
        product_data,
        colWidths=[
            0.3 * inch, 1.55 * inch, 0.95 * inch, 0.85 * inch,
            0.75 * inch, 0.7 * inch, 0.65 * inch, 0.85 * inch,
        ],
        repeatRows=1,
    )
    product_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), header_color),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (0, -1), 'CENTER'),
        ('ALIGN', (1, 0), (3, -1), 'LEFT'),
        ('ALIGN', (4, 0), (-1, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('FONTSIZE', (0, 1), (-1, totals_idx - 1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('ROWBACKGROUNDS', (0, 1), (-1, totals_idx - 1), [colors.white, row_alt_color]),
        ('BACKGROUND', (0, totals_idx), (-1, totals_idx), header_dark_color),
        ('TEXTCOLOR', (0, totals_idx), (-1, totals_idx), colors.whitesmoke),
        ('FONTNAME', (0, totals_idx), (-1, totals_idx), 'Helvetica-Bold'),
        ('LINEABOVE', (0, totals_idx), (-1, totals_idx), 1.5, header_dark_color),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    elements.append(product_table)
    elements.append(Spacer(1, 0.2 * inch))
