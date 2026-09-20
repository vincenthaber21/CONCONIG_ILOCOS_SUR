from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils import timezone
from django.db.models import Q
from django.db import transaction as db_transaction
from django.utils.safestring import mark_safe
from inventory.models import Product, ProductSaleUnit, ProductStockHistory, StockTransaction, TaxRate
from inventory.stock_history import capture_stock_snapshot, record_stock_history
from inventory.sale_units import (
    cart_item_stock_pieces,
    cart_line_key,
    get_sale_unit_for_cart_item,
    kiosk_line_pricing,
    kiosk_payload_sale_unit,
    kiosk_scan_product_payload,
    product_sale_unit_options,
    resolve_product_sale_unit,
    resolve_scan_barcode,
    sale_units_search_queryset,
    sellable_quantity,
)
from inventory.pricing import (
    discounts_by_product_ids,
    price_payload_for_product,
    deduct_stock_batches,
)
from inventory.units import is_kilo_product, parse_sale_qty, qty_json
from members.models import Member, BalanceTransaction, SegmentProductGroupDiscount
from members.utils import mask_rfid, member_registered_discount_for_kiosk
from transactions.models import Transaction, TransactionItem, WalkInCustomer, user_processor_display
from transactions.walk_in_customers import (
    is_operator_default_customer_name,
    register_walk_in_customer,
)
from decimal import Decimal
import json
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt

from kiosk_helper import (
    generate_transaction_number,
    validate_cart_items,
    check_stock_availability,
    authenticate_member_for_debit,
    finalise_transaction,
    build_member_summary,
    get_member_credit_outstanding,
    member_credit_fields,
    member_credit_limit_exceeded,
    get_member_max_credit_limit,
    calculate_change,
    set_kiosk_session,
    clear_kiosk_session,
    get_kiosk_session_member_id,
    to_decimal,
)


from login_helper import is_cashier_or_admin, member_or_login_required
from admin_panel.models import KioskConfig, KioskSessionConfig, StoreProfile


def _member_and_segment_rules_for_pricing(request, member_id=None):
    """
    Member-scanned session and/or explicit member_id (same source as payment payload)
    for promotional + segment (senior/PWD/member group) unit pricing on product APIs.
    """
    mid = member_id
    if mid is None or mid == '':
        mid = get_kiosk_session_member_id(request)
    if mid is not None:
        try:
            mid = int(mid)
        except (TypeError, ValueError):
            mid = None
    if not mid:
        return None, None
    member = (
        Member.objects.select_related('member_role', 'senior_profile', 'pwd_profile')
        .filter(id=mid, is_active=True)
        .first()
    )
    if not member:
        return None, None
    segment_rules = list(SegmentProductGroupDiscount.objects.filter(is_active=True).select_related('discount_group'))
    return member, segment_rules


def _resolve_kiosk_shell_member(request):
    """
    Active member for kiosk / browse shell (same rules as kiosk home).
    Sets kiosk RFID session for admin/staff/cashier on username login.
    """
    member = None
    if request.user.is_authenticated:
        try:
            member = Member.objects.get(user=request.user, is_active=True)
        except (Member.DoesNotExist, Member.MultipleObjectsReturned):
            try:
                member = Member.objects.filter(user=request.user, is_active=True).first()
            except Exception:
                pass
        if not member:
            try:
                member = Member.objects.get(username=request.user.username, is_active=True)
            except (Member.DoesNotExist, Member.MultipleObjectsReturned):
                try:
                    member = Member.objects.filter(username=request.user.username, is_active=True).first()
                except Exception:
                    pass
    elif request.session.get('member_id'):
        try:
            member = Member.objects.get(id=request.session['member_id'], is_active=True)
        except Member.DoesNotExist:
            pass

    if member:
        member = (
            Member.objects.select_related('senior_profile', 'pwd_profile')
            .filter(id=member.id, is_active=True)
            .first()
        ) or member
        if member.role in ('admin', 'cashier', 'staff'):
            set_kiosk_session(request, member)
    return member


def _kiosk_operator_can_lookup_members(request):
    """Admin, cashier, and staff may search/attach a customer member on the kiosk."""
    if request.user.is_authenticated and is_cashier_or_admin(request.user):
        return True
    shell = _resolve_kiosk_shell_member(request)
    return bool(shell and shell.role in ('admin', 'cashier', 'staff'))


def _kiosk_member_scan_payload(member):
    """JSON member object returned by scan-rfid and attach-member kiosk APIs."""
    payload = {
        'id': member.id,
        'name': member.full_name,
        'rfid': mask_rfid(member.rfid_card_number),
        'balance': str(member.balance),
        'role': member.role,
    }
    payload.update(member_credit_fields(member))
    rd = member_registered_discount_for_kiosk(member)
    if rd:
        payload['registered_discount'] = rd
    return payload


def _kiosk_can_apply_manual_discount(request):
    """Manual line discount (Discount ₱) is limited to admin, staff, and cashier operators."""
    if request.user.is_authenticated and is_cashier_or_admin(request.user):
        return True
    mid = get_kiosk_session_member_id(request)
    if mid:
        role = (
            Member.objects.filter(id=mid, is_active=True)
            .values_list('member_role__slug', flat=True)
            .first()
        )
        if role in ('admin', 'cashier', 'staff'):
            return True
    shell = _resolve_kiosk_shell_member(request)
    return bool(shell and shell.role in ('admin', 'cashier', 'staff'))


def _product_tax_payload(product):
    """Return tax_rate, tax_type, tax_name fields for a product JSON payload."""
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


def _price_payload_extras(pf):
    """Optional old/new stock tier fields from price_payload_for_product."""
    extras = {}
    for key in ('old_stock_qty', 'old_stock_price', 'new_stock_qty', 'new_stock_price', 'stock_tier'):
        if key in pf:
            extras[key] = pf[key]
    return extras


def _kiosk_products_queryset(request):
    """Active products for kiosk scan, search, and browse catalog."""
    return (
        Product.objects.filter(is_active=True)
        .prefetch_related('stock_batches', 'sale_units')
    )


def _kiosk_shell_context(request):
    member = _resolve_kiosk_shell_member(request)
    logged_in_member_json = 'null'
    if member:
        member_data = {
            'id': member.id,
            'name': member.full_name,
            'rfid': mask_rfid(member.rfid_card_number),
            'rfid_autofill': member.rfid_card_number if member.role in ('admin', 'cashier', 'staff') else None,
            'balance': str(member.balance),
            'role': member.role,
        }
        member_data.update(member_credit_fields(member))
        rd = member_registered_discount_for_kiosk(member)
        if rd:
            member_data['registered_discount'] = rd
        logged_in_member_json = mark_safe(json.dumps(member_data))

    session_cfg = KioskSessionConfig.get()
    privileged_member = bool(member and member.role in ('admin', 'cashier', 'staff'))
    privileged_user = bool(
        request.user.is_authenticated and is_cashier_or_admin(request.user)
    )
    # Match checkout: staff operator in kiosk session may apply Discount (₱) even when
    # the shell member is an attached customer.
    can_apply_manual_discount = _kiosk_can_apply_manual_discount(request)
    can_search_kiosk_members = can_apply_manual_discount
    kiosk_skip_idle_logout = can_apply_manual_discount
    kiosk_operator_json = 'null'
    if privileged_member and member:
        kiosk_operator_json = mark_safe(json.dumps({
            'name': member.full_name,
            'role': member.role,
            'member_id': member.id,
            'is_privileged': True,
        }))
    elif privileged_user and request.user.is_authenticated:
        kiosk_operator_json = mark_safe(json.dumps({
            'name': (request.user.get_full_name() or '').strip() or request.user.username,
            'role': 'admin',
            'member_id': member.id if member else None,
            'is_privileged': True,
        }))
    # Resolve the active tax rate for customer-facing display on the kiosk.
    active_tax = TaxRate.objects.filter(is_active=True).order_by('name').first()
    if active_tax:
        _rate_pct = float(active_tax.rate)
        _pct_str = f"{int(_rate_pct)}%" if _rate_pct == int(_rate_pct) else f"{_rate_pct}%"
        active_tax_label = (
            active_tax.name
            if '%' in active_tax.name
            else f"{active_tax.name} {_pct_str}"
        )
        active_tax_pct = _rate_pct
        active_tax_type = active_tax.tax_type or 'inclusive'
    else:
        active_tax_label = 'VAT'
        active_tax_pct = None
        active_tax_type = 'inclusive'

    kiosk_cfg = KioskConfig.get()
    store_profile = StoreProfile.get()
    store_logo_url = (
        request.build_absolute_uri(store_profile.logo.url)
        if store_profile.logo
        else ''
    )
    return {
        'VAT_RATE': settings.VAT_RATE,
        'VAT_INCLUSIVE': settings.VAT_INCLUSIVE,
        'TAX_ENABLED': kiosk_cfg.tax_enabled,
        'ACTIVE_TAX_LABEL': active_tax_label,
        'ACTIVE_TAX_PCT': active_tax_pct if active_tax_pct is not None else '',
        'ACTIVE_TAX_TYPE': active_tax_type,
        'logged_in_member_json': logged_in_member_json,
        'kiosk_operator_json': kiosk_operator_json,
        'is_admin': request.user.is_authenticated and is_cashier_or_admin(request.user),
        'kiosk_config': kiosk_cfg,
        'store_logo_url': store_logo_url,
        'kiosk_session_config': session_cfg,
        'kiosk_idle_timeout_ms': int(session_cfg.inactivity_minutes) * 60 * 1000,
        'kiosk_idle_warning_ms': int(session_cfg.warning_seconds) * 1000,
        'kiosk_skip_idle_logout': kiosk_skip_idle_logout,
        'can_apply_manual_discount': can_apply_manual_discount,
        'can_search_kiosk_members': can_search_kiosk_members,
        'member_max_credit': get_member_max_credit_limit(),
    }


@member_or_login_required
@ensure_csrf_cookie
def kiosk_home(request):
    return render(request, 'kiosk/kiosk.html', _kiosk_shell_context(request))


@member_or_login_required
@ensure_csrf_cookie
def kiosk_browse_products(request):
    """Full-page product catalog (natural shelf-style layout) linked from the main kiosk."""
    return render(request, 'kiosk/browse_products.html', _kiosk_shell_context(request))


@require_http_methods(["POST"])
def scan_product(request):
    try:
        data = json.loads(request.body)
        barcode = data.get('barcode')
        
        if not barcode:
            return JsonResponse({'success': False, 'error': 'Barcode is required'})
        
        product, sale_unit = resolve_scan_barcode(barcode)
        if not product:
            return JsonResponse({'success': False, 'error': 'Product not found'})

        sale_unit = kiosk_payload_sale_unit(product, sale_unit)

        if sellable_quantity(product, sale_unit) <= 0:
            from inventory.utils import track_out_of_stock_attempt
            track_out_of_stock_attempt(product)
            return JsonResponse({'success': False, 'error': 'Product is out of stock'})

        member_id = data.get('member_id')
        pricing_member, segment_rules = _member_and_segment_rules_for_pricing(request, member_id)
        disc_one = discounts_by_product_ids([product.id])
        payload = kiosk_scan_product_payload(
            product,
            sale_unit,
            discount_list=disc_one.get(product.id, []),
            member=pricing_member,
            segment_rules=segment_rules,
        )
        return JsonResponse({'success': True, 'product': payload})
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
    except Exception:
        return JsonResponse({'success': False, 'error': 'Server error occurred'})


@require_http_methods(["GET"])
def search_products(request):
    """
    Simple product search endpoint used by the kiosk JS.
    Query parameter: `q` (string). Returns JSON: { results: [ {id,name,barcode,price,stock}, ... ] }
    Matches against name (icontains) and barcode (exact or contains) and only active products.
    """
    q = request.GET.get('q', '')
    q = (q or '').strip()
    if not q or len(q) < 2:
        return JsonResponse({'results': []})

    try:
        base_qs = _kiosk_products_queryset(request).select_related('discount_group', 'tax_rate').prefetch_related('sale_units')
        member_id = request.GET.get('member_id')
        pricing_member, segment_rules = _member_and_segment_rules_for_pricing(request, member_id)

        exact_unit = (
            ProductSaleUnit.objects.filter(
                barcode=q,
                is_active=True,
                product__is_active=True,
            )
            .select_related('product', 'product__discount_group', 'product__tax_rate')
            .first()
        )
        if exact_unit:
            product = exact_unit.product
            disc_map = discounts_by_product_ids([product.id])
            payload = kiosk_scan_product_payload(
                product,
                exact_unit,
                discount_list=disc_map.get(product.id, []),
                member=pricing_member,
                segment_rules=segment_rules,
            )
            return JsonResponse({'results': [payload]})

        qs = base_qs
        if q.isdigit():
            qs = qs.filter(Q(barcode__icontains=q) | Q(name__icontains=q))
        else:
            qs = qs.filter(name__icontains=q)

        qs = qs.order_by('name')[:50]

        results = []
        from inventory.utils import track_out_of_stock_attempt

        disc_map = discounts_by_product_ids(list(qs.values_list('id', flat=True)))
        seen_keys = set()

        for idx, p in enumerate(qs):
            retail_unit = kiosk_payload_sale_unit(p, None)
            stock = sellable_quantity(p, retail_unit)
            
            if stock <= 0:
                is_exact_match = (
                    (q.isdigit() and p.barcode == q) or
                    (p.name.lower() == q.lower())
                )
                if is_exact_match or idx < 3:
                    track_out_of_stock_attempt(p)
            
            payload = kiosk_scan_product_payload(
                p,
                retail_unit,
                discount_list=disc_map.get(p.id, []),
                member=pricing_member,
                segment_rules=segment_rules,
            )
            results.append(payload)
            seen_keys.add(payload['cart_line_key'])

        if q.isdigit() or len(q) >= 3:
            for unit in sale_units_search_queryset(q, base_qs):
                if unit.sale_mode != ProductSaleUnit.SALE_MODE_WHOLESALE:
                    continue
                key = cart_line_key(unit.product_id, unit.id)
                if key in seen_keys:
                    continue
                payload = kiosk_scan_product_payload(
                    unit.product,
                    unit,
                    discount_list=disc_map.get(unit.product_id, []),
                    member=pricing_member,
                    segment_rules=segment_rules,
                )
                if int(payload.get('stock') or 0) <= 0:
                    continue
                results.append(payload)
                seen_keys.add(key)
                if len(results) >= 50:
                    break

        return JsonResponse({'results': results})
    except Exception:
        return JsonResponse({'results': []})


@require_http_methods(["GET"])
def get_all_products(request):
    """
    Returns all active products grouped by category for the visual product catalog.
    Optional: ?category=<id> to filter by category, ?q=<text> for search.
    """
    try:
        qs = (
            _kiosk_products_queryset(request)
            .select_related('category', 'discount_group', 'tax_rate')
            .order_by('category__name', 'name')
        )

        q = request.GET.get('q', '').strip()
        cat_id = request.GET.get('category', '').strip()

        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(barcode__icontains=q))
        if cat_id:
            try:
                qs = qs.filter(category_id=int(cat_id))
            except (ValueError, TypeError):
                pass

        products = []
        disc_map = discounts_by_product_ids(list(qs.values_list('id', flat=True)))
        member_id = request.GET.get('member_id')
        pricing_member, segment_rules = _member_and_segment_rules_for_pricing(request, member_id)
        for p in qs:
            image_url = None
            if p.image:
                try:
                    image_url = p.image.url
                except Exception:
                    pass
            pf = price_payload_for_product(
                p,
                discount_list=disc_map.get(p.id, []),
                member=pricing_member,
                segment_rules=segment_rules,
            )
            row = {
                'id': p.id,
                'name': p.name,
                'barcode': p.barcode,
                'price': pf['price'],
                'regular_price': pf['regular_price'],
                'discount_group': p.discount_group_code,
                'stock': qty_json(p.stock_quantity),
                'unit_type': p.unit_type,
                'is_kilo': is_kilo_product(p),
                'image': image_url,
                'category_id': p.category_id,
                'category_name': p.category.name if p.category else 'Uncategorized',
                'is_out_of_stock': p.stock_quantity <= 0,
                'is_low_stock': p.is_low_stock,
                **_price_payload_extras(pf),
                **_product_tax_payload(p),
            }
            if 'discount_name' in pf:
                row['discount_name'] = pf['discount_name']
            products.append(row)

        # Also return distinct categories
        from inventory.models import Category
        categories = list(
            Category.objects.filter(is_active=True).values('id', 'name').order_by('name')
        )

        return JsonResponse({
            'products': products,
            'categories': categories,
        })
    except Exception:
        return JsonResponse({'products': [], 'categories': []})


@require_http_methods(["GET"])
def api_kiosk_product_sale_units(request):
    """
    List piece + wholesale sale options for a product (kiosk cart unit selector).
    Query: product_id, optional member_id for member pricing.
    """
    product_id = request.GET.get('product_id', '').strip()
    if not product_id:
        return JsonResponse({'success': False, 'error': 'product_id is required'}, status=400)
    try:
        product_id = int(product_id)
    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'error': 'Invalid product_id'}, status=400)

    product = (
        _kiosk_products_queryset(request)
        .select_related('discount_group', 'tax_rate')
        .prefetch_related('sale_units')
        .filter(id=product_id)
        .first()
    )
    if not product:
        return JsonResponse({'success': False, 'error': 'Product not found'}, status=404)

    member_id = request.GET.get('member_id')
    pricing_member, segment_rules = _member_and_segment_rules_for_pricing(request, member_id)
    disc_map = discounts_by_product_ids([product.id])
    options = product_sale_unit_options(
        product,
        discount_list=disc_map.get(product.id, []),
        member=pricing_member,
        segment_rules=segment_rules,
    )

    return JsonResponse({
        'success': True,
        'product_id': product.id,
        'product_name': product.name,
        'has_multiple_units': len(options) > 1,
        'options': options,
    })


@require_http_methods(["POST"])
def api_kiosk_select_sale_unit(request):
    """
    Resolve piece vs wholesale selection for kiosk cart.
    Body: { product_id, sale_unit_id? (null/0 = per piece), member_id? }
    """
    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'}, status=400)

    product_id = data.get('product_id')
    if not product_id:
        return JsonResponse({'success': False, 'error': 'product_id is required'}, status=400)
    try:
        product_id = int(product_id)
    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'error': 'Invalid product_id'}, status=400)

    product = (
        _kiosk_products_queryset(request)
        .select_related('discount_group', 'tax_rate')
        .prefetch_related('sale_units')
        .filter(id=product_id)
        .first()
    )
    if not product:
        return JsonResponse({'success': False, 'error': 'Product not found'}, status=404)

    sale_unit_id = data.get('sale_unit_id')
    sale_unit = resolve_product_sale_unit(product, sale_unit_id)
    if sale_unit_id not in (None, '', 0, '0') and not sale_unit:
        return JsonResponse({'success': False, 'error': 'Sale unit not found for this product'}, status=400)

    available = sellable_quantity(product, sale_unit)
    if available <= 0:
        if sale_unit and sale_unit.sale_mode == ProductSaleUnit.SALE_MODE_WHOLESALE:
            return JsonResponse({
                'success': False,
                'error': (
                    f'Need at least {sale_unit.units_per_package} pieces in stock for '
                    f'one {sale_unit.unit_label}. Currently {product.stock_quantity} pieces.'
                ),
            }, status=400)
        return JsonResponse({'success': False, 'error': 'Product is out of stock for this sale unit'}, status=400)

    pricing_member, segment_rules = _member_and_segment_rules_for_pricing(
        request,
        data.get('member_id'),
    )
    disc_map = discounts_by_product_ids([product.id])
    payload = kiosk_scan_product_payload(
        product,
        sale_unit,
        discount_list=disc_map.get(product.id, []),
        member=pricing_member,
        segment_rules=segment_rules,
    )
    options = product_sale_unit_options(
        product,
        discount_list=disc_map.get(product.id, []),
        member=pricing_member,
        segment_rules=segment_rules,
    )

    return JsonResponse({
        'success': True,
        'product': payload,
        'has_multiple_units': len(options) > 1,
        'options': options,
    })


@require_http_methods(["POST"])
def api_quote_cart_lines(request):
    """
    Authoritative per-line kiosk pricing (FIFO old/new stock tiers + member discounts).
    Body: { member_id?, items: [{ product_id, quantity }] }
    """
    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'}, status=400)

    items = data.get('items') or []
    if not items:
        return JsonResponse({'success': True, 'lines': []})

    member_id = data.get('member_id')
    pricing_member, segment_rules = _member_and_segment_rules_for_pricing(request, member_id)

    product_ids = []
    cleaned = []
    for row in items:
        try:
            pid = int(row.get('product_id'))
            qty = Decimal(str(row.get('quantity')))
        except (TypeError, ValueError, Exception):
            continue
        if qty <= 0:
            continue
        product_ids.append(pid)
        line = {'product_id': pid, 'quantity': qty}
        if row.get('sale_unit_id') not in (None, ''):
            try:
                line['sale_unit_id'] = int(row.get('sale_unit_id'))
            except (TypeError, ValueError):
                pass
        cleaned.append(line)

    if not cleaned:
        return JsonResponse({'success': False, 'error': 'No valid cart items'}, status=400)

    products_qs = (
        _kiosk_products_queryset(request)
        .filter(id__in=product_ids)
        .prefetch_related('sale_units')
    )
    product_map = {p.id: p for p in products_qs}
    disc_map = discounts_by_product_ids(product_ids)

    lines = []
    for row in cleaned:
        product = product_map.get(row['product_id'])
        if not product:
            continue
        qty = row['quantity']
        sale_unit = get_sale_unit_for_cart_item(product, row)
        try:
            qty = parse_sale_qty(qty, product)
        except ValueError:
            continue
        row['quantity'] = qty
        pricing = kiosk_line_pricing(
            product,
            qty,
            sale_unit=sale_unit,
            discount_list=disc_map.get(product.id, []),
            member=pricing_member,
            segment_rules=segment_rules,
        )
        is_wholesale = bool(
            sale_unit and sale_unit.sale_mode == ProductSaleUnit.SALE_MODE_WHOLESALE
        )
        available = sellable_quantity(product, sale_unit)
        line = {
            'product_id': product.id,
            'sale_unit_id': sale_unit.id if sale_unit else None,
            'cart_line_key': cart_line_key(product.id, sale_unit.id if sale_unit else None),
            'quantity': qty_json(qty),
            'unit_price': pricing['unit_price'],
            'regular_price': pricing['regular_price'],
            'line_gross': pricing['line_gross'],
            'fifo_line_gross': pricing['fifo_line_gross'],
            'price': pricing['unit_price'],
            'available_stock': available,
            'stock': available,
            'is_wholesale': is_wholesale,
            'units_per_package': sale_unit.units_per_package if sale_unit else 1,
            **_price_payload_extras(pricing),
        }
        if pricing.get('discount_name'):
            line['discount_name'] = pricing['discount_name']
        lines.append(line)

    return JsonResponse({'success': True, 'lines': lines})


def _parse_kiosk_cart_stock_rows(rows, product_map=None):
    """Normalize cart rows for aggregate stock checks (product_id, quantity, sale_unit_id)."""
    cleaned = []
    product_ids = []
    for row in rows or []:
        try:
            pid = int(row.get('product_id'))
            qty = Decimal(str(row.get('quantity')))
        except (TypeError, ValueError, Exception):
            continue
        if qty <= 0:
            continue
        product_ids.append(pid)
        line = {'product_id': pid, 'quantity': qty}
        if row.get('sale_unit_id') not in (None, ''):
            try:
                line['sale_unit_id'] = int(row.get('sale_unit_id'))
            except (TypeError, ValueError):
                pass
        if row.get('units_per_package') not in (None, ''):
            try:
                line['units_per_package'] = int(row.get('units_per_package'))
            except (TypeError, ValueError):
                pass
        elif product_map and line.get('sale_unit_id'):
            product = product_map.get(pid)
            if product:
                sale_unit = get_sale_unit_for_cart_item(product, line)
                if sale_unit:
                    line['units_per_package'] = sale_unit.units_per_package
        cleaned.append(line)
    return cleaned, product_ids


@require_http_methods(["POST"])
def api_kiosk_update_cart_quantity(request):
    """
    Validate and quote a cart-line quantity change against live stock.
    Body: {
      product_id, quantity (absolute, >= 1),
      sale_unit_id?, units_per_package?,
      other_items? (remaining cart lines for shared-stock checks),
      member_id?
    }
    """
    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'}, status=400)

    try:
        product_id = int(data.get('product_id'))
        quantity = Decimal(str(data.get('quantity')))
    except (TypeError, ValueError, Exception):
        return JsonResponse({'success': False, 'error': 'Invalid product_id or quantity'}, status=400)

    if quantity <= 0:
        return JsonResponse({'success': False, 'error': 'Quantity must be greater than zero'}, status=400)

    product = (
        _kiosk_products_queryset(request)
        .select_related('discount_group', 'tax_rate')
        .prefetch_related('sale_units')
        .filter(id=product_id)
        .first()
    )
    if not product:
        return JsonResponse({'success': False, 'error': 'Product not found'}, status=404)

    try:
        quantity = parse_sale_qty(quantity, product)
    except ValueError as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)

    sale_unit_row = {'sale_unit_id': data.get('sale_unit_id')}
    if data.get('units_per_package') not in (None, ''):
        try:
            sale_unit_row['units_per_package'] = int(data.get('units_per_package'))
        except (TypeError, ValueError):
            pass
    sale_unit = get_sale_unit_for_cart_item(product, sale_unit_row)
    if data.get('sale_unit_id') not in (None, '', 0, '0') and not sale_unit:
        return JsonResponse({'success': False, 'error': 'Sale unit not found for this product'}, status=400)

    available = sellable_quantity(product, sale_unit)
    if quantity > available:
        unit_hint = sale_unit.unit_label if sale_unit else 'unit'
        return JsonResponse({
            'success': False,
            'error': f'Only {available} {unit_hint}(s) available.',
            'available_stock': available,
            'quantity': available if available > 0 else quantity,
        }, status=400)

    target_line = {'product_id': product_id, 'quantity': quantity}
    if sale_unit:
        target_line['sale_unit_id'] = sale_unit.id
        target_line['units_per_package'] = sale_unit.units_per_package
    elif data.get('units_per_package') not in (None, ''):
        try:
            target_line['units_per_package'] = int(data.get('units_per_package'))
        except (TypeError, ValueError):
            pass

    product_map = {product_id: product}
    other_rows, other_pids = _parse_kiosk_cart_stock_rows(data.get('other_items'), product_map)
    all_pids = list({product_id, *other_pids})
    for pid in other_pids:
        if pid in product_map:
            continue
        extra = (
            _kiosk_products_queryset(request)
            .prefetch_related('sale_units')
            .filter(id=pid)
            .first()
        )
        if extra:
            product_map[pid] = extra

    ok, err = check_stock_availability(product_map, other_rows + [target_line])
    if not ok:
        return JsonResponse({
            'success': False,
            'error': err or 'Insufficient stock',
            'available_stock': available,
        }, status=400)

    pricing_member, segment_rules = _member_and_segment_rules_for_pricing(
        request,
        data.get('member_id'),
    )
    disc_map = discounts_by_product_ids([product_id])
    pricing = kiosk_line_pricing(
        product,
        quantity,
        sale_unit=sale_unit,
        discount_list=disc_map.get(product_id, []),
        member=pricing_member,
        segment_rules=segment_rules,
    )
    product_payload = kiosk_scan_product_payload(
        product,
        sale_unit,
        discount_list=disc_map.get(product_id, []),
        member=pricing_member,
        segment_rules=segment_rules,
    )

    line_key = cart_line_key(product_id, sale_unit.id if sale_unit else None)
    is_wholesale = bool(
        sale_unit and sale_unit.sale_mode == ProductSaleUnit.SALE_MODE_WHOLESALE
    )
    line = {
        'product_id': product_id,
        'sale_unit_id': sale_unit.id if sale_unit else None,
        'cart_line_key': line_key,
        'quantity': quantity,
        'unit_price': pricing['unit_price'],
        'regular_price': pricing['regular_price'],
        'price': pricing['unit_price'],
        'line_gross': pricing['line_gross'],
        'fifo_line_gross': pricing['fifo_line_gross'],
        'available_stock': available,
        'stock': available,
        'is_wholesale': is_wholesale,
        'units_per_package': sale_unit.units_per_package if sale_unit else 1,
        **_price_payload_extras(pricing),
    }
    if pricing.get('discount_name'):
        line['discount_name'] = pricing['discount_name']

    return JsonResponse({
        'success': True,
        'cart_line_key': line_key,
        'quantity': quantity,
        'available_stock': available,
        'remaining': max(available - quantity, 0),
        'product': product_payload,
        'line': line,
    })


@require_http_methods(["POST"])
def scan_rfid(request):
    try:
        data = json.loads(request.body)
        rfid = data.get('rfid')
        
        if not rfid:
            return JsonResponse({'success': False, 'error': 'RFID is required'})
        
        try:
            member = Member.objects.select_related('senior_profile', 'pwd_profile').get(
                rfid_card_number=rfid, is_active=True
            )
            
            set_kiosk_session(request, member)

            return JsonResponse({
                'success': True,
                'member': _kiosk_member_scan_payload(member),
            })
        except Member.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Member not found'})
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': 'Server error occurred'})


@require_http_methods(["GET"])
def api_kiosk_search_members(request):
    """Search members by name or RFID for kiosk operators (admin, cashier, staff)."""
    if not _kiosk_operator_can_lookup_members(request):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

    query = (request.GET.get('q') or '').strip()
    if not query or len(query) < 2:
        return JsonResponse({'success': True, 'members': []})

    try:
        members = Member.objects.filter(
            Q(rfid_card_number__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email__icontains=query)
        ).filter(is_active=True).order_by('first_name', 'last_name')[:20]

        results = [
            {
                'id': member.id,
                'rfid': member.rfid_card_number or '',
                'name': member.full_name,
                'email': member.email or '',
                'current_balance': str(member.balance),
            }
            for member in members
        ]
        return JsonResponse({'success': True, 'members': results})
    except Exception:
        return JsonResponse({'success': False, 'error': 'Server error occurred'})


@require_http_methods(["POST"])
def api_kiosk_attach_member(request):
    """Attach a customer member to the kiosk session by database id (no RFID required)."""
    if not _kiosk_operator_can_lookup_members(request):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'})

    member_id = data.get('member_id')
    if not member_id:
        return JsonResponse({'success': False, 'error': 'member_id is required'})

    try:
        member_id = int(member_id)
    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'error': 'Invalid member_id'})

    try:
        member = Member.objects.select_related('senior_profile', 'pwd_profile').get(
            id=member_id,
            is_active=True,
        )
    except Member.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Member not found'})

    set_kiosk_session(request, member)
    return JsonResponse({'success': True, 'member': _kiosk_member_scan_payload(member)})


@require_http_methods(["GET"])
def api_walk_in_customer_names(request):
    """Recent walk-in customer names for kiosk autocomplete."""
    q = (request.GET.get('q') or '').strip()
    qs = WalkInCustomer.objects.all().order_by('-last_seen_at')
    if q:
        qs = qs.filter(display_name__icontains=q)[:25]
    else:
        qs = qs[:40]
    seen = set()
    names = []
    for c in qs:
        key = (c.display_name or '').strip().casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        names.append(c.display_name.strip())
    return JsonResponse({
        'success': True,
        'names': names,
    })


@require_http_methods(["GET"])
def api_member_credit(request):
    """Return outstanding credit (completed credit sales) for a member."""
    member_id = request.GET.get('member_id', '').strip()
    if not member_id:
        return JsonResponse({'success': False, 'error': 'member_id is required'})
    try:
        member_id = int(member_id)
    except (ValueError, TypeError):
        return JsonResponse({'success': False, 'error': 'Invalid member_id'})

    try:
        member = Member.objects.get(id=member_id, is_active=True)
    except Member.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Member not found'})

    payload = {
        'success': True,
        'member_id': member.id,
        'balance': str(member.balance),
    }
    payload.update(member_credit_fields(member))
    return JsonResponse(payload)


@require_http_methods(["POST"])
@db_transaction.atomic
def process_payment(request):
    try:
        data = json.loads(request.body)
        
        member_id = data.get('member_id')
        items = data.get('items', [])
        payment_method = data.get('payment_method')
        guest_customer_name = (data.get('guest_customer_name') or '').strip()
        operator_default_name = (data.get('operator_default_name') or '').strip()

        if guest_customer_name and operator_default_name and is_operator_default_customer_name(
            guest_customer_name, operator_default_name
        ):
            guest_customer_name = ''

        if not payment_method or payment_method not in ['debit', 'cash', 'credit']:
            return JsonResponse({'success': False, 'error': 'Invalid payment method'})

        # Validate cart items
        is_valid, cart_err, items = validate_cart_items(items)
        if not is_valid:
            return JsonResponse({'success': False, 'error': cart_err})
        
        member = None
        if member_id:
            try:
                member_id = int(member_id)
            except (ValueError, TypeError):
                return JsonResponse({'success': False, 'error': 'Invalid member ID'})
            
            try:
                member = Member.objects.select_related(
                    'member_role', 'senior_profile', 'pwd_profile'
                ).get(id=member_id, is_active=True)
            except Member.DoesNotExist:
                return JsonResponse({'success': False, 'error': 'Member not found or inactive'})
            
            # Validate debit authentication via RFID session and/or PIN
            if payment_method == 'debit':
                auth_ok, auth_err = authenticate_member_for_debit(request, member, data.get('pin'))
                if not auth_ok:
                    return JsonResponse({'success': False, 'error': auth_err})
            elif payment_method == 'credit' and not _kiosk_can_apply_manual_discount(request):
                # Member self-service credit (insufficient balance) requires PIN
                auth_ok, auth_err = authenticate_member_for_debit(request, member, data.get('pin'))
                if not auth_ok:
                    return JsonResponse({'success': False, 'error': auth_err})
        else:
            if payment_method in ('debit', 'credit'):
                return JsonResponse({
                    'success': False,
                    'error': 'Member card required for debit or credit payment',
                })
            elif (
                payment_method == 'cash'
                and request.user.is_authenticated
                and not is_cashier_or_admin(request.user)
                and not guest_customer_name
                and not operator_default_name
            ):
                # Self-checkout fallback: only for regular members, never for cashier/admin.
                # A cashier who sends no member_id must provide a walk-in customer name.
                try:
                    member = Member.objects.select_related(
                        'member_role', 'senior_profile', 'pwd_profile'
                    ).get(user=request.user, is_active=True)
                except Member.DoesNotExist:
                    pass
                except Member.MultipleObjectsReturned:
                    member = Member.objects.select_related(
                        'member_role', 'senior_profile', 'pwd_profile'
                    ).filter(user=request.user, is_active=True).first()

        if not member:
            if len(guest_customer_name) < 2:
                err = 'Please enter the walk-in customer name (at least 2 characters).'
                if operator_default_name:
                    err = (
                        'Please enter the walk-in customer\'s name '
                        '(not your staff/cashier name).'
                    )
                return JsonResponse({'success': False, 'error': err})
            if len(guest_customer_name) > 200:
                guest_customer_name = guest_customer_name[:200]

        # Lock product rows and validate stock availability
        product_ids = [item['product_id'] for item in items]
        products_qs = (
            Product.objects.select_for_update()
            .select_related('tax_rate', 'discount_group')
            .prefetch_related('stock_batches', 'sale_units')
            .filter(id__in=product_ids, is_active=True)
        )
        product_map = {p.id: p for p in products_qs}

        stock_ok, stock_err = check_stock_availability(product_map, items)
        if not stock_ok:
            return JsonResponse({'success': False, 'error': stock_err})

        allow_manual_discount = _kiosk_can_apply_manual_discount(request)

        disc_map = discounts_by_product_ids(product_ids)

        segment_rules = None
        if member:
            segment_rules = list(SegmentProductGroupDiscount.objects.filter(is_active=True).select_related('discount_group'))

        # Capture balance before any deductions for the receipt
        member_before_balance = Decimal(str(member.balance)) if member else None

        walk_in_customer = None
        if guest_customer_name:
            walk_in_customer = register_walk_in_customer(guest_customer_name)
            if walk_in_customer:
                guest_customer_name = walk_in_customer.display_name

        # Record the cashier / staff who processed this sale.
        processed_by_user = None
        if request.user.is_authenticated and is_cashier_or_admin(request.user):
            processed_by_user = request.user
        else:
            session_member_id = get_kiosk_session_member_id(request)
            if session_member_id:
                try:
                    session_member = Member.objects.select_related('user').get(
                        pk=session_member_id, is_active=True
                    )
                    if session_member.role in ('admin', 'cashier', 'staff') and session_member.user_id:
                        processed_by_user = session_member.user
                except Member.DoesNotExist:
                    pass

        transaction = Transaction.objects.create(
            transaction_number=generate_transaction_number(),
            member=member,
            guest_customer_name=guest_customer_name[:200] if guest_customer_name else '',
            walk_in_customer=walk_in_customer,
            payment_method=payment_method,
            status='pending',
            processed_by=processed_by_user,
        )
        
        for item_data in items:
            pid = item_data['product_id']
            product = product_map[pid]
            before_stock = product.stock_quantity
            before_stock_snapshot = capture_stock_snapshot(product)

            qty = item_data['quantity']
            sale_unit = get_sale_unit_for_cart_item(product, item_data)
            if item_data.get('sale_unit_id') and not sale_unit:
                transaction.status = 'cancelled'
                transaction.save()
                return JsonResponse({'success': False, 'error': 'Invalid sale unit for cart item'})
            try:
                qty = parse_sale_qty(qty, product)
            except ValueError as exc:
                transaction.status = 'cancelled'
                transaction.save()
                return JsonResponse({'success': False, 'error': str(exc)})
            item_data['quantity'] = qty

            pricing = kiosk_line_pricing(
                product,
                qty,
                sale_unit=sale_unit,
                discount_list=disc_map.get(pid, []),
                member=member,
                segment_rules=segment_rules,
            )
            unit_price = Decimal(str(pricing['unit_price']))
            line_gross = Decimal(str(pricing['line_gross']))

            minus = Decimal('0.00')
            if allow_manual_discount:
                try:
                    minus = to_decimal(item_data.get('minus_price', 0) or 0)
                except Exception:
                    minus = Decimal('0.00')
                if minus < 0:
                    minus = Decimal('0.00')
                if minus > line_gross:
                    minus = line_gross

            if sale_unit and sale_unit.sale_mode == ProductSaleUnit.SALE_MODE_WHOLESALE:
                line_name = f'{product.name} ({sale_unit.unit_label})'
                line_barcode = sale_unit.barcode
            else:
                line_name = product.name
                line_barcode = sale_unit.barcode if sale_unit else product.barcode

            TransactionItem.objects.create(
                transaction=transaction,
                product=product,
                product_name=line_name,
                product_barcode=line_barcode,
                unit_price=unit_price,
                quantity=qty,
                manual_discount_php=minus,
            )

            stock_pieces = cart_item_stock_pieces({
                'quantity': qty,
                'units_per_package': sale_unit.units_per_package if sale_unit else 1,
            })
            product.stock_quantity -= stock_pieces
            product.save()
            deduct_stock_batches(product, stock_pieces)
            StockTransaction.objects.create(
                product=product,
                transaction_type='out',
                quantity=stock_pieces,
                stock_before=before_stock,
                stock_after=product.stock_quantity,
                notes=f'Sale via kiosk transaction {transaction.transaction_number}'
            )
            record_stock_history(
                product,
                ProductStockHistory.CHANGE_SALE,
                before_stock_snapshot,
                note=f'Sale via kiosk transaction {transaction.transaction_number}',
                user=processed_by_user,
                quantity_sold=stock_pieces,
                skip_if_unchanged=False,
            )
        
        transaction.calculate_totals()
        
        if payment_method == 'debit' and member:
            if member.balance >= transaction.total_amount:
                member.deduct_balance(transaction.total_amount)
                transaction.amount_from_balance = transaction.total_amount
                transaction.status = 'completed'
            else:
                # Insufficient balance - return error instead of converting to credit
                transaction.status = 'cancelled'
                transaction.save()
                return JsonResponse({
                    'success': False,
                    'error': f'Insufficient balance. Available: ₱{member_before_balance}, Required: ₱{transaction.total_amount}'
                })
        
        elif payment_method == 'credit':
            if not member:
                transaction.status = 'cancelled'
                transaction.save()
                return JsonResponse({'success': False, 'error': 'Member required for credit payment'})
            exceeded, limit_msg = member_credit_limit_exceeded(member, transaction.total_amount)
            if exceeded:
                transaction.status = 'cancelled'
                transaction.save()
                return JsonResponse({'success': False, 'error': limit_msg})
            if not _kiosk_can_apply_manual_discount(request):
                if member.balance >= transaction.total_amount:
                    transaction.status = 'cancelled'
                    transaction.save()
                    return JsonResponse({
                        'success': False,
                        'error': (
                            'You have enough balance for debit. '
                            'Use Pay with Debit, or pay with cash.'
                        ),
                    })
            transaction.amount_paid = Decimal('0.00')
            transaction.amount_from_balance = Decimal('0.00')
            transaction.status = 'completed'

        elif payment_method == 'cash':
            # Get cash amount from request, validate it's sufficient
            cash_amount = data.get('cash_amount')
            if cash_amount is not None:
                try:
                    cash_amount = Decimal(str(cash_amount))
                    if cash_amount < transaction.total_amount:
                        return JsonResponse({
                            'success': False, 
                            'error': f'Insufficient cash. Total: ₱{transaction.total_amount}, Received: ₱{cash_amount}'
                        })
                    transaction.amount_paid = cash_amount
                except (ValueError, TypeError):
                    return JsonResponse({'success': False, 'error': 'Invalid cash amount'})
            else:
                # If no cash_amount provided, assume exact payment
                transaction.amount_paid = transaction.total_amount
            transaction.status = 'completed'
        
        transaction.save()
        
        # Post-payment side-effects: last_transaction, fees, session management
        finalise_transaction(request, transaction, member, items, payment_method)
        
        if member:
            member.refresh_from_db()
        
        member_summary = build_member_summary(member, member_before_balance) if member else None
        
        change_amount = calculate_change(transaction.total_amount, transaction.amount_paid) if payment_method == 'cash' else Decimal('0.00')

        line_items = list(transaction.items.all())
        cart_line_discount_total = sum(
            (ti.manual_discount_php or Decimal('0.00')) for ti in line_items
        ).quantize(Decimal('0.01'))

        try:
            from admin_panel.audit import mark_audit_recorded, record_audit
            customer = (
                (member.full_name if member else None)
                or transaction.guest_customer_name
                or transaction.customer_display_name
                or 'Walk-in'
            )
            record_audit(
                'PURCHASE',
                actor=request.user if getattr(request.user, 'is_authenticated', False) else None,
                description=(
                    f"Sale {transaction.transaction_number}: ₱{transaction.total_amount} "
                    f"via {payment_method} for {customer}"
                ),
                request=request,
                object_type='Transaction',
                object_id=transaction.pk,
                metadata={
                    'transaction_number': transaction.transaction_number,
                    'payment_method': payment_method,
                    'total_amount': str(transaction.total_amount),
                    'item_count': len(line_items),
                    'customer': customer,
                },
            )
            mark_audit_recorded(request)
        except Exception:
            pass

        return JsonResponse({
            'success': True,
            'transaction': {
                'id': transaction.id,
                'transaction_number': transaction.transaction_number,
                'payment_method': transaction.payment_method,
                'subtotal': str(transaction.subtotal),
                'vatable_sale': str(transaction.vatable_sale),
                'vat_amount': str(transaction.vat_amount),
                'cart_line_discount_total': str(cart_line_discount_total),
                'items': [
                    {
                        'product_name': ti.product_name,
                        'quantity': qty_json(ti.quantity),
                        'quantity_display': ti.quantity_display,
                        'unit_price': str(ti.unit_price),
                        'total_price': str(ti.total_price),
                        'vat_amount': str(ti.vat_amount),
                        'vatable_sale': str(ti.vatable_sale),
                        'line_discount': str(ti.manual_discount_php or Decimal('0.00')),
                        'manual_discount_php': str(ti.manual_discount_php or Decimal('0.00')),
                        'gross_line_total': str(
                            (ti.unit_price * Decimal(ti.quantity)).quantize(Decimal('0.01'))
                        ),
                    } for ti in line_items
                ],
                'total_amount': str(transaction.total_amount),
                'amount_from_balance': str(transaction.amount_from_balance),
                'amount_paid': str(transaction.amount_paid),
                'change_amount': str(change_amount),
                'member': member_summary,
                'guest_customer_name': transaction.guest_customer_name or '',
                'customer_name': transaction.customer_display_name,
                'processed_by': user_processor_display(processed_by_user),
            }
        })
    
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
    except Product.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Product not found'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'Transaction failed: {str(e)}'})


@csrf_exempt
@require_http_methods(["POST"])
def print_receipt_local(request):
    """
    POST endpoint to print receipts on the server's default Windows printer.
    Expects JSON: { "text": "...receipt text..." } or { "html": "...", "text": "..." }
    If HTML is provided, prints the HTML directly to match the exact same template as manual printing.
    This endpoint attempts direct local print handlers. If these are not available or
    printing fails, it returns success: false with an error message.
    """
    try:
        data = json.loads(request.body)
        text = data.get('text', '')
        html = data.get('html', '')
        strict_html = bool(data.get('strict_html', False))

        def _resolve_configured_printer_name():
            """Get target printer from admin settings, fallback to Windows default when possible."""
            configured_printer = ""
            try:
                from admin_panel.models import PrinterSettings
                configured_printer = (PrinterSettings.get().printer_name or "").strip()
            except Exception:
                configured_printer = ""

            try:
                import win32print  # type: ignore
                return configured_printer or win32print.GetDefaultPrinter()
            except Exception:
                # Without win32print we can still print; if no configured printer, use default printer via notepad /p.
                return configured_printer

        def _get_configured_paper_size():
            """Read admin paper size setting; defaults to 57mm."""
            try:
                from admin_panel.models import PrinterSettings
                return (PrinterSettings.get().paper_size or "57mm").strip()
            except Exception:
                return "57mm"

        def _format_text_for_paper(raw_text, paper_size):
            """
            Normalize receipt text width so output matches selected paper size.
            This is especially important for RAW/notepad printing.
            """
            import textwrap

            width_map = {
                "57mm": 30,   # 57 mm narrow thermal
                "58mm": 32,   # 58 mm narrow thermal
                "80mm": 42,   # standard thermal
                "A4": 96,     # full page
            }
            line_width = width_map.get(paper_size, 32)

            normalized_lines = []
            for raw_line in (raw_text or "").replace("\r\n", "\n").split("\n"):
                line = raw_line.rstrip()
                if not line:
                    normalized_lines.append("")
                    continue

                # Preserve divider aesthetics if line is made of separators.
                if set(line.strip()) <= set("-=_*"):
                    normalized_lines.append((line.strip()[0] * min(line_width, max(10, len(line.strip())))))
                    continue

                wrapped = textwrap.wrap(
                    line,
                    width=line_width,
                    break_long_words=True,
                    break_on_hyphens=False,
                )
                if wrapped:
                    normalized_lines.extend(wrapped)
                else:
                    normalized_lines.append("")

            out = "\r\n".join(normalized_lines).rstrip()
            if not out.endswith("\r\n"):
                out += "\r\n\r\n"
            return out
        
        html_print_error = None
        # If HTML is provided, try to print it directly using the template formatting
        # This ensures the refund_receipt.html template is used with proper CSS styling
        if html:
            try:
                import tempfile
                import os
                import subprocess
                
                # Create a temporary HTML file with the receipt template
                with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as f:
                    f.write(html)
                    temp_file = f.name
                
                try:
                    # Try to print using Windows default browser/print handler
                    # This preserves the CSS formatting from refund_receipt.html
                    os.startfile(temp_file, 'print')
                    # Give it a moment to start printing
                    import time
                    time.sleep(1)
                    return JsonResponse({'success': True, 'message': 'Receipt sent to printer using HTML template'})
                except Exception as e:
                    # Do not open the temp HTML in browser.
                    # If direct print fails, capture the error and continue with caller fallback.
                    html_print_error = str(e)
                finally:
                    # Clean up temp file after a delay (give print time to start)
                    import threading
                    def cleanup():
                        import time
                        time.sleep(5)
                        try:
                            os.unlink(temp_file)
                        except:
                            pass
                    threading.Thread(target=cleanup, daemon=True).start()
            except Exception as e:
                # If HTML printing fails, fall through to text extraction
                html_print_error = str(e)

        # For exact receipt rendering requests, do not fall back to text mode.
        # Let caller decide next fallback (usually window.print on the same HTML page).
        if strict_html and html:
            return JsonResponse({
                'success': False,
                'error': f'Exact HTML printing failed: {html_print_error or "unknown error"}'
            })
        
        # Use provided text if available (it matches the HTML template exactly)
        # Only extract from HTML if text is not provided
        if not text and html:
            try:
                from html.parser import HTMLParser
                import re
                
                # Extract the receiptPaper element content - this is the same element used in manual print
                # Look for the receiptPaper div (by id or class) in the HTML
                receipt_paper_match = re.search(
                    r'<div[^>]*(?:id|class)=["\'][^"\']*receiptPaper[^"\']*["\'][^>]*>(.*?)</div>\s*(?:</div>|</body>)', 
                    html, 
                    re.DOTALL | re.IGNORECASE
                )
                
                if receipt_paper_match:
                    receipt_content = receipt_paper_match.group(1)
                else:
                    # Fallback: extract from body if receiptPaper not found
                    body_match = re.search(r'<body[^>]*>(.*?)</body>', html, re.DOTALL | re.IGNORECASE)
                    if body_match:
                        receipt_content = body_match.group(1)
                    else:
                        receipt_content = html
                
                # Extract text from HTML, preserving structure and formatting
                class ReceiptTextExtractor(HTMLParser):
                    def __init__(self):
                        super().__init__()
                        self.lines = []
                        self.current_line_parts = []
                        
                    def handle_data(self, data):
                        data = data.strip()
                        if data:
                            self.current_line_parts.append(data)
                            
                    def handle_starttag(self, tag, attrs):
                        attrs_dict = dict(attrs)
                        class_attr = attrs_dict.get('class', '')
                        # Section titles should be on their own line
                        if 'rp-section-title' in class_attr:
                            if self.current_line_parts:
                                self.lines.append(' '.join(self.current_line_parts))
                                self.current_line_parts = []
                        elif tag == 'br':
                            if self.current_line_parts:
                                self.lines.append(' '.join(self.current_line_parts))
                                self.current_line_parts = []
                                
                    def handle_endtag(self, tag):
                        if tag in ['div', 'li', 'p']:
                            if self.current_line_parts:
                                self.lines.append(' '.join(self.current_line_parts))
                                self.current_line_parts = []
                        elif tag == 'ul':
                            if self.current_line_parts:
                                self.lines.append(' '.join(self.current_line_parts))
                                self.current_line_parts = []
                                
                    def get_text(self):
                        if self.current_line_parts:
                            self.lines.append(' '.join(self.current_line_parts))
                        # Filter out empty lines and join with line breaks
                        return '\r\n'.join([line.strip() for line in self.lines if line.strip()])
                
                parser = ReceiptTextExtractor()
                parser.feed(receipt_content)
                extracted_text = parser.get_text()
                
                if extracted_text and len(extracted_text) > 50:
                    text = extracted_text
                else:
                    return JsonResponse({
                        'success': False, 
                        'error': 'Could not extract text content from HTML receipt template'
                    })
                    
            except Exception as e:
                return JsonResponse({
                    'success': False, 
                    'error': f'Failed to extract text from HTML template: {str(e)}'
                })
        
        # Fallback to text printing if HTML not available or HTML printing failed
        if not text:
            return JsonResponse({'success': False, 'error': 'No content available for printing'})
        paper_size = _get_configured_paper_size()
        text = _format_text_for_paper(text, paper_size)

        # Text printing using win32print (for thermal printers that need raw text)
        try:
            import win32print
        except ImportError:
            # Fallback path for environments without pywin32:
            # print a temporary text file silently using Notepad.
            try:
                import tempfile
                import os
                import subprocess
                import threading
                import time

                printer_name = _resolve_configured_printer_name()
                with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
                    f.write(text)
                    temp_file = f.name

                try:
                    if printer_name:
                        # /pt prints to specific printer; no browser print dialog.
                        cmd = f'notepad /pt "{temp_file}" "{printer_name}"'
                    else:
                        # /p prints to Windows default printer.
                        cmd = f'notepad /p "{temp_file}"'

                    # Use shell=True so Windows can resolve notepad command consistently.
                    subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True, timeout=20)

                    def cleanup():
                        time.sleep(5)
                        try:
                            os.unlink(temp_file)
                        except Exception:
                            pass

                    threading.Thread(target=cleanup, daemon=True).start()
                    target = printer_name or "Windows default printer"
                    return JsonResponse({'success': True, 'message': f'Receipt sent to printer: {target}'})
                except subprocess.CalledProcessError as e:
                    try:
                        os.unlink(temp_file)
                    except Exception:
                        pass
                    stderr_text = (e.stderr or "").strip()
                    raise Exception(stderr_text or str(e))
                except Exception:
                    try:
                        os.unlink(temp_file)
                    except Exception:
                        pass
                    raise
            except Exception as e:
                return JsonResponse({
                    'success': False,
                    'error': f'Printing module not available and fallback print failed: {str(e)}'
                })

        try:
            # Resolve printer target from admin settings, fallback to Windows default.
            try:
                printer_name = _resolve_configured_printer_name()
            except Exception as e:
                return JsonResponse({
                    'success': False, 
                    'error': (
                        f'No printer available. '
                        f'Check Printer Settings in admin or set a Windows default printer. Error: {str(e)}'
                    )
                })

            if not printer_name:
                return JsonResponse({
                    'success': False, 
                    'error': (
                        'No printer configured. Set a printer in Admin > Printer Settings, '
                        'or set a Windows default printer.'
                    )
                })

            # Open printer
            hPrinter = win32print.OpenPrinter(printer_name)
            try:
                # Start a RAW print job
                job_info = ("KioskReceipt", None, "RAW")
                job_id = win32print.StartDocPrinter(hPrinter, 1, job_info)
                try:
                    win32print.StartPagePrinter(hPrinter)
                    # Ensure text ends with newlines for proper printing
                    print_text = text
                    # Write bytes to printer (encode as utf-8)
                    win32print.WritePrinter(hPrinter, print_text.encode('utf-8'))
                    win32print.EndPagePrinter(hPrinter)
                except Exception as e:
                    # Try to abort the job if page printing fails
                    try:
                        win32print.AbortPrinter(hPrinter)
                    except:
                        pass
                    raise e
                finally:
                    win32print.EndDocPrinter(hPrinter)
            finally:
                win32print.ClosePrinter(hPrinter)

            return JsonResponse({'success': True, 'message': f'Receipt sent to printer: {printer_name}'})
        except Exception as e:
            error_msg = str(e)
            # Provide more helpful error messages
            if 'Access is denied' in error_msg or 'access denied' in error_msg.lower():
                return JsonResponse({
                    'success': False, 
                    'error': 'Access denied to printer. Please check printer permissions or try running the application as administrator.'
                })
            elif 'printer' in error_msg.lower() and 'not found' in error_msg.lower():
                return JsonResponse({
                    'success': False, 
                    'error': 'Printer not found. Please check that the printer is connected and set as default.'
                })
            else:
                return JsonResponse({
                    'success': False, 
                    'error': f'Printing failed: {error_msg}'
                })
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data received'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'Server error: {str(e)}'})


@require_http_methods(["POST"])
def api_kiosk_toggle_tax(request):
    """
    Toggle KioskConfig.tax_enabled on/off.
    Only admin, cashier, and staff (privileged kiosk roles) may call this.
    """
    # Permission: must be a privileged Django user or a privileged kiosk member session.
    is_privileged_django = request.user.is_authenticated and is_cashier_or_admin(request.user)
    session_member_id = get_kiosk_session_member_id(request)
    is_privileged_member = False
    if session_member_id:
        try:
            m = Member.objects.get(pk=session_member_id)
            is_privileged_member = m.role in ('admin', 'cashier', 'staff')
        except Exception:
            pass

    if not (is_privileged_django or is_privileged_member):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

    cfg = KioskConfig.get()
    cfg.tax_enabled = not cfg.tax_enabled
    cfg.save()

    active_tax = TaxRate.objects.filter(is_active=True).order_by('name').first()
    rate_info = None
    if active_tax:
        rate_info = {
            'rate': float(active_tax.rate),
            'rate_fraction': float(active_tax.rate / 100),
            'tax_type': active_tax.tax_type or 'inclusive',
            'name': active_tax.name,
        }
    return JsonResponse({'success': True, 'tax_enabled': cfg.tax_enabled, 'active_tax': rate_info})


@require_http_methods(["GET"])
def api_kiosk_tax_rate(request):
    """
    Return the active TaxRate record for the kiosk frontend.
    Used by the kiosk to resolve the live tax rate set in /admin/inventory/taxrate/.
    """
    active_tax = TaxRate.objects.filter(is_active=True).order_by('name').first()
    kiosk_cfg = KioskConfig.get()
    if active_tax:
        return JsonResponse({
            'tax_enabled': kiosk_cfg.tax_enabled,
            'rate': float(active_tax.rate),
            'rate_fraction': float(active_tax.rate / 100),
            'tax_type': active_tax.tax_type or 'inclusive',
            'name': active_tax.name,
        })
    return JsonResponse({
        'tax_enabled': kiosk_cfg.tax_enabled,
        'rate': None,
        'rate_fraction': None,
        'tax_type': None,
        'name': None,
    })
