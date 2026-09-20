"""Piece vs kilogram sale units and quantity helpers."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

UNIT_PIECE = 'piece'
UNIT_KILO = 'kilo'
UNIT_CHOICES = [
    (UNIT_PIECE, 'By piece'),
    (UNIT_KILO, 'By kilogram'),
]

KILO_QTY_STEP = Decimal('0.001')
PIECE_QTY_STEP = Decimal('1')


def is_kilo_product(product) -> bool:
    return getattr(product, 'unit_type', UNIT_PIECE) == UNIT_KILO


def unit_suffix(unit_type) -> str:
    return 'kg' if unit_type == UNIT_KILO else 'pcs'


def retail_unit_label(unit_type) -> str:
    return 'Kilogram' if unit_type == UNIT_KILO else 'Piece'


def price_unit_label(unit_type) -> str:
    return 'per kg' if unit_type == UNIT_KILO else 'per piece'


def qty_step(unit_type) -> Decimal:
    return KILO_QTY_STEP if unit_type == UNIT_KILO else PIECE_QTY_STEP


def as_qty(value, default=None):
    if value is None or value == '':
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def quantize_qty(value, unit_type):
    qty = as_qty(value, Decimal('0'))
    if qty is None:
        qty = Decimal('0')
    step = qty_step(unit_type)
    return qty.quantize(step, rounding=ROUND_HALF_UP)


def parse_stock_qty(value, unit_type, *, default=0):
    """Parse a dashboard/API stock quantity. Raises ValueError on invalid input."""
    if value is None or value == '':
        return quantize_qty(default, unit_type)
    try:
        qty = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError('Invalid stock quantity') from exc
    if qty < 0:
        raise ValueError('Stock quantity cannot be negative')
    quantized = quantize_qty(qty, unit_type)
    if unit_type != UNIT_KILO and qty != qty.to_integral_value():
        raise ValueError('Piece quantities must be whole numbers')
    return quantized


def parse_sale_qty(value, product):
    """Parse a kiosk/cart sale quantity for this product."""
    unit_type = getattr(product, 'unit_type', UNIT_PIECE) if product is not None else UNIT_PIECE
    qty = as_qty(value)
    if qty is None:
        raise ValueError('Invalid quantity')
    if qty <= 0:
        raise ValueError('Quantity must be greater than zero')
    quantized = quantize_qty(qty, unit_type)
    if quantized <= 0:
        raise ValueError('Quantity must be greater than zero')
    if unit_type != UNIT_KILO and qty != qty.to_integral_value():
        raise ValueError('Piece quantities must be whole numbers')
    return quantized


def qty_json(value):
    """JSON-safe number: int for whole quantities, float otherwise."""
    qty = as_qty(value, Decimal('0'))
    if qty is None:
        return 0
    if qty == qty.to_integral_value():
        return int(qty)
    return float(qty)


def format_qty_display(value, unit_type, *, with_unit=True):
    qty = quantize_qty(value or 0, unit_type)
    if unit_type == UNIT_KILO:
        text = format(qty.normalize(), 'f')
        if '.' in text:
            text = text.rstrip('0').rstrip('.')
        if text in ('', '-'):
            text = '0'
        return f'{text} kg' if with_unit else text
    text = str(int(qty))
    if not with_unit:
        return text
    return f'{text} pc' if int(qty) == 1 else f'{text} pcs'


def format_product_qty(product, value, *, with_unit=True):
    unit_type = getattr(product, 'unit_type', UNIT_PIECE) if product is not None else UNIT_PIECE
    return format_qty_display(value, unit_type, with_unit=with_unit)
