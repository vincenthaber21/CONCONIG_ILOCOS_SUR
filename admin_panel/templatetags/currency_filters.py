from django import template
from django.contrib.messages import get_messages
from members.utils import mask_rfid as mask_rfid_value

register = template.Library()


@register.simple_tag(takes_context=True)
def deduped_messages(context):
    """
    Return flash messages with duplicates removed (same level + same text).
    Consumes the request message storage. Use at most once per page.
    """
    request = context.get("request")
    if request is None:
        return []

    collected = list(get_messages(request))
    seen = set()
    unique = []
    for m in collected:
        key = (m.level, str(m))
        if key in seen:
            continue
        seen.add(key)
        unique.append(m)
    return unique


@register.filter(name='currency')
def currency(value):
    """
    Format a number as currency with thousand separators.
    Example: 1234.56 -> "1,234.56"
    """
    try:
        # Convert to float if it's not already
        num = float(value)
        # Format with 2 decimal places and thousand separators
        return f"{num:,.2f}"
    except (ValueError, TypeError):
        return value


@register.filter(name='stock_qty')
def stock_qty(value, unit_type='piece'):
    """Format on-hand quantity as pieces or kilograms."""
    from inventory.units import format_qty_display
    return format_qty_display(value, unit_type or 'piece', with_unit=True)


@register.filter(name='mask_rfid')
def mask_rfid(value):
    """
    Mask RFID card number for security purposes.
    Shows only the last 4 digits, prefixed with asterisks.
    Example: '0008265033' -> '******5033'
    """
    return mask_rfid_value(value)
