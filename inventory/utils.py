"""
Utility functions for inventory management
"""
import logging
import re

from django.conf import settings
from django.core.cache import cache
from django.utils.html import format_html, escape as html_escape

logger = logging.getLogger(__name__)

STOCK_ALERT_ROLE_SLUGS = ('admin', 'staff')
_STOCK_ALERT_SEND_DEDUP_SECONDS = 20


def _send_email_async(subject, message, recipient_list, html_message=None):
    """
    Send email in a background thread with retries (same path as OTP mail).
    """
    recipients = [email for email in (recipient_list or []) if email]
    if not recipients:
        logger.warning('Skipped email "%s": no staff/admin recipients', subject)
        return

    from mobile_api.email_utils import send_email_async

    send_email_async(
        subject=subject,
        body=message,
        recipient_email=recipients,
        html_body=html_message,
    )


def _normalize_email(value):
    """Return a bare email address from a raw field or 'Name <email>' string."""
    if not value:
        return ''
    value = str(value).strip()
    if not value:
        return ''
    match = re.search(r'<([^<>\s]+@[^<>\s]+)>', value)
    if match:
        return match.group(1).strip()
    return value


def get_stock_alert_recipient_emails():
    """
    All distinct emails for active Members with admin or staff roles.

    Uses Member.email first, then the linked Django User email.
    Falls back to ADMIN_EMAIL / DEFAULT_FROM_EMAIL if none are set.
    """
    from members.models import Member

    emails = []
    seen = set()

    def _add(raw):
        email = _normalize_email(raw)
        key = email.lower()
        if email and '@' in email and key not in seen:
            seen.add(key)
            emails.append(email)

    members = (
        Member.objects.filter(
            is_active=True,
            member_role__slug__in=STOCK_ALERT_ROLE_SLUGS,
        )
        .select_related('user', 'member_role')
        .order_by('member_role__sort_order', 'first_name', 'last_name')
    )
    for member in members:
        _add(member.email)
        user = getattr(member, 'user', None)
        if user:
            _add(user.email)

    if not emails:
        _add(getattr(settings, 'ADMIN_EMAIL', ''))
    if not emails:
        _add(getattr(settings, 'DEFAULT_FROM_EMAIL', ''))

    return emails


def get_admin_email():
    """First stock-alert recipient (admin/staff). Kept for callers that need a single address."""
    recipients = get_stock_alert_recipient_emails()
    return recipients[0] if recipients else ''


def _claim_stock_alert_send(product_id, event):
    """Prevent signal + StockManager from sending the same alert twice in one request."""
    key = f'inv_stock_email_{event}_{product_id}'
    if cache.get(key):
        return False
    cache.set(key, 1, _STOCK_ALERT_SEND_DEDUP_SECONDS)
    return True


def send_out_of_stock_notification(product):
    """
    Send email notification to admin when a product runs out of stock.
    
    Args:
        product: Product instance that has run out of stock
    """
    try:
        if not _claim_stock_alert_send(product.id, 'out_of_stock'):
            return True

        recipients = get_stock_alert_recipient_emails()
        if not recipients:
            logger.warning(
                'No staff/admin emails for out-of-stock alert (product %s)',
                product.id,
            )
            return False
        
        # Prepare email content
        subject = f'⚠️ Product Out of Stock: {product.name}'
        
        # Format price as string
        price_str = f'{float(product.price):.2f}'
        category_name = product.category.name if product.category else 'Uncategorized'
        
        # Build email body
        body = f"""
Dear Admin and Staff,

A product has run out of stock and requires immediate attention.

Product Details:
- Name: {product.name}
- Barcode: {product.barcode}
- Current Stock: {product.stock_quantity}
- Low Stock Threshold: {product.low_stock_threshold}
- Category: {category_name}
- Price: ₱{price_str}

Please restock this product as soon as possible to avoid sales disruption.

This is an automated notification from the inventory management system.

Best regards,
BAGNOS MPC
"""
        
        # HTML version for better formatting
        html_message = format_html("""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background-color: #d32f2f; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0; }}
                .content {{ background-color: #f9f9f9; padding: 20px; border: 1px solid #ddd; }}
                .product-info {{ background-color: white; padding: 15px; margin: 15px 0; border-left: 4px solid #d32f2f; }}
                .product-info p {{ margin: 8px 0; }}
                .label {{ font-weight: bold; color: #555; }}
                .footer {{ text-align: center; padding: 20px; color: #777; font-size: 12px; }}
                .warning {{ color: #d32f2f; font-weight: bold; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>⚠️ Product Out of Stock Alert</h2>
                </div>
                <div class="content">
                    <p>Dear Admin and Staff,</p>
                    <p class="warning">A product has run out of stock and requires immediate attention.</p>
                    
                    <div class="product-info">
                        <h3>Product Details:</h3>
                        <p><span class="label">Name:</span> {}</p>
                        <p><span class="label">Barcode:</span> {}</p>
                        <p><span class="label">Current Stock:</span> <span class="warning">{}</span></p>
                        <p><span class="label">Low Stock Threshold:</span> {}</p>
                        <p><span class="label">Category:</span> {}</p>
                        <p><span class="label">Price:</span> ₱{}</p>
                    </div>
                    
                    <p>Please restock this product as soon as possible to avoid sales disruption.</p>
                    <p>This is an automated notification from the inventory management system.</p>
                </div>
                <div class="footer">
                    <p>Best regards,<br>BAGNOS MPC</p>
                </div>
            </div>
        </body>
        </html>
        """, 
        product.name,
        product.barcode,
        product.stock_quantity,
        product.low_stock_threshold,
        category_name,
        price_str
        )
        
        _send_email_async(subject, body, recipients, html_message)
        
        return True
    except Exception as e:
        logger.error(f'Failed to send out-of-stock notification for product {product.id}: {str(e)}')
        return False


def send_low_stock_warning(product):
    """
    Send email warning to admin when a product reaches the low stock threshold.
    
    Args:
        product: Product instance that has reached low stock threshold
    """
    try:
        if not _claim_stock_alert_send(product.id, 'low_stock'):
            return True

        recipients = get_stock_alert_recipient_emails()
        if not recipients:
            logger.warning(
                'No staff/admin emails for low-stock alert (product %s)',
                product.id,
            )
            return False
        
        # Prepare email content
        subject = f'⚠️ Low Stock Warning: {product.name}'
        
        # Format price as string
        price_str = f'{float(product.price):.2f}'
        category_name = product.category.name if product.category else 'Uncategorized'
        
        # Calculate how many units below threshold
        stock_deficit = max(0, product.low_stock_threshold - product.stock_quantity)
        
        # Build email body
        body = f"""
Dear Admin and Staff,

A product has reached its low stock threshold and requires attention.

Product Details:
- Name: {product.name}
- Barcode: {product.barcode}
- Current Stock: {product.stock_quantity}
- Low Stock Threshold: {product.low_stock_threshold}
- Stock Deficit: {stock_deficit} units needed to reach threshold
- Category: {category_name}
- Price: ₱{price_str}

Please consider restocking this product soon to avoid running out of stock.

This is an automated notification from the inventory management system.

Best regards,
BAGNOS MPC
"""
        
        # HTML version for better formatting
        html_message = format_html("""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background-color: #ff9800; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0; }}
                .content {{ background-color: #f9f9f9; padding: 20px; border: 1px solid #ddd; }}
                .product-info {{ background-color: white; padding: 15px; margin: 15px 0; border-left: 4px solid #ff9800; }}
                .product-info p {{ margin: 8px 0; }}
                .label {{ font-weight: bold; color: #555; }}
                .footer {{ text-align: center; padding: 20px; color: #777; font-size: 12px; }}
                .warning {{ color: #ff9800; font-weight: bold; }}
                .alert-box {{ background-color: #fff3cd; border: 2px solid #ffc107; padding: 15px; margin: 15px 0; border-radius: 5px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>⚠️ Low Stock Warning</h2>
                </div>
                <div class="content">
                    <p>Dear Admin and Staff,</p>
                    <div class="alert-box">
                        <p><strong>A product has reached its low stock threshold and requires attention.</strong></p>
                    </div>
                    
                    <div class="product-info">
                        <h3>Product Details:</h3>
                        <p><span class="label">Name:</span> {}</p>
                        <p><span class="label">Barcode:</span> {}</p>
                        <p><span class="label">Current Stock:</span> <span class="warning">{}</span></p>
                        <p><span class="label">Low Stock Threshold:</span> {}</p>
                        <p><span class="label">Stock Deficit:</span> <span class="warning">{} units needed</span></p>
                        <p><span class="label">Category:</span> {}</p>
                        <p><span class="label">Price:</span> ₱{}</p>
                    </div>
                    
                    <p>Please consider restocking this product soon to avoid running out of stock.</p>
                    <p>This is an automated notification from the inventory management system.</p>
                </div>
                <div class="footer">
                    <p>Best regards,<br>BAGNOS MPC</p>
                </div>
            </div>
        </body>
        </html>
        """, 
        product.name,
        product.barcode,
        product.stock_quantity,
        product.low_stock_threshold,
        stock_deficit,
        category_name,
        price_str
        )
        
        _send_email_async(subject, body, recipients, html_message)
        
        return True
    except Exception as e:
        logger.error(f'Failed to send low stock warning for product {product.id}: {str(e)}')
        return False


def _stock_alert_product_lines(products):
    """Plain-text and HTML rows for digest emails."""
    text_lines = []
    html_rows = []
    for product in products:
        category_name = product.category.name if product.category else 'Uncategorized'
        barcode = product.barcode or '—'
        text_lines.append(
            f"- {product.name} (barcode: {barcode}) | stock: {product.stock_quantity} | "
            f"threshold: {product.low_stock_threshold} | category: {category_name}"
        )
        html_rows.append(
            '<tr>'
            f'<td style="padding:8px;border-bottom:1px solid #eee;">{html_escape(product.name)}</td>'
            f'<td style="padding:8px;border-bottom:1px solid #eee;">{html_escape(str(barcode))}</td>'
            f'<td style="padding:8px;border-bottom:1px solid #eee;text-align:center;">{product.stock_quantity}</td>'
            f'<td style="padding:8px;border-bottom:1px solid #eee;text-align:center;">{product.low_stock_threshold}</td>'
            f'<td style="padding:8px;border-bottom:1px solid #eee;">{html_escape(category_name)}</td>'
            '</tr>'
        )
    return '\n'.join(text_lines), ''.join(html_rows)


def send_inventory_stock_alerts():
    """
    Email current low-stock and out-of-stock products to all staff and admin members.
    Used by the inventory products section "Email Stock Alerts" action.
    """
    from django.db.models import F
    from inventory.models import Product

    recipients = get_stock_alert_recipient_emails()
    if not recipients:
        return {
            'success': False,
            'error': 'No email addresses found for active staff or admin members.',
            'recipient_count': 0,
            'low_stock_count': 0,
            'out_of_stock_count': 0,
        }

    low_stock = list(
        Product.objects.filter(
            is_active=True,
            stock_quantity__gt=0,
            stock_quantity__lte=F('low_stock_threshold'),
        ).select_related('category').order_by('name')
    )
    out_of_stock = list(
        Product.objects.filter(
            is_active=True,
            stock_quantity=0,
        ).select_related('category').order_by('name')
    )

    if not low_stock and not out_of_stock:
        return {
            'success': False,
            'error': 'There are no low-stock or out-of-stock products to report.',
            'recipient_count': len(recipients),
            'low_stock_count': 0,
            'out_of_stock_count': 0,
        }

    low_text, low_html = _stock_alert_product_lines(low_stock)
    oos_text, oos_html = _stock_alert_product_lines(out_of_stock)

    subject = (
        f'⚠️ Inventory Stock Alerts: {len(low_stock)} low stock, '
        f'{len(out_of_stock)} out of stock'
    )
    body = f"""
Dear Admin and Staff,

Current inventory alerts that need restocking:

OUT OF STOCK ({len(out_of_stock)})
{oos_text or '- None'}

LOW STOCK ({len(low_stock)})
{low_text or '- None'}

Please restock these products as soon as possible.

This is an automated notification from the inventory management system.

Best regards,
BAGNOS MPC
"""

    table_head = (
        '<tr>'
        '<th style="padding:8px;text-align:left;border-bottom:2px solid #ddd;">Name</th>'
        '<th style="padding:8px;text-align:left;border-bottom:2px solid #ddd;">Barcode</th>'
        '<th style="padding:8px;text-align:center;border-bottom:2px solid #ddd;">Stock</th>'
        '<th style="padding:8px;text-align:center;border-bottom:2px solid #ddd;">Threshold</th>'
        '<th style="padding:8px;text-align:left;border-bottom:2px solid #ddd;">Category</th>'
        '</tr>'
    )
    oos_section = (
        f'<h3 style="color:#d32f2f;">Out of Stock ({len(out_of_stock)})</h3>'
        f'<table style="width:100%;border-collapse:collapse;background:#fff;">{table_head}{oos_html}</table>'
        if out_of_stock else
        '<h3 style="color:#d32f2f;">Out of Stock (0)</h3><p>None.</p>'
    )
    low_section = (
        f'<h3 style="color:#ff9800;">Low Stock ({len(low_stock)})</h3>'
        f'<table style="width:100%;border-collapse:collapse;background:#fff;">{table_head}{low_html}</table>'
        if low_stock else
        '<h3 style="color:#ff9800;">Low Stock (0)</h3><p>None.</p>'
    )
    html_message = f"""
    <html>
    <body style="font-family:Arial,sans-serif;line-height:1.6;color:#333;">
      <div style="max-width:720px;margin:0 auto;padding:20px;">
        <div style="background:#d32f2f;color:#fff;padding:20px;border-radius:5px 5px 0 0;text-align:center;">
          <h2 style="margin:0;">Inventory Stock Alerts</h2>
        </div>
        <div style="background:#f9f9f9;padding:20px;border:1px solid #ddd;">
          <p>Dear Admin and Staff,</p>
          <p>Current inventory alerts that need restocking:</p>
          {oos_section}
          {low_section}
          <p>Please restock these products as soon as possible.</p>
        </div>
        <p style="text-align:center;color:#777;font-size:12px;">Best regards,<br>BAGNOS MPC</p>
      </div>
    </body>
    </html>
    """

    try:
        _send_email_async(subject, body, recipients, html_message)
    except Exception as exc:
        logger.error('Failed to send inventory stock alerts: %s', exc)
        return {
            'success': False,
            'error': 'Could not send the stock alert email. Please try again.',
            'recipient_count': len(recipients),
            'low_stock_count': len(low_stock),
            'out_of_stock_count': len(out_of_stock),
        }

    logger.info(
        'Queued inventory stock alerts to %s staff/admin recipient(s) '
        '(%s low stock, %s out of stock)',
        len(recipients),
        len(low_stock),
        len(out_of_stock),
    )
    return {
        'success': True,
        'message': (
            f'Stock alerts sent to {len(recipients)} staff/admin recipient'
            f'{"s" if len(recipients) != 1 else ""}. '
            f'{len(out_of_stock)} out of stock, {len(low_stock)} low stock.'
        ),
        'recipient_count': len(recipients),
        'low_stock_count': len(low_stock),
        'out_of_stock_count': len(out_of_stock),
        'recipients': recipients,
    }


def reset_out_of_stock_attempts(product):
    """
    Reset the attempt counter for a product when stock is added.
    
    Args:
        product: Product instance
    """
    from django.core.cache import cache
    
    # Clear attempt tracking cache keys
    cache_key = f'out_of_stock_attempts_{product.id}'
    last_notification_key = f'out_of_stock_last_notification_{product.id}'
    
    # Delete the cache entries
    cache.delete(cache_key)
    cache.delete(last_notification_key)


def track_out_of_stock_attempt(product):
    """
    Track when a customer tries to access an out-of-stock product.
    Sends notification email every 5 attempts (5, 10, 15, 20, etc.).
    
    Args:
        product: Product instance that is out of stock
    
    Returns:
        tuple: (attempt_count, notification_sent)
    """
    if product.stock_quantity > 0:
        # Product is not out of stock, don't track
        return (0, False)
    
    # Cache key for tracking attempts
    cache_key = f'out_of_stock_attempts_{product.id}'
    last_notification_key = f'out_of_stock_last_notification_{product.id}'
    
    # Get current attempt count
    attempt_count = cache.get(cache_key, 0)
    attempt_count += 1
    
    # Store updated count (expires in 24 hours)
    cache.set(cache_key, attempt_count, 86400)
    
    # Get the last notification count (to know when we last sent)
    last_notification_count = cache.get(last_notification_key, 0)
    
    # Send notification every 5 attempts (5, 10, 15, 20, etc.)
    # Check if we've crossed a multiple of 5 threshold
    notification_sent = False
    if attempt_count >= 5 and (attempt_count // 5) > (last_notification_count // 5):
        send_failed_access_notification(product, attempt_count)
        # Update last notification count
        cache.set(last_notification_key, attempt_count, 86400)
        notification_sent = True
    
    return (attempt_count, notification_sent)


def send_failed_access_notification(product, attempt_count):
    """
    Send email notification when customers try to access out-of-stock product 5 times.
    
    Args:
        product: Product instance that is out of stock
        attempt_count: Number of failed attempts
    """
    try:
        recipients = get_stock_alert_recipient_emails()
        if not recipients:
            logger.warning(
                'No staff/admin emails for failed-access alert (product %s)',
                product.id,
            )
            return False
        
        # Prepare email content
        subject = f'⚠️ High Demand Alert: {product.name} (Out of Stock)'
        
        # Format price as string
        price_str = f'{float(product.price):.2f}'
        category_name = product.category.name if product.category else 'Uncategorized'
        
        # Build email body
        body = f"""
Dear Admin and Staff,

Multiple customers have attempted to access a product that is currently out of stock.

Product Details:
- Name: {product.name}
- Barcode: {product.barcode}
- Current Stock: {product.stock_quantity}
- Low Stock Threshold: {product.low_stock_threshold}
- Category: {category_name}
- Price: ₱{price_str}

Alert Details:
- Failed Access Attempts: {attempt_count} times
- Status: Product is out of stock

This indicates high customer demand for this product. Please restock immediately to avoid losing sales opportunities.

This is an automated notification from the inventory management system.

Best regards,
BAGNOS MPC
"""
        
        # HTML version for better formatting
        html_message = format_html("""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background-color: #ff9800; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0; }}
                .content {{ background-color: #f9f9f9; padding: 20px; border: 1px solid #ddd; }}
                .product-info {{ background-color: white; padding: 15px; margin: 15px 0; border-left: 4px solid #ff9800; }}
                .product-info p {{ margin: 8px 0; }}
                .label {{ font-weight: bold; color: #555; }}
                .footer {{ text-align: center; padding: 20px; color: #777; font-size: 12px; }}
                .warning {{ color: #d32f2f; font-weight: bold; }}
                .alert-box {{ background-color: #fff3cd; border: 2px solid #ffc107; padding: 15px; margin: 15px 0; border-radius: 5px; }}
                .attempt-count {{ font-size: 24px; font-weight: bold; color: #ff9800; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>⚠️ High Demand Alert</h2>
                </div>
                <div class="content">
                    <p>Dear Admin and Staff,</p>
                    <div class="alert-box">
                        <p><strong>Multiple customers have attempted to access a product that is currently out of stock.</strong></p>
                        <p class="attempt-count">Failed Attempts: {}</p>
                    </div>
                    
                    <div class="product-info">
                        <h3>Product Details:</h3>
                        <p><span class="label">Name:</span> {}</p>
                        <p><span class="label">Barcode:</span> {}</p>
                        <p><span class="label">Current Stock:</span> <span class="warning">{}</span></p>
                        <p><span class="label">Low Stock Threshold:</span> {}</p>
                        <p><span class="label">Category:</span> {}</p>
                        <p><span class="label">Price:</span> ₱{}</p>
                    </div>
                    
                    <p><strong>This indicates high customer demand for this product.</strong> Please restock immediately to avoid losing sales opportunities.</p>
                    <p>This is an automated notification from the inventory management system.</p>
                </div>
                <div class="footer">
                    <p>Best regards,<br>BAGNOS MPC</p>
                </div>
            </div>
        </body>
        </html>
        """, 
        attempt_count,
        product.name,
        product.barcode,
        product.stock_quantity,
        product.low_stock_threshold,
        category_name,
        price_str
        )
        
        _send_email_async(subject, body, recipients, html_message)
        
        return True
    except Exception as e:
        logger.error(f'Failed to send failed access notification for product {product.id}: {str(e)}')
        return False


GIVEAWAY_STOCK_NOTE_PREFIX = 'Giveaway —'


def giveaway_stock_note(username: str, extra_notes: str = '') -> str:
    """Notes stored on stock-out rows when staff record a giveaway."""
    base = f'{GIVEAWAY_STOCK_NOTE_PREFIX} recorded by {username}'
    extra = (extra_notes or '').strip()
    return f'{base}: {extra}' if extra else base


def parse_giveaway_stock_notes(notes: str) -> dict:
    """Split stored giveaway notes into recorder username and optional detail."""
    import re

    text = (notes or '').strip()
    recorded_by = ''
    extra_notes = ''
    match = re.match(
        r'^Giveaway\s*[—\-]\s*recorded by\s+([^:]+?)(?:\s*:\s*(.*))?$',
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if match:
        recorded_by = (match.group(1) or '').strip()
        extra_notes = (match.group(2) or '').strip()
    return {
        'recorded_by': recorded_by,
        'extra_notes': extra_notes,
        'full_notes': text,
    }


def giveaway_stock_transactions_qs():
    """Stock-out rows created via Record Giveaway."""
    from .models import StockTransaction

    return StockTransaction.objects.filter(
        transaction_type='out',
        notes__icontains='Giveaway',
    ).select_related('product', 'product__category')


def is_giveaway_stock_transaction(stock_txn) -> bool:
    return (
        getattr(stock_txn, 'transaction_type', None) == 'out'
        and 'giveaway' in (getattr(stock_txn, 'notes', '') or '').lower()
    )


def serialize_giveaway_stock_transaction(stock_txn) -> dict:
    from django.utils import timezone

    parsed = parse_giveaway_stock_notes(stock_txn.notes)
    created = timezone.localtime(stock_txn.created_at)
    return {
        'id': stock_txn.id,
        'product_id': stock_txn.product_id,
        'product_name': stock_txn.product.name,
        'product_barcode': stock_txn.product.barcode or '',
        'quantity': stock_txn.quantity,
        'stock_after': stock_txn.stock_after,
        'current_stock': stock_txn.product.stock_quantity,
        'notes': stock_txn.notes,
        'recorded_by': parsed['recorded_by'],
        'extra_notes': parsed['extra_notes'],
        'created_at': created.strftime('%Y-%m-%d %H:%M:%S'),
        'created_at_display': created.strftime('%b %d, %Y %I:%M %p'),
    }


def _giveaway_stock_filter(related_prefix=''):
    """Match Record Giveaway stock-outs (em dash, hyphen, or plain text)."""
    from django.db.models import Q

    prefix = f'{related_prefix}__' if related_prefix else ''
    return Q(
        **{
            f'{prefix}stock_transactions__transaction_type': 'out',
            f'{prefix}stock_transactions__notes__icontains': 'Giveaway',
        }
    )


def annotate_giveaway_units_given(queryset):
    """Add giveaway_units_given: total units distributed via Record Giveaway."""
    from django.db.models import DecimalField, Sum, Value
    from django.db.models.functions import Coalesce

    qty_field = DecimalField(max_digits=14, decimal_places=3)
    return queryset.annotate(
        giveaway_units_given=Coalesce(
            Sum('stock_transactions__quantity', filter=_giveaway_stock_filter()),
            Value(0, output_field=qty_field),
            output_field=qty_field,
        ),
    )


def giveaway_totals_by_product_ids(product_ids):
    """Total units distributed via Record Giveaway, keyed by product id."""
    if not product_ids:
        return {}
    from decimal import Decimal
    from django.db.models import Sum
    from .models import StockTransaction

    rows = (
        StockTransaction.objects.filter(
            product_id__in=product_ids,
            transaction_type='out',
            notes__icontains='Giveaway',
        )
        .values('product_id')
        .annotate(total=Sum('quantity'))
    )
    return {row['product_id']: Decimal(str(row['total'] or 0)) for row in rows}


def get_giveaway_summary_for_period(date_from, date_to=None):
    """
    Aggregated giveaway product summary for a single date or date range.
    Uses StockTransaction rows recorded via Record Giveaway (notes contain 'Giveaway').
    """
    from datetime import datetime, timedelta
    from decimal import Decimal

    from django.db.models import Count, Sum
    from django.utils import timezone

    from .models import StockTransaction

    if date_to is None:
        date_to = date_from

    # Store-local [start, end) — same convention as Generate Report / dashboard
    tz = timezone.get_current_timezone()
    start_datetime = timezone.make_aware(
        datetime(date_from.year, date_from.month, date_from.day, 0, 0, 0),
        tz,
    )
    end_day = date_to + timedelta(days=1)
    end_datetime = timezone.make_aware(
        datetime(end_day.year, end_day.month, end_day.day, 0, 0, 0),
        tz,
    )
    base_qs = StockTransaction.objects.filter(
        transaction_type='out',
        notes__icontains='Giveaway',
        created_at__gte=start_datetime,
        created_at__lt=end_datetime,
    )

    agg = base_qs.aggregate(
        total_units=Sum('quantity'),
        record_count=Count('id'),
    )

    by_product = list(
        base_qs.values('product__name', 'product__barcode', 'product__price')
        .annotate(quantity_given=Sum('quantity'))
        .order_by('-quantity_given')
    )

    products = []
    total_est_value = Decimal('0.00')
    for row in by_product:
        qty = int(row['quantity_given'] or 0)
        price = Decimal(str(row['product__price'] or '0'))
        est_value = price * qty
        total_est_value += est_value
        products.append({
            'name': row['product__name'],
            'barcode': row['product__barcode'],
            'price': price,
            'quantity_given': qty,
            'est_value': est_value,
        })

    return {
        'products': products,
        'total_units': int(agg['total_units'] or 0),
        'record_count': int(agg['record_count'] or 0),
        'total_est_value': total_est_value,
    }


def product_displays_as_giveaway_free(product) -> bool:
    """Show/charge FREE only when units were recorded via Record Giveaway."""
    units = getattr(product, 'giveaway_units_given', None)
    if units is None:
        totals = giveaway_totals_by_product_ids([product.pk])
        units = totals.get(product.pk, 0)
    return int(units or 0) > 0


def request_can_manage_giveaways(request) -> bool:
    """Admin, cashier, or staff (Django user) may record and configure giveaways."""
    from login_helper import is_cashier_or_admin

    user = getattr(request, 'user', None)
    return bool(user and user.is_authenticated and is_cashier_or_admin(user))


def ensure_product_giveaway_active(product):
    """Ensure an active product has a giveaway profile (all products are eligible)."""
    from .models import GiveawayProduct

    if not product.is_active:
        return
    GiveawayProduct.objects.update_or_create(
        product=product,
        defaults={'is_active': True},
    )


def set_product_giveaway(product, is_giveaway: bool = True):
    """Backward-compatible alias; all active products remain giveaway-eligible."""
    ensure_product_giveaway_active(product)

