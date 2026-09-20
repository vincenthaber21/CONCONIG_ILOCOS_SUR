"""Kiosk / checkout helpers for ProductSaleUnit (piece vs wholesale)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db.models import Q

from .models import Product, ProductSaleUnit
from .pricing import (
    discounts_by_product_ids,
    fifo_line_gross,
    fifo_weighted_unit_price,
    price_payload_for_product,
    unit_price_after_discounts,
)
from .units import is_kilo_product, qty_json, retail_unit_label


def cart_line_key(product_id, sale_unit_id=None) -> str:
    return f'{product_id}:{sale_unit_id or 0}'


def cart_item_units_per_package(item: dict) -> int:
    try:
        upp = int(item.get('units_per_package') or 1)
    except (TypeError, ValueError):
        upp = 1
    return max(1, upp)


def cart_item_stock_pieces(item: dict):
    try:
        qty = Decimal(str(item.get('quantity') or 0))
    except (TypeError, ValueError, InvalidOperation):
        return Decimal('0')
    if qty <= 0:
        return Decimal('0')
    return qty * Decimal(cart_item_units_per_package(item))


def aggregate_cart_stock_pieces(items: list[dict]) -> dict[int, Decimal]:
    demand: dict[int, Decimal] = {}
    for item in items:
        pid = item.get('product_id')
        if pid is None:
            continue
        demand[int(pid)] = demand.get(int(pid), Decimal('0')) + cart_item_stock_pieces(item)
    return demand


def resolve_scan_barcode(barcode: str):
    """
    Resolve a scanned barcode to (product, sale_unit).
    Sale units are checked first so wholesale barcodes work.
    """
    code = (barcode or '').strip()
    if not code:
        return None, None

    unit = (
        ProductSaleUnit.objects.filter(
            barcode=code,
            is_active=True,
            product__is_active=True,
        )
        .select_related('product', 'product__discount_group', 'product__tax_rate')
        .first()
    )
    if unit:
        return unit.product, unit

    product = (
        Product.objects.filter(is_active=True, barcode=code)
        .select_related('discount_group', 'tax_rate')
        .first()
    )
    return product, None


def get_sale_unit_for_cart_item(product: Product, item: dict):
    sale_unit_id = item.get('sale_unit_id')
    if not sale_unit_id:
        return None
    try:
        sale_unit_id = int(sale_unit_id)
    except (TypeError, ValueError):
        return None
    return (
        product.sale_units.filter(id=sale_unit_id, is_active=True)
        .first()
    )


def sellable_quantity(product: Product, sale_unit: ProductSaleUnit | None):
    if sale_unit and sale_unit.sale_mode == ProductSaleUnit.SALE_MODE_WHOLESALE:
        pack = max(1, sale_unit.units_per_package)
        return qty_json(Decimal(str(product.stock_quantity or 0)) // pack)
    return qty_json(product.stock_quantity)


def kiosk_product_tax_payload(product: Product) -> dict:
    tr = product.tax_rate
    if tr:
        return {
            'tax_rate': float(tr.rate / 100),
            'tax_type': tr.tax_type,
            'tax_name': tr.name,
        }
    return {
        'tax_rate': None,
        'tax_type': None,
        'tax_name': None,
    }


def _price_payload_extras(pf: dict) -> dict:
    extras = {}
    for key in ('old_stock_qty', 'old_stock_price', 'new_stock_qty', 'new_stock_price', 'stock_tier'):
        if key in pf:
            extras[key] = pf[key]
    return extras


def kiosk_line_pricing(
    product: Product,
    quantity,
    *,
    sale_unit: ProductSaleUnit | None = None,
    discount_list=None,
    member=None,
    segment_rules=None,
) -> dict:
    """Unit + line pricing for one cart row (piece, kilo, or wholesale box)."""
    qty = Decimal(str(quantity or 0))
    if qty <= 0:
        qty = Decimal('1')

    if sale_unit and sale_unit.sale_mode == ProductSaleUnit.SALE_MODE_WHOLESALE:
        unit_price = Decimal(str(sale_unit.price))
        regular = unit_price
        line_gross = (unit_price * qty).quantize(Decimal('0.01'))
        pf = {'price': str(unit_price), 'regular_price': str(regular)}
    else:
        base_regular = fifo_weighted_unit_price(product, qty)
        unit_price, regular, _meta = unit_price_after_discounts(
            product,
            discount_list=discount_list or [],
            member=member,
            segment_rules=segment_rules,
            regular=base_regular,
        )
        line_gross = (Decimal(str(unit_price)) * qty).quantize(Decimal('0.01'))
        pf = price_payload_for_product(
            product,
            discount_list=discount_list or [],
            member=member,
            segment_rules=segment_rules,
        )

    line = {
        'price': pf.get('price') or str(unit_price),
        'unit_price': str(unit_price),
        'regular_price': pf.get('regular_price') or str(regular),
        'line_gross': str(line_gross),
        'fifo_line_gross': str(fifo_line_gross(product, qty)),
        **_price_payload_extras(pf),
    }
    if pf.get('discount_name'):
        line['discount_name'] = pf['discount_name']
    return line


def kiosk_scan_product_payload(
    product: Product,
    sale_unit: ProductSaleUnit | None,
    *,
    discount_list=None,
    member=None,
    segment_rules=None,
) -> dict:
    """JSON payload for kiosk scan / search add-to-cart."""
    is_wholesale = bool(
        sale_unit and sale_unit.sale_mode == ProductSaleUnit.SALE_MODE_WHOLESALE
    )
    stock = sellable_quantity(product, sale_unit)
    units_per_package = sale_unit.units_per_package if sale_unit else 1
    scanned_barcode = sale_unit.barcode if sale_unit else product.barcode

    if is_wholesale:
        pricing = kiosk_line_pricing(
            product,
            1,
            sale_unit=sale_unit,
            discount_list=discount_list,
            member=member,
            segment_rules=segment_rules,
        )
        display_name = f'{product.name} ({sale_unit.unit_label})'
    else:
        pricing = price_payload_for_product(
            product,
            discount_list=discount_list or [],
            member=member,
            segment_rules=segment_rules,
        )
        display_name = product.name

    price = pricing.get('price') or pricing.get('unit_price')
    regular_price = pricing.get('regular_price') or price

    payload = {
        'id': product.id,
        'name': display_name,
        'product_name': product.name,
        'barcode': scanned_barcode,
        'price': str(price),
        'regular_price': str(regular_price),
        'discount_group': product.discount_group_code,
        'image': product.image.url if product.image else None,
        'stock': stock,
        'units_per_package': units_per_package,
        'sale_unit_id': sale_unit.id if sale_unit else None,
        'sale_mode': sale_unit.sale_mode if sale_unit else ProductSaleUnit.SALE_MODE_RETAIL,
        'unit_label': sale_unit.unit_label if sale_unit else retail_unit_label(
            getattr(product, 'unit_type', None)
        ),
        'unit_type': getattr(product, 'unit_type', 'piece') or 'piece',
        'is_kilo': is_kilo_product(product),
        'is_wholesale': is_wholesale,
        'cart_line_key': cart_line_key(product.id, sale_unit.id if sale_unit else None),
        **_price_payload_extras(pricing),
        **kiosk_product_tax_payload(product),
    }
    if pricing.get('discount_name'):
        payload['discount_name'] = pricing['discount_name']
    return payload


def resolve_product_sale_unit(product: Product, sale_unit_id=None):
    """Return the active sale unit for kiosk selection, or retail default."""
    if sale_unit_id not in (None, '', 0, '0'):
        try:
            sale_unit_id = int(sale_unit_id)
        except (TypeError, ValueError):
            return None
        return product.sale_units.filter(id=sale_unit_id, is_active=True).first()

    retail_unit = (
        product.sale_units.filter(
            sale_mode=ProductSaleUnit.SALE_MODE_RETAIL,
            is_active=True,
        )
        .order_by('id')
        .first()
    )
    return retail_unit


def kiosk_payload_sale_unit(product: Product, sale_unit: ProductSaleUnit | None):
    """
    When a product is scanned by its main barcode (no wholesale unit),
    attach the retail ProductSaleUnit when one exists so cart lines and
    the Sell-as dropdown stay in sync.
    """
    if sale_unit is not None:
        return sale_unit
    return resolve_product_sale_unit(product, None)


def product_sale_unit_options(
    product: Product,
    *,
    discount_list=None,
    member=None,
    segment_rules=None,
) -> list[dict]:
    """All kiosk-selectable sale units for a product (piece + wholesale)."""
    options: list[dict] = []
    has_retail_unit = False

    for unit in product.sale_units.filter(is_active=True).order_by('sale_mode', 'id'):
        if unit.sale_mode == ProductSaleUnit.SALE_MODE_RETAIL:
            has_retail_unit = True
        options.append(
            kiosk_scan_product_payload(
                product,
                unit,
                discount_list=discount_list,
                member=member,
                segment_rules=segment_rules,
            )
        )

    if not has_retail_unit:
        options.insert(
            0,
            kiosk_scan_product_payload(
                product,
                None,
                discount_list=discount_list,
                member=member,
                segment_rules=segment_rules,
            ),
        )

    return options


def sale_units_search_queryset(q: str, active_product_qs):
    """Wholesale / sale-unit rows matching barcode search text."""
    return (
        ProductSaleUnit.objects.filter(
            is_active=True,
            product__is_active=True,
            product__in=active_product_qs,
        )
        .filter(Q(barcode__icontains=q) | Q(unit_label__icontains=q))
        .select_related('product', 'product__discount_group', 'product__tax_rate')
        .order_by('product__name', 'sale_mode')[:25]
    )
