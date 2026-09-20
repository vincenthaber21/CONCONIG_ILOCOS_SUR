"""Effective unit price: ProductDiscount promos + segment fixed-peso rules (senior/PWD vs member)."""
from collections import defaultdict
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from .units import qty_json



def _money(value):
    return Decimal(value).quantize(Decimal('0.01'))


def _stock_batches_for_product(product):
    """Return (old_batch|None, new_batch|None), using prefetch cache when available."""
    from .models import ProductStockBatch

    old_batch = None
    new_batch = None
    if (
        hasattr(product, '_prefetched_objects_cache')
        and 'stock_batches' in getattr(product, '_prefetched_objects_cache', {})
    ):
        for batch in product.stock_batches.all():
            if batch.tier == ProductStockBatch.TIER_OLD:
                old_batch = batch
            elif batch.tier == ProductStockBatch.TIER_NEW:
                new_batch = batch
        return old_batch, new_batch

    old_batch = product.stock_batches.filter(tier=ProductStockBatch.TIER_OLD).first()
    new_batch = product.stock_batches.filter(tier=ProductStockBatch.TIER_NEW).first()
    return old_batch, new_batch


def current_shelf_unit_price(product):
    """
    Unit price shown on shelf / product lists.
    Old stock is sold first; when it is gone, show the new-stock price.
    """
    old_batch, new_batch = _stock_batches_for_product(product)
    if old_batch and old_batch.quantity > 0:
        return _money(old_batch.unit_price)
    if new_batch and new_batch.quantity > 0:
        return _money(new_batch.unit_price)
    return _money(product.price)


def fifo_line_gross(product, quantity):
    """
    FIFO line total for a sale quantity: old tier units first, then new tier, then list price.
    Quantity is in the product's stock unit (pieces or kilograms).
    """
    qty = Decimal(str(quantity or 0))
    if qty <= 0:
        return Decimal('0.00')

    remaining = qty
    total = Decimal('0')
    old_batch, new_batch = _stock_batches_for_product(product)

    if old_batch and old_batch.quantity > 0 and remaining > 0:
        take = min(remaining, Decimal(str(old_batch.quantity)))
        total += old_batch.unit_price * take
        remaining -= take

    if remaining > 0 and new_batch and new_batch.quantity > 0:
        take = min(remaining, Decimal(str(new_batch.quantity)))
        total += new_batch.unit_price * take
        remaining -= take

    if remaining > 0:
        total += product.price * remaining

    return _money(total)


def fifo_weighted_unit_price(product, quantity):
    """
    FIFO average unit price for a sale quantity spanning old then new stock tiers.
    """
    qty = Decimal(str(quantity or 0))
    if qty <= 0:
        return current_shelf_unit_price(product)

    return _money(fifo_line_gross(product, qty) / qty)


def deduct_stock_batches(product, quantity):
    """
    Reduce old stock first, then new stock. Deletes batch rows when quantity hits 0.
    Returns units actually deducted from batch records.
    """
    from .models import ProductStockBatch

    remaining = Decimal(str(quantity or 0))
    if remaining <= 0:
        return Decimal('0')

    deducted = Decimal('0')
    old_batch, new_batch = _stock_batches_for_product(product)

    if old_batch and old_batch.quantity > 0 and remaining > 0:
        take = min(remaining, Decimal(str(old_batch.quantity)))
        old_batch.quantity = Decimal(str(old_batch.quantity)) - take
        remaining -= take
        deducted += take
        if old_batch.quantity <= 0:
            ProductStockBatch.objects.filter(pk=old_batch.pk).delete()
        else:
            old_batch.save(update_fields=['quantity', 'updated_at'])

    if new_batch and new_batch.quantity > 0 and remaining > 0:
        take = min(remaining, Decimal(str(new_batch.quantity)))
        new_batch.quantity = Decimal(str(new_batch.quantity)) - take
        remaining -= take
        deducted += take
        if new_batch.quantity <= 0:
            ProductStockBatch.objects.filter(pk=new_batch.pk).delete()
        else:
            new_batch.save(update_fields=['quantity', 'updated_at'])

    promote_new_stock_to_old_if_needed(product)
    return deducted


def promote_new_stock_to_old_if_needed(product):
    """
    When old stock is gone, move the new-stock batch into the old-stock tier.
    Syncs Product.price and Product.cost from the promoted batch selling/buying prices.
    Returns True when a promotion occurred.
    """
    from .models import ProductStockBatch

    old_batch, new_batch = _stock_batches_for_product(product)

    if old_batch and old_batch.quantity > 0:
        return False

    if not new_batch or new_batch.quantity <= 0:
        if old_batch:
            ProductStockBatch.objects.filter(pk=old_batch.pk).delete()
        return False

    if old_batch:
        ProductStockBatch.objects.filter(pk=old_batch.pk).delete()

    promoted_price = new_batch.unit_price
    promoted_cost = new_batch.cost
    new_batch.tier = ProductStockBatch.TIER_OLD
    new_batch.save(update_fields=['tier', 'updated_at'])

    update_fields = ['updated_at']
    if product.price != promoted_price:
        product.price = promoted_price
        update_fields.append('price')
    if promoted_cost is not None and product.cost != promoted_cost:
        product.cost = promoted_cost
        update_fields.append('cost')
    product.save(update_fields=update_fields)

    if hasattr(product, '_prefetched_objects_cache'):
        product._prefetched_objects_cache.pop('stock_batches', None)

    return True


def active_discounts_queryset():
    from .models import ProductDiscount

    now = timezone.now()
    return ProductDiscount.objects.filter(is_active=True).filter(
        Q(valid_from__isnull=True) | Q(valid_from__lte=now),
    ).filter(Q(valid_to__isnull=True) | Q(valid_to__gte=now))


def discounts_by_product_ids(product_ids):
    """Bulk-load active discounts keyed by product id (avoids N+1 in list endpoints)."""
    if not product_ids:
        return {}
    grouped = defaultdict(list)
    qs = active_discounts_queryset().filter(product_id__in=product_ids).order_by('id')
    for d in qs:
        grouped[d.product_id].append(d)
    return grouped


def _best_product_discount_price(regular, discount_list):
    """Return (lowest_price, ProductDiscount | None) from promotional rules only."""
    best = regular
    best_rule = None
    for d in discount_list:
        if d.discount_percent is not None:
            cand = regular * (Decimal('100') - d.discount_percent) / Decimal('100')
        else:
            cand = regular - (d.discount_amount or Decimal('0'))
        cand = _money(max(Decimal('0'), cand))
        if cand < best:
            best = cand
            best_rule = d
    if best >= regular:
        return regular, None
    return best, best_rule


def _member_price_segment(member):
    """
    Seniors/PWDs use senior_pwd rules; everyone else with a member account uses member_reseller rules.
    """
    if not member or not getattr(member, 'is_active', True):
        return None

    from members.models import PWDProfile, SegmentProductGroupDiscount, SeniorCitizenProfile

    try:
        sp = member.senior_profile
    except SeniorCitizenProfile.DoesNotExist:
        sp = None
    try:
        pp = member.pwd_profile
    except PWDProfile.DoesNotExist:
        pp = None

    if (sp and sp.is_active) or (pp and pp.is_active):
        return SegmentProductGroupDiscount.SEG_SENIOR_PWD
    return SegmentProductGroupDiscount.SEG_MEMBER_RESELLER


def _segment_rules_index(segment_rules):
    """Build (segment, discount_group_code) -> (amount_off, label) from queryset or list."""
    amount_map = {}
    label_map = {}
    for r in segment_rules or []:
        if not getattr(r, 'is_active', True):
            continue
        if not getattr(r, 'discount_group_id', None):
            continue
        code = r.discount_group.code
        key = (r.segment, code)
        amount_map[key] = r.amount_off
        raw = (getattr(r, 'label', None) or '').strip()
        label_map[key] = raw or f'₱{r.amount_off} off ({r.get_discount_group_display()})'
    return amount_map, label_map


def _apply_segment_amount_off(promo_price, product, member, segment_rules):
    """
    Subtract fixed pesos from promo unit price when member segment matches a rule for product.discount_group (FK).
    Returns (new_price, segment_label_or_none).
    """
    if not member or not (product.discount_group_code or '').strip():
        return promo_price, None

    from members.models import SegmentProductGroupDiscount

    segment = _member_price_segment(member)
    if not segment:
        return promo_price, None

    if segment_rules is None:
        segment_rules = list(
            SegmentProductGroupDiscount.objects.filter(is_active=True).select_related('discount_group')
        )

    amount_map, label_map = _segment_rules_index(segment_rules)
    key = (segment, product.discount_group_code)
    off = amount_map.get(key)
    if off is None or off <= 0:
        return promo_price, None

    after = _money(max(Decimal('0'), promo_price - off))
    return after, label_map.get(key)


def unit_price_after_discounts(
    product,
    discount_list=None,
    regular=None,
    member=None,
    segment_rules=None,
    **kwargs,
):
    """
    Return (effective_unit_price, regular_unit_price, meta).

    meta = {'discount_name': str|None}
    Promotional ProductDiscount is applied first; then fixed peso segment rules subtract from that unit price.
    """
    kwargs.pop('concession_policies', None)

    regular = _money(
        regular if regular is not None else current_shelf_unit_price(product)
    )
    if discount_list is None:
        discount_list = list(active_discounts_queryset().filter(product_id=product.id))

    promo_price, promo_rule = _best_product_discount_price(regular, discount_list)
    final, seg_label = _apply_segment_amount_off(promo_price, product, member, segment_rules)

    parts = []
    if promo_rule and promo_price < regular:
        parts.append(promo_rule.name)
    if seg_label and final < promo_price:
        parts.append(seg_label)
    discount_name = '; '.join(parts) if parts else None

    if final >= regular:
        return regular, regular, {'discount_name': None}
    return final, regular, {'discount_name': discount_name}


def price_payload_for_product(product, discount_list=None, member=None, segment_rules=None, **kwargs):
    """JSON-friendly fields for APIs (price = amount charged)."""
    kwargs.pop('concession_policies', None)
    eff, reg, meta = unit_price_after_discounts(
        product,
        discount_list=discount_list,
        member=member,
        segment_rules=segment_rules,
    )
    out = {
        'price': str(eff),
        'regular_price': str(reg),
    }
    old_batch, new_batch = _stock_batches_for_product(product)
    if old_batch and old_batch.quantity > 0:
        out['old_stock_qty'] = qty_json(old_batch.quantity)
        out['old_stock_price'] = str(old_batch.unit_price)
    if new_batch and new_batch.quantity > 0:
        out['new_stock_qty'] = qty_json(new_batch.quantity)
        out['new_stock_price'] = str(new_batch.unit_price)
    if old_batch and old_batch.quantity > 0:
        out['stock_tier'] = 'old'
    elif new_batch and new_batch.quantity > 0:
        out['stock_tier'] = 'new'
    if meta.get('discount_name'):
        out['discount_name'] = meta['discount_name']
    if (product.discount_group_code or '').strip():
        out['discount_group'] = product.discount_group_code
    return out
