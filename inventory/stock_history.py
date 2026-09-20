"""
Helpers for recording ProductStockHistory entries.

Captures stock tiers (old/new/total) and selling/buying prices so the inventory
dashboard can show an item's stock and price timeline.
"""
import logging
from decimal import Decimal

logger = logging.getLogger(__name__)


def _money(value):
    if value is None or value == '':
        return None
    return Decimal(str(value)).quantize(Decimal('0.01'))


def _qty(value):
    if value is None or value == '':
        return Decimal('0')
    return Decimal(str(value))


def capture_stock_snapshot(product):
    """
    Return a fresh snapshot of a product's stock and prices:

    ``{
        'old': int, 'new': int, 'total': int,
        'unit_price': Decimal|None, 'cost': Decimal|None,
        'old_stock_price': Decimal|None, 'new_stock_price': Decimal|None,
    }``
    """
    from .models import ProductStockBatch, Product

    old_qty = 0
    new_qty = 0
    old_price = None
    new_price = None
    for batch in ProductStockBatch.objects.filter(product=product).only(
        'tier', 'quantity', 'unit_price',
    ):
        if batch.tier == ProductStockBatch.TIER_OLD:
            old_qty = batch.quantity
            old_price = _money(batch.unit_price)
        elif batch.tier == ProductStockBatch.TIER_NEW:
            new_qty = batch.quantity
            new_price = _money(batch.unit_price)

    row = (
        Product.objects.filter(pk=product.pk)
        .values('stock_quantity', 'price', 'cost')
        .first()
    )
    if row is None:
        total = getattr(product, 'stock_quantity', old_qty + new_qty) or 0
        unit_price = _money(getattr(product, 'price', None))
        cost = _money(getattr(product, 'cost', None))
    else:
        total = row['stock_quantity'] or 0
        unit_price = _money(row['price'])
        cost = _money(row['cost'])

    return {
        'old': old_qty or 0,
        'new': new_qty or 0,
        'total': total or 0,
        'unit_price': unit_price,
        'cost': cost,
        'old_stock_price': old_price,
        'new_stock_price': new_price,
    }


def _stock_unchanged(before, after):
    return (
        before.get('old') == after.get('old')
        and before.get('new') == after.get('new')
        and before.get('total') == after.get('total')
    )


def _price_unchanged(before, after):
    return (
        before.get('unit_price') == after.get('unit_price')
        and before.get('cost') == after.get('cost')
        and before.get('old_stock_price') == after.get('old_stock_price')
        and before.get('new_stock_price') == after.get('new_stock_price')
    )


def record_stock_history(
    product,
    change_type,
    before,
    *,
    after=None,
    note='',
    user=None,
    quantity_sold=0,
    skip_if_unchanged=True,
):
    """
    Persist a ProductStockHistory row including stock and price before/after.

    When stock is unchanged but prices changed, the change_type is upgraded to
    ``price`` (unless the caller already used created/sale/etc.).
    History logging never raises — failures are logged and swallowed.
    """
    from .models import ProductStockHistory

    try:
        if before is None:
            before = {
                'old': 0, 'new': 0, 'total': 0,
                'unit_price': None, 'cost': None,
                'old_stock_price': None, 'new_stock_price': None,
            }
        if after is None:
            after = capture_stock_snapshot(product)

        stock_same = _stock_unchanged(before, after)
        price_same = _price_unchanged(before, after)

        if skip_if_unchanged and stock_same and price_same and not quantity_sold:
            return None

        # Prefer an explicit "price" label when only prices moved.
        resolved_type = change_type
        if (
            stock_same
            and not price_same
            and change_type in (
                ProductStockHistory.CHANGE_EDIT,
                ProductStockHistory.CHANGE_ADJUSTMENT,
            )
        ):
            resolved_type = ProductStockHistory.CHANGE_PRICE

        changed_by = user if getattr(user, 'is_authenticated', False) else None

        return ProductStockHistory.objects.create(
            product=product,
            change_type=resolved_type,
            old_stock_before=before.get('old', 0),
            old_stock_after=after.get('old', 0),
            new_stock_before=before.get('new', 0),
            new_stock_after=after.get('new', 0),
            total_before=before.get('total', 0),
            total_after=after.get('total', 0),
            quantity_sold=quantity_sold or 0,
            unit_price_before=before.get('unit_price'),
            unit_price=after.get('unit_price', getattr(product, 'price', None)),
            cost_before=before.get('cost'),
            cost=after.get('cost', getattr(product, 'cost', None)),
            old_stock_price_before=before.get('old_stock_price'),
            old_stock_price_after=after.get('old_stock_price'),
            new_stock_price_before=before.get('new_stock_price'),
            new_stock_price_after=after.get('new_stock_price'),
            note=(note or '')[:255],
            changed_by=changed_by,
        )
    except Exception:  # pragma: no cover - audit logging must never break flows
        logger.exception('Failed to record stock history for product %s', getattr(product, 'pk', '?'))
        return None


def _close_purchase_period(period, ended_at):
    if period is None:
        return None
    period['period_end'] = ended_at
    buy = period['buying_price'] or Decimal('0.00')
    qty = _qty(period['qty_purchased'] or 0)
    period['buy_value'] = (buy * qty).quantize(Decimal('0.01'))
    return period


def _product_export_meta(product):
    name = getattr(product, 'name', '') or ''
    barcode = getattr(product, 'barcode', '') or ''
    category = ''
    if getattr(product, 'category_id', None) and getattr(product, 'category', None):
        category = product.category.name or ''
    return name, barcode, category or 'Uncategorized'


def build_product_history_ledger_rows(product, history_entries=None):
    """
    Event-level product history for easy viewing.

    Separates purchases (stock in / buying) from sales (stock out / selling):
    - PURCHASE — created, restock, refund restock, positive adjustments
    - SALE — sold units with selling price and sale amount
    - PRICE — selling/buying price changes with no stock movement
    - ADJUSTMENT — other stock edits
    """
    from .models import ProductStockBatch, ProductStockHistory

    if history_entries is None:
        history_entries = list(
            ProductStockHistory.objects
            .filter(product=product)
            .order_by('created_at', 'id')
        )

    name, barcode, category = _product_export_meta(product)

    def _row(**extra):
        row = {
            'product_id': product.pk,
            'name': name,
            'barcode': barcode,
            'category': category,
            'event_type': 'OTHER',
            'description': '',
            'qty': 0,
            'buying_price': None,
            'buying_value': None,
            'selling_price': None,
            'sale_value': None,
            'stock_before': None,
            'stock_after': None,
            'created_at': None,
            'note': '',
        }
        row.update(extra)
        return row

    if not history_entries:
        rows = []
        batches = list(
            ProductStockBatch.objects
            .filter(product=product, quantity__gt=0)
            .order_by('tier')
        )
        if batches:
            for batch in batches:
                buy = _money(batch.cost) or Decimal('0.00')
                sell = _money(batch.unit_price) or Decimal('0.00')
                qty = _qty(batch.quantity or 0)
                rows.append(_row(
                    event_type='PURCHASE',
                    description=f'Current {batch.get_tier_display()} on hand',
                    qty=qty,
                    buying_price=buy,
                    buying_value=(buy * qty).quantize(Decimal('0.01')),
                    selling_price=sell,
                    stock_after=qty,
                    created_at=getattr(batch, 'updated_at', None) or getattr(batch, 'created_at', None),
                    note='No history yet — showing current stock',
                ))
            return rows

        buy = _money(getattr(product, 'cost', None)) or Decimal('0.00')
        sell = _money(getattr(product, 'price', None)) or Decimal('0.00')
        qty = _qty(getattr(product, 'stock_quantity', 0) or 0)
        return [_row(
            event_type='PURCHASE',
            description='Current stock on hand',
            qty=qty,
            buying_price=buy,
            buying_value=(buy * qty).quantize(Decimal('0.01')),
            selling_price=sell,
            stock_after=qty,
            note='No history yet — showing current stock',
        )]

    purchase_types = {
        ProductStockHistory.CHANGE_CREATED,
        ProductStockHistory.CHANGE_RESTOCK,
        ProductStockHistory.CHANGE_REFUND,
    }
    rows = []

    for entry in history_entries:
        when = entry.created_at
        buy = _money(entry.cost)
        buy_before = _money(entry.cost_before)
        sell = _money(entry.unit_price)
        sell_before = _money(entry.unit_price_before)
        delta = _qty(entry.total_after or 0) - _qty(entry.total_before or 0)
        sold = _qty(entry.quantity_sold or 0)
        buy_changed = buy_before is not None and buy is not None and buy_before != buy
        sell_changed = sell_before is not None and sell is not None and sell_before != sell

        if entry.change_type == ProductStockHistory.CHANGE_SALE or sold > 0:
            qty = sold if sold > 0 else abs(delta)
            unit_sell = sell if sell is not None else sell_before
            sale_value = None
            if unit_sell is not None and qty:
                sale_value = (unit_sell * Decimal(qty)).quantize(Decimal('0.01'))
            rows.append(_row(
                event_type='SALE',
                description=f'Sold {qty} unit{"s" if qty != 1 else ""}',
                qty=qty,
                buying_price=buy if buy is not None else buy_before,
                selling_price=unit_sell,
                sale_value=sale_value,
                stock_before=entry.total_before,
                stock_after=entry.total_after,
                created_at=when,
                note=entry.note or '',
            ))
            continue

        if entry.change_type in purchase_types and delta > 0:
            unit_buy = buy if buy is not None else buy_before
            buy_value = None
            if unit_buy is not None:
                buy_value = (unit_buy * Decimal(delta)).quantize(Decimal('0.01'))
            label = {
                ProductStockHistory.CHANGE_CREATED: 'Product created / purchased',
                ProductStockHistory.CHANGE_RESTOCK: 'Restocked / purchased',
                ProductStockHistory.CHANGE_REFUND: 'Refund restocked',
            }.get(entry.change_type, 'Purchased')
            rows.append(_row(
                event_type='PURCHASE',
                description=f'{label} +{delta} unit{"s" if delta != 1 else ""}',
                qty=delta,
                buying_price=unit_buy,
                buying_value=buy_value,
                selling_price=sell if sell is not None else sell_before,
                stock_before=entry.total_before,
                stock_after=entry.total_after,
                created_at=when,
                note=entry.note or '',
            ))
            continue

        if entry.change_type == ProductStockHistory.CHANGE_PRICE or (
            delta == 0 and (buy_changed or sell_changed)
        ):
            parts = []
            if sell_changed:
                if sell_before is not None and sell is not None:
                    parts.append(f'Selling ₱{sell_before:,.2f} to ₱{sell:,.2f}')
                elif sell is not None:
                    parts.append(f'Selling set to ₱{sell:,.2f}')
            if buy_changed:
                if buy_before is not None and buy is not None:
                    parts.append(f'Buying ₱{buy_before:,.2f} to ₱{buy:,.2f}')
                elif buy is not None:
                    parts.append(f'Buying set to ₱{buy:,.2f}')
            rows.append(_row(
                event_type='PRICE',
                description='; · '.join(parts) or 'Price updated',
                qty=0,
                buying_price=buy if buy is not None else buy_before,
                selling_price=sell if sell is not None else sell_before,
                stock_before=entry.total_before,
                stock_after=entry.total_after,
                created_at=when,
                note=entry.note or '',
            ))
            continue

        if delta > 0:
            unit_buy = buy if buy is not None else buy_before
            buy_value = (unit_buy * Decimal(delta)).quantize(Decimal('0.01')) if unit_buy is not None else None
            rows.append(_row(
                event_type='PURCHASE',
                description=f'Stock increased +{delta} unit{"s" if delta != 1 else ""}',
                qty=delta,
                buying_price=unit_buy,
                buying_value=buy_value,
                selling_price=sell if sell is not None else sell_before,
                stock_before=entry.total_before,
                stock_after=entry.total_after,
                created_at=when,
                note=entry.note or entry.get_change_type_display(),
            ))
            continue

        if delta < 0:
            rows.append(_row(
                event_type='ADJUSTMENT',
                description=f'Stock reduced {delta} unit{"s" if abs(delta) != 1 else ""}',
                qty=abs(delta),
                buying_price=buy if buy is not None else buy_before,
                selling_price=sell if sell is not None else sell_before,
                stock_before=entry.total_before,
                stock_after=entry.total_after,
                created_at=when,
                note=entry.note or entry.get_change_type_display(),
            ))
            continue

        # Zero-delta edits that still matter (tier moves, etc.)
        if entry.change_type in (
            ProductStockHistory.CHANGE_EDIT,
            ProductStockHistory.CHANGE_ADJUSTMENT,
            ProductStockHistory.CHANGE_PROMOTION,
        ):
            rows.append(_row(
                event_type='ADJUSTMENT',
                description=entry.get_change_type_display(),
                qty=0,
                buying_price=buy if buy is not None else buy_before,
                selling_price=sell if sell is not None else sell_before,
                stock_before=entry.total_before,
                stock_after=entry.total_after,
                created_at=when,
                note=entry.note or '',
            ))

    return rows


def build_purchase_rows_by_buying_price(product, history_entries=None):
    """
    Build purchase / restock rows for a product, split whenever the buying price changes.

    Each row is one buying-price period:
    ``buying_price``, ``selling_price``, ``qty_purchased`` (stock increases while
    that cost was active), ``buy_value``, ``period_start``, ``period_end``.

    Falls back to current stock batches (or list cost × on-hand) when no history exists.
    """
    from .models import ProductStockBatch, ProductStockHistory

    if history_entries is None:
        history_entries = list(
            ProductStockHistory.objects
            .filter(product=product)
            .order_by('created_at', 'id')
        )

    name, barcode, category = _product_export_meta(product)

    def _base_row(**extra):
        row = {
            'product_id': product.pk,
            'name': name,
            'barcode': barcode,
            'category': category,
            'buying_price': Decimal('0.00'),
            'selling_price': Decimal('0.00'),
            'qty_purchased': 0,
            'buy_value': Decimal('0.00'),
            'period_start': None,
            'period_end': None,
            'is_current': False,
            'note': '',
        }
        row.update(extra)
        return row

    if not history_entries:
        rows = []
        batches = list(
            ProductStockBatch.objects
            .filter(product=product, quantity__gt=0)
            .order_by('tier')
        )
        if batches:
            for batch in batches:
                buy = _money(batch.cost) or Decimal('0.00')
                sell = _money(batch.unit_price) or Decimal('0.00')
                qty = _qty(batch.quantity or 0)
                rows.append(_base_row(
                    buying_price=buy,
                    selling_price=sell,
                    qty_purchased=qty,
                    buy_value=(buy * qty).quantize(Decimal('0.01')),
                    period_start=getattr(batch, 'updated_at', None) or getattr(batch, 'created_at', None),
                    period_end=None,
                    is_current=True,
                    note=f'Current {batch.get_tier_display()} (no history yet)',
                ))
            return rows

        buy = _money(getattr(product, 'cost', None)) or Decimal('0.00')
        sell = _money(getattr(product, 'price', None)) or Decimal('0.00')
        qty = _qty(getattr(product, 'stock_quantity', 0) or 0)
        return [_base_row(
            buying_price=buy,
            selling_price=sell,
            qty_purchased=qty,
            buy_value=(buy * qty).quantize(Decimal('0.01')),
            period_start=None,
            period_end=None,
            is_current=True,
            note='Current stock (no history yet)',
        )]

    purchase_types = {
        ProductStockHistory.CHANGE_CREATED,
        ProductStockHistory.CHANGE_RESTOCK,
        ProductStockHistory.CHANGE_REFUND,
        ProductStockHistory.CHANGE_ADJUSTMENT,
        ProductStockHistory.CHANGE_EDIT,
        ProductStockHistory.CHANGE_PROMOTION,
    }

    periods = []
    current = None

    for entry in history_entries:
        when = entry.created_at
        buy_after = _money(entry.cost)
        buy_before = _money(entry.cost_before)
        sell_after = _money(entry.unit_price)
        sell_before = _money(entry.unit_price_before)

        opening_buy = buy_before if buy_before is not None else buy_after
        opening_sell = sell_before if sell_before is not None else sell_after

        if current is None:
            current = _base_row(
                buying_price=opening_buy or Decimal('0.00'),
                selling_price=opening_sell or Decimal('0.00'),
                period_start=when,
                note='',
            )

        # Buying price changed → close prior period and open a new one.
        if buy_after is not None and current['buying_price'] != buy_after:
            periods.append(_close_purchase_period(current, when))
            current = _base_row(
                buying_price=buy_after,
                selling_price=sell_after if sell_after is not None else (current['selling_price'] or Decimal('0.00')),
                period_start=when,
                note='Buying price changed',
            )
        elif sell_after is not None:
            current['selling_price'] = sell_after

        delta = _qty(entry.total_after or 0) - _qty(entry.total_before or 0)
        if delta > 0 and entry.change_type in purchase_types:
            current['qty_purchased'] = _qty(current['qty_purchased'] or 0) + delta

    if current is not None:
        current['is_current'] = True
        current['period_end'] = None
        periods.append(_close_purchase_period(current, None))

    return periods


def format_period_dt(value):
    """Local-time string for export cells; empty when unknown."""
    if value is None:
        return ''
    from django.utils import timezone as dj_tz
    try:
        local = dj_tz.localtime(value) if dj_tz.is_aware(value) else value
    except Exception:
        local = value
    try:
        return local.strftime('%Y-%m-%d %I:%M %p')
    except Exception:
        return str(value)
