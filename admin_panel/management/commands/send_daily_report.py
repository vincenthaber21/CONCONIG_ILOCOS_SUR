from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Sum, Count, Q, F
from django.core.mail import EmailMessage
from django.conf import settings
from django.contrib.auth.models import User
from datetime import datetime, timedelta
from decimal import Decimal
import io
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

from transactions.models import Transaction, TransactionItem
from inventory.models import Product, Category, TaxRate
from inventory.utils import get_giveaway_summary_for_period
from members.models import Member
from admin_panel.models import KioskConfig, SentDailyReport
from admin_panel.report_customers import append_top_customers_pdf, get_top_customers_for_period
from admin_panel.report_utils import get_report_sale_items, get_report_transactions
from admin_panel.report_walk_in import append_walk_in_summary_pdf
from admin_panel.report_wholesale import append_wholesale_sales_pdf, get_wholesale_sales_for_period
from admin_panel.utils import get_masked_from_email
from transactions.walk_in_customers import get_walk_in_summary_for_period


def _get_active_tax_label():
    """Return the human-readable label for the active TaxRate (e.g. 'VAT 12%')."""
    tax = TaxRate.objects.filter(is_active=True).order_by('name').first()
    if not tax:
        return 'VAT (12%)'
    rate_pct = float(tax.rate)
    pct_str = f'{int(rate_pct)}%' if rate_pct == int(rate_pct) else f'{rate_pct}%'
    if '%' in tax.name:
        return tax.name
    return f'{tax.name} ({pct_str})'


class Command(BaseCommand):
    help = 'Generates and emails a daily sales and stock report as PDF'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            help='Date for the report (YYYY-MM-DD format). Defaults to today if not specified.',
        )
        parser.add_argument(
            '--to',
            type=str,
            help='Email recipient (overrides settings).',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force sending even if report was already sent for this date and recipient.',
        )

    def get_admin_email(self):
        """Get admin email from database - checks superusers, staff users, and Member admins"""
        # First, try to get superuser email
        superuser = User.objects.filter(is_superuser=True, is_active=True).exclude(email='').first()
        if superuser and superuser.email:
            return superuser.email
        
        # Then try to get staff user email
        staff_user = User.objects.filter(is_staff=True, is_active=True).exclude(email='').first()
        if staff_user and staff_user.email:
            return staff_user.email
        
        # Finally, try to get Member with admin role
        admin_member = Member.objects.filter(member_role__slug='admin', is_active=True).exclude(email__isnull=True).exclude(email='').first()
        if admin_member and admin_member.email:
            return admin_member.email
        
        # Fall back to settings
        return getattr(settings, 'DAILY_REPORT_EMAIL', getattr(settings, 'ADMIN_EMAIL', 'habervincent21@gmail.com'))

    def handle(self, *args, **options):
        # Determine the date for the report
        if options['date']:
            try:
                report_date = datetime.strptime(options['date'], '%Y-%m-%d').date()
            except ValueError:
                self.stdout.write(self.style.ERROR('Invalid date format. Use YYYY-MM-DD'))
                return
        else:
            # Default to today
            report_date = timezone.now().date()
        
        # Get email recipient - only send to admin email from database
        recipient_email = options.get('to') or self.get_admin_email()

        # Check if report has already been sent for this date and recipient
        force_resend = options.get('force', False)
        if not force_resend:
            already_sent = SentDailyReport.objects.filter(
                report_date=report_date,
                recipient_email=recipient_email
            ).exists()
            
            if already_sent:
                sent_record = SentDailyReport.objects.get(
                    report_date=report_date,
                    recipient_email=recipient_email
                )
                self.stdout.write(self.style.WARNING(
                    f'Report for {report_date} has already been sent to {recipient_email} '
                    f'on {timezone.localtime(sent_record.sent_at).strftime("%Y-%m-%d %H:%M:%S")}. '
                    f'Use --force to resend.'
                ))
                return

        self.stdout.write(f'Generating daily report for {report_date}...')

        # Check if there are any reportable sales for this date
        has_transactions = get_report_transactions(report_date).exists()

        if not has_transactions:
            from admin_panel.report_utils import REPORT_SALE_STATUSES
            # Suggest the most recent date with reportable sales
            latest_date = (
                Transaction.objects.filter(status__in=REPORT_SALE_STATUSES)
                .exclude(transaction_number__startswith='DUMMY-')
                .dates('created_at', 'day', order='DESC')
                .first()
            )

            if latest_date:
                self.stdout.write(self.style.WARNING(
                    f'No completed/partially-refunded sales found for {report_date}. '
                    f'Most recent date with transactions: {latest_date}. '
                    f'Consider using --date {latest_date} to generate a report for that date.'
                ))

        # Generate PDF
        pdf_buffer = self.generate_pdf(report_date)

        # Send email
        try:
            self.send_email(pdf_buffer, report_date, recipient_email)
            
            # Record that the report was sent (update if forcing resend, create if new)
            SentDailyReport.objects.update_or_create(
                report_date=report_date,
                recipient_email=recipient_email,
                defaults={'sent_at': timezone.now()}
            )
            
            self.stdout.write(self.style.SUCCESS(f'Successfully sent daily report to {recipient_email}'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error sending email: {str(e)}'))
            raise

    def generate_pdf(self, report_date):
        """Generate PDF report for the given date"""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, 
                               rightMargin=30, leftMargin=30,
                               topMargin=30, bottomMargin=18)
        
        # Container for the 'Flowable' objects
        elements = []
        styles = getSampleStyleSheet()
        
        # Use "PHP" instead of peso sign for better font compatibility in PDF
        currency_symbol = "PHP "
        
        # Define custom styles
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#1a237e'),
            spaceAfter=30,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        )
        
        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#283593'),
            spaceAfter=12,
            spaceBefore=12,
            fontName='Helvetica-Bold',
            keepWithNext=True,
        )
        
        # Title
        title = Paragraph("Daily Sales & Stock Report", title_style)
        elements.append(title)
        
        date_str = report_date.strftime('%B %d, %Y')
        date_para = Paragraph(f"Report Date: {date_str}", styles['Normal'])
        elements.append(date_para)
        elements.append(Spacer(1, 0.3*inch))
        
        # ===== SALES SUMMARY =====
        elements.append(Paragraph("Sales Summary", heading_style))

        daily_transactions = get_report_transactions(report_date)
        total_transactions = daily_transactions.count()
        self.stdout.write(
            f'Found {total_transactions} reportable sales for {report_date}'
        )

        if total_transactions > 0:
            sample_txn = daily_transactions.first()
            self.stdout.write(f'Sample transaction date: {sample_txn.created_at} (status: {sample_txn.status})')
            self.stdout.write(f'Sample transaction amount: {sample_txn.total_amount}')

        # Header totals are net of refunded lines
        tax_agg = daily_transactions.aggregate(
            total_amount=Sum('total_amount'),
            total_vatable=Sum('vatable_sale'),
            total_vat=Sum('vat_amount'),
        )

        self.stdout.write(f'Raw revenue_agg: {tax_agg["total_amount"]}')

        # Convert to Decimal, handling None values and existing Decimal values
        def to_decimal(value):
            if value is None:
                return Decimal('0.00')
            if isinstance(value, Decimal):
                return value
            return Decimal(str(value))

        total_revenue = to_decimal(tax_agg['total_amount'])
        total_vatable = to_decimal(tax_agg['total_vatable'])
        total_vat = to_decimal(tax_agg['total_vat'])
        total_vat_exempt = total_revenue - total_vatable - total_vat

        # Resolve active tax label from the database so it matches receipts exactly.
        tax_enabled = bool(KioskConfig.get().tax_enabled)
        active_tax_label = _get_active_tax_label() if tax_enabled else ''

        # Payment method breakdown
        payment_breakdown = daily_transactions.values('payment_method').annotate(
            count=Count('id'),
            total=Sum('total_amount')
        ).order_by('-total')
        
        payment_labels = dict(Transaction.PAYMENT_METHODS)
        
        # Sales summary table — tax rows only when tax is enabled system-wide
        sales_data = [
            ['Metric', 'Value'],
            ['Total Transactions', f"{total_transactions:,}"],
            ['Total Revenue', f"{currency_symbol}{float(total_revenue):,.2f}"],
        ]
        if tax_enabled:
            sales_data.extend([
                ['Vatable Sales', f"{currency_symbol}{float(total_vatable):,.2f}"],
                [active_tax_label, f"{currency_symbol}{float(total_vat):,.2f}"],
                ['VAT-Exempt Sales', f"{currency_symbol}{float(total_vat_exempt):,.2f}"],
            ])
        
        sales_table = Table(sales_data, colWidths=[3*inch, 2*inch])
        sales_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#283593')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
        ]))
        elements.append(sales_table)
        elements.append(Spacer(1, 0.2*inch))
        
        # Payment method breakdown
        if payment_breakdown:
            elements.append(Paragraph("Payment Method Breakdown", heading_style))
            payment_data = [['Payment Method', 'Total Amount']]
            for entry in payment_breakdown:
                method_label = payment_labels.get(entry['payment_method'], entry['payment_method'].title())
                total_amount = entry['total'] if entry['total'] is not None else Decimal('0.00')
                payment_data.append([
                    method_label,
                    f"{currency_symbol}{float(total_amount):,.2f}"
                ])
            
            payment_table = Table(payment_data, colWidths=[3*inch, 2*inch])
            payment_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#283593')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (0, -1), 'LEFT'),
                ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 11),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
            ]))
            elements.append(payment_table)
            elements.append(Spacer(1, 0.2*inch))

        top_customers = get_top_customers_for_period(report_date)
        append_top_customers_pdf(
            elements,
            top_customers,
            heading_style=heading_style,
            styles=styles,
            currency_symbol=currency_symbol,
            header_color=colors.HexColor('#283593'),
            header_dark_color=colors.HexColor('#1a237e'),
            row_alt_color=colors.HexColor('#f0f4ff'),
            period_label=report_date.strftime('%B %d, %Y'),
        )
        
        # Top Products Sold — non-refunded line items; revenue = Sum(total_price)
        top_products = list(
            get_report_sale_items(report_date)
            .values('product_name', 'product_barcode')
            .annotate(
                quantity_sold=Sum('quantity'),
                total_revenue=Sum('total_price'),
            )
            .order_by('-quantity_sold')[:10]
        )

        if top_products:
            elements.append(Paragraph("Top Products Sold (Top 10)", heading_style))
            products_data = [['Product Name', 'Barcode', 'Quantity', 'Revenue']]
            for product in top_products:
                quantity = product['quantity_sold'] if product['quantity_sold'] is not None else 0
                revenue = product['total_revenue'] if product['total_revenue'] is not None else Decimal('0.00')
                products_data.append([
                    product['product_name'][:30],  # Truncate long names
                    product['product_barcode'],
                    f"{quantity:,}",
                    f"{currency_symbol}{float(revenue):,.2f}"
                ])
            
            products_table = Table(products_data, colWidths=[2*inch, 1*inch, 0.75*inch, 1.25*inch])
            products_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#283593')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (1, -1), 'LEFT'),
                ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('FONTSIZE', (0, 1), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
            ]))
            elements.append(products_table)
            elements.append(Spacer(1, 0.2*inch))

        wholesale_summary = get_wholesale_sales_for_period(report_date)
        append_wholesale_sales_pdf(
            elements,
            wholesale_summary,
            heading_style=heading_style,
            styles=styles,
            currency_symbol=currency_symbol,
            header_color=colors.HexColor('#283593'),
            header_dark_color=colors.HexColor('#1a237e'),
            row_alt_color=colors.HexColor('#f0f4ff'),
            period_label=report_date.strftime('%B %d, %Y'),
        )

        # ===== WALK-IN CUSTOMERS SUMMARY =====
        walk_in_summary = get_walk_in_summary_for_period(report_date)
        append_walk_in_summary_pdf(
            elements,
            walk_in_summary,
            heading_style=heading_style,
            styles=styles,
            currency_symbol=currency_symbol,
            header_color=colors.HexColor('#283593'),
            header_dark_color=colors.HexColor('#1a237e'),
            row_alt_color=colors.HexColor('#f0f4ff'),
            period_label=report_date.strftime('%B %d, %Y'),
        )

        # ===== GIVEAWAY PRODUCTS SUMMARY =====
        giveaway_summary = get_giveaway_summary_for_period(report_date)
        elements.append(Paragraph("Giveaway Products Summary", heading_style))

        giveaway_metrics = [
            ['Metric', 'Value'],
            ['Total Units Given Away', f"{giveaway_summary['total_units']:,}"],
            ['Distinct Products', f"{len(giveaway_summary['products']):,}"],
            ['Estimated Value (List Price)', f"{currency_symbol}{float(giveaway_summary['total_est_value']):,.2f}"],
        ]
        giveaway_metrics_table = Table(giveaway_metrics, colWidths=[3*inch, 2*inch])
        giveaway_metrics_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3730a3')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#eef2ff')),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#eef2ff')]),
        ]))
        elements.append(giveaway_metrics_table)
        elements.append(Spacer(1, 0.15*inch))

        if giveaway_summary['products']:
            giveaway_data = [['Product Name', 'Barcode', 'Unit Price', 'Qty Given', 'Est. Value']]
            for product in giveaway_summary['products']:
                giveaway_data.append([
                    product['name'][:30],
                    product['barcode'],
                    f"{currency_symbol}{float(product['price']):,.2f}",
                    f"{product['quantity_given']:,}",
                    f"{currency_symbol}{float(product['est_value']):,.2f}",
                ])
            giveaway_data.append([
                'TOTAL',
                '',
                '',
                f"{giveaway_summary['total_units']:,}",
                f"{currency_symbol}{float(giveaway_summary['total_est_value']):,.2f}",
            ])
            giveaway_totals_idx = len(giveaway_data) - 1
            giveaway_table = Table(
                giveaway_data,
                colWidths=[1.75*inch, 1*inch, 0.85*inch, 0.75*inch, 1*inch],
                repeatRows=1,
            )
            giveaway_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3730a3')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (1, -1), 'LEFT'),
                ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('FONTSIZE', (0, 1), (-1, giveaway_totals_idx - 1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, giveaway_totals_idx - 1), colors.HexColor('#eef2ff')),
                ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                ('ROWBACKGROUNDS', (0, 1), (-1, giveaway_totals_idx - 1), [colors.white, colors.HexColor('#eef2ff')]),
                ('BACKGROUND', (0, giveaway_totals_idx), (-1, giveaway_totals_idx), colors.HexColor('#312e81')),
                ('TEXTCOLOR', (0, giveaway_totals_idx), (-1, giveaway_totals_idx), colors.whitesmoke),
                ('FONTNAME', (0, giveaway_totals_idx), (-1, giveaway_totals_idx), 'Helvetica-Bold'),
                ('LINEABOVE', (0, giveaway_totals_idx), (-1, giveaway_totals_idx), 1.5, colors.HexColor('#312e81')),
            ]))
            elements.append(giveaway_table)
        else:
            elements.append(Paragraph("No giveaway products recorded for this date.", styles['Normal']))
        elements.append(Spacer(1, 0.2*inch))
        
        elements.append(PageBreak())
        
        # ===== STOCK SUMMARY =====
        elements.append(Paragraph("Stock Summary", heading_style))
        
        # Total products
        total_products = Product.objects.filter(is_active=True).count()
        low_stock_count = Product.objects.filter(is_active=True, stock_quantity__lte=F('low_stock_threshold')).exclude(stock_quantity=0).count()
        out_of_stock_count = Product.objects.filter(is_active=True, stock_quantity=0).count()
        
        stock_summary_data = [
            ['Metric', 'Value'],
            ['Total Active Products', f"{total_products:,}"],
            ['Low Stock Items', f"{low_stock_count:,}"],
            ['Out of Stock Items', f"{out_of_stock_count:,}"],
        ]
        
        stock_summary_table = Table(stock_summary_data, colWidths=[3*inch, 2*inch])
        stock_summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#283593')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
        ]))
        elements.append(stock_summary_table)
        elements.append(Spacer(1, 0.2*inch))
        
        # Low Stock Products
        low_stock_products = Product.objects.filter(
            is_active=True,
            stock_quantity__lte=F('low_stock_threshold')
        ).order_by('stock_quantity', 'name')
        
        if low_stock_products.exists():
            elements.append(Paragraph("Low Stock & Out of Stock Products", heading_style))
            low_stock_data = [['Product Name', 'Barcode', 'Current Stock', 'Status']]
            
            for product in low_stock_products[:50]:  # Limit to 50 for PDF size
                status = "Out of Stock" if product.stock_quantity == 0 else "Low Stock"
                low_stock_data.append([
                    product.name[:30],
                    product.barcode,
                    f"{product.stock_quantity:,}",
                    status
                ])
            
            low_stock_table = Table(low_stock_data, colWidths=[2.25*inch, 1.25*inch, 0.9*inch, 1*inch])
            low_stock_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#d32f2f')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (1, -1), 'LEFT'),
                ('ALIGN', (2, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('FONTSIZE', (0, 1), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
            ]))
            elements.append(low_stock_table)
            elements.append(Spacer(1, 0.2*inch))
        
        # Category Stock Summary
        category_stock = list(Product.objects.filter(is_active=True).values(
            'category__name'
        ).annotate(
            product_count=Count('id'),
            total_stock=Sum('stock_quantity'),
            low_stock_count=Count('id', filter=Q(stock_quantity__lte=F('low_stock_threshold')))
        ).order_by('category__name'))

        if category_stock:
            elements.append(Paragraph("Stock by Category", heading_style))

            # Dynamically size category column based on longest name
            max_name_len = max((len(cat['category__name'] or 'Uncategorized') for cat in category_stock), default=10)
            # Usable page width: A4 (595.27pt) minus left+right margins (30+30 = 60pt) = 535.27pt
            usable_width = 535.27
            cat_col   = min(240, max(140, max_name_len * 7))
            remaining = usable_width - cat_col
            num_col   = remaining * 0.25
            stock_col = remaining * 0.375
            low_col   = remaining * 0.375

            # Aggregate totals directly from DB (source of truth, not from annotation)
            db_totals = Product.objects.filter(is_active=True).aggregate(
                total_products=Count('id'),
                total_stock=Sum('stock_quantity'),
                total_low=Count('id', filter=Q(stock_quantity__lte=F('low_stock_threshold'))),
            )
            total_all_products = db_totals['total_products'] or 0
            total_all_stock    = db_totals['total_stock'] or 0
            total_all_low      = db_totals['total_low'] or 0

            category_data = [['Category', 'Products', 'Total Stock', 'Low Stock Items']]
            for cat in category_stock:
                category_name = cat['category__name'] or 'Uncategorized'
                category_data.append([
                    category_name,
                    f"{cat['product_count']:,}",
                    f"{cat['total_stock'] or 0:,}",
                    f"{cat['low_stock_count'] or 0:,}",
                ])
            # Totals footer row
            category_data.append([
                'TOTAL',
                f"{total_all_products:,}",
                f"{total_all_stock:,}",
                f"{total_all_low:,}",
            ])

            totals_row_idx = len(category_data) - 1
            category_table = Table(
                category_data,
                colWidths=[cat_col, num_col, stock_col, low_col],
                repeatRows=1,
            )
            cat_style = [
                # Header
                ('BACKGROUND',    (0, 0), (-1, 0),              colors.HexColor('#283593')),
                ('TEXTCOLOR',     (0, 0), (-1, 0),              colors.whitesmoke),
                ('FONTNAME',      (0, 0), (-1, 0),              'Helvetica-Bold'),
                ('FONTSIZE',      (0, 0), (-1, 0),              10),
                ('BOTTOMPADDING', (0, 0), (-1, 0),              10),
                ('TOPPADDING',    (0, 0), (-1, 0),              8),
                # Data rows
                ('FONTSIZE',      (0, 1), (-1, totals_row_idx - 1), 9),
                ('TOPPADDING',    (0, 1), (-1, totals_row_idx - 1), 5),
                ('BOTTOMPADDING', (0, 1), (-1, totals_row_idx - 1), 5),
                ('ROWBACKGROUNDS', (0, 1), (-1, totals_row_idx - 1), [colors.white, colors.HexColor('#f0f4ff')]),
                # Totals footer
                ('BACKGROUND',    (0, totals_row_idx), (-1, totals_row_idx), colors.HexColor('#1a237e')),
                ('TEXTCOLOR',     (0, totals_row_idx), (-1, totals_row_idx), colors.whitesmoke),
                ('FONTNAME',      (0, totals_row_idx), (-1, totals_row_idx), 'Helvetica-Bold'),
                ('FONTSIZE',      (0, totals_row_idx), (-1, totals_row_idx), 9),
                ('TOPPADDING',    (0, totals_row_idx), (-1, totals_row_idx), 7),
                ('BOTTOMPADDING', (0, totals_row_idx), (-1, totals_row_idx), 7),
                # Alignment
                ('ALIGN',  (0, 0), (0, -1), 'LEFT'),
                ('ALIGN',  (1, 0), (-1, -1), 'CENTER'),
                # Grid
                ('GRID',   (0, 0), (-1, -1), 0.5, colors.grey),
                ('LINEABOVE', (0, totals_row_idx), (-1, totals_row_idx), 1.5, colors.HexColor('#1a237e')),
            ]
            # Highlight rows that have any low-stock items
            for i, cat in enumerate(category_stock, start=1):
                if (cat['low_stock_count'] or 0) > 0:
                    cat_style.append(('TEXTCOLOR', (3, i), (3, i), colors.HexColor('#c62828')))
                    cat_style.append(('FONTNAME',  (3, i), (3, i), 'Helvetica-Bold'))

            category_table.setStyle(TableStyle(cat_style))
            elements.append(category_table)
            elements.append(Spacer(1, 0.2*inch))
        
        elements.append(PageBreak())
        
        # ===== RECENT TRANSACTIONS =====
        elements.append(Paragraph("Recent Transactions (Last 50)", heading_style))
        
        recent_transactions = list(daily_transactions.order_by('-created_at')[:50])
        
        # Debug: Show how many transactions we're including
        self.stdout.write(f'Including {len(recent_transactions)} transactions in recent transactions list')
        
        if recent_transactions:
            if tax_enabled:
                transactions_data = [
                    ['Transaction #', 'Member', 'Method', 'Time', 'Amount', 'Vatable Sale', active_tax_label]
                ]
                txn_col_widths = [
                    1.3 * inch, 1.2 * inch, 0.6 * inch, 0.65 * inch,
                    0.95 * inch, 0.9 * inch, 0.85 * inch,
                ]
            else:
                transactions_data = [['Transaction #', 'Member', 'Method', 'Time', 'Amount']]
                txn_col_widths = [1.5 * inch, 1.5 * inch, 0.8 * inch, 0.85 * inch, 1.5 * inch]

            for txn in recent_transactions:
                member_name = txn.customer_display_name
                if len(member_name) > 20:
                    member_name = member_name[:17] + '...'
                
                method_short = {
                    'cash': 'Cash',
                    'debit': 'Debit'
                }.get(txn.payment_method, txn.payment_method.title())
                
                time_str = timezone.localtime(txn.created_at).strftime('%H:%M:%S')
                amount = Decimal(str(txn.total_amount)) if txn.total_amount is not None else Decimal('0.00')
                row = [
                    txn.transaction_number[:15],
                    member_name,
                    method_short,
                    time_str,
                    f"{currency_symbol}{float(amount):,.2f}",
                ]
                if tax_enabled:
                    vatable_amt = (
                        Decimal(str(txn.vatable_sale)) if txn.vatable_sale is not None else Decimal('0.00')
                    )
                    vat_amt = (
                        Decimal(str(txn.vat_amount)) if txn.vat_amount is not None else Decimal('0.00')
                    )
                    row.extend([
                        f"{currency_symbol}{float(vatable_amt):,.2f}",
                        f"{currency_symbol}{float(vat_amt):,.2f}",
                    ])
                transactions_data.append(row)
            
            txn_table = Table(transactions_data, colWidths=txn_col_widths)
            txn_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#283593')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (1, -1), 'LEFT'),
                ('ALIGN', (2, 0), (3, -1), 'CENTER'),
                ('ALIGN', (4, 0), (-1, -1), 'RIGHT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 8),
                ('FONTSIZE', (0, 1), (-1, -1), 7),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
            ]))
            elements.append(txn_table)
        else:
            elements.append(Paragraph("No transactions for this date.", styles['Normal']))
        
        # Build PDF
        doc.build(elements)
        buffer.seek(0)
        return buffer

    def send_email(self, pdf_buffer, report_date, recipient_email):
        """Send the PDF report via email"""
        date_str = report_date.strftime('%B %d, %Y')
        subject = f'Daily Sales & Stock Report - {date_str}'
        
        body = f"""
Dear Administrator,

Please find attached the daily sales and stock report for {date_str}.

This report includes:
- Sales summary and statistics
- Payment method breakdown
- Top products sold
- Wholesale sales products summary
- Walk-in customers summary
- Giveaway products summary
- Stock levels and low stock alerts
- Recent transactions

Best regards,
BAGNOS MPC
        """.strip()
        
        email = EmailMessage(
            subject=subject,
            body=body,
            from_email=get_masked_from_email(),
            to=[recipient_email],
        )
        
        # Attach PDF
        filename = f'daily_report_{report_date.strftime("%Y%m%d")}.pdf'
        email.attach(filename, pdf_buffer.getvalue(), 'application/pdf')
        
        email.send()

