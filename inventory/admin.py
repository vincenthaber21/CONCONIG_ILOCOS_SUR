import base64
import io

import barcode
from barcode.writer import SVGWriter
from django.contrib import admin
from django.contrib import messages
from django.db.models import Count, Sum, Value
from django.db.models.functions import Coalesce
from django.utils.html import format_html
from import_export.admin import ExportMixin, ImportExportModelAdmin

from .models import (
    Category,
    GiveawayProduct,
    Product,
    ProductDiscount,
    ProductDiscountGroup,
    ProductSaleUnit,
    ProductStockBatch,
    ProductStockHistory,
    StockTransaction,
    TaxRate,
)
from .resources import (
    CategoryResource,
    GiveawayProductResource,
    ProductDiscountGroupResource,
    ProductDiscountResource,
    ProductResource,
    ProductSaleUnitResource,
    ProductStockBatchResource,
    ProductStockHistoryResource,
    StockTransactionResource,
    TaxRateResource,
)
from .utils import _giveaway_stock_filter


@admin.register(TaxRate)
class TaxRateAdmin(ImportExportModelAdmin):
    resource_classes = [TaxRateResource]
    change_list_template = 'admin/inventory/taxrate/change_list.html'
    list_display = (
        'name',
        'tax_type_badge',
        'products_assigned',
        'status_badge',
        'updated_at',
        'rate',
    )
    list_display_links = ('name',)
    list_filter = ('tax_type', 'is_active')
    search_fields = ('name', 'description')
    # Edit rate % directly from the list — no need to open each record.
    list_editable = ('rate',)
    readonly_fields = ('created_at', 'updated_at', 'products_assigned_detail')
    save_on_top = True
    actions = [
        'enable_tax_rates',
        'disable_tax_rates',
        'apply_to_all_products',
        'apply_to_unassigned_products',
        'remove_from_products',
    ]
    fieldsets = (
        ('Tax Rate Settings', {
            'description': (
                '<strong>Tip:</strong> Change <em>Rate (%)</em> here and click Save — '
                'the new rate will immediately apply at checkout for all products '
                'assigned to this tax rate. '
                'Use <em>Actions → Apply to all products</em> to bulk-assign this rate to every product.'
            ),
            'fields': ('name', 'rate', 'tax_type', 'is_active'),
        }),
        ('Products using this rate', {
            'fields': ('products_assigned_detail',),
        }),
        ('Notes', {
            'fields': ('description',),
            'classes': ('collapse',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .annotate(_product_count=Count('products', distinct=True))
        )

    def changelist_view(self, request, extra_context=None):
        from admin_panel.models import KioskConfig
        from django.shortcuts import redirect
        from django.urls import reverse

        if request.method == 'POST' and '_toggle_system_tax' in request.POST:
            cfg = KioskConfig.get()
            action = request.POST.get('tax_system_action')
            if action == 'enable':
                cfg.tax_enabled = True
                cfg.save(update_fields=['tax_enabled'])
                self.message_user(
                    request,
                    'System-wide tax calculation has been enabled.',
                    level=messages.SUCCESS,
                )
            elif action == 'disable':
                cfg.tax_enabled = False
                cfg.save(update_fields=['tax_enabled'])
                self.message_user(
                    request,
                    'System-wide tax calculation has been disabled.',
                    level=messages.WARNING,
                )
            return redirect(reverse('admin:inventory_taxrate_changelist'))

        extra_context = extra_context or {}
        kiosk_cfg = KioskConfig.get()
        extra_context['tax_system_enabled'] = kiosk_cfg.tax_enabled
        extra_context['active_tax_rate'] = (
            TaxRate.objects.filter(is_active=True).order_by('name').first()
        )
        return super().changelist_view(request, extra_context=extra_context)

    # ------------------------------------------------------------------ #
    #  List columns                                                        #
    # ------------------------------------------------------------------ #

    @admin.display(description='Status', ordering='is_active')
    def status_badge(self, obj):
        if obj.is_active:
            return format_html(
                '<span style="'
                'background:#ED1C24;color:#fff;padding:2px 8px;border-radius:4px;'
                'font-size:0.78rem;font-weight:600;white-space:nowrap;">Enabled</span>'
            )
        return format_html(
            '<span style="'
            'background:#888;color:#fff;padding:2px 8px;border-radius:4px;'
            'font-size:0.78rem;font-weight:600;white-space:nowrap;">Disabled</span>'
        )

    @admin.display(description='Type', ordering='tax_type')
    def tax_type_badge(self, obj):
        if obj.tax_type == 'inclusive':
            color, label = '#ED1C24', 'Inclusive'
        else:
            color, label = '#0066cc', 'Exclusive'
        return format_html(
            '<span style="'
            'background:{};color:#fff;padding:2px 8px;border-radius:4px;'
            'font-size:0.78rem;font-weight:600;white-space:nowrap;">{}</span>',
            color, label,
        )

    @admin.display(description='Products assigned', ordering='_product_count')
    def products_assigned(self, obj):
        count = getattr(obj, '_product_count', 0) or 0
        if count == 0:
            return format_html('<span style="color:#999;">0</span>')
        url = (
            f'../product/?tax_rate__id__exact={obj.pk}'
        )
        return format_html(
            '<a href="{}" style="font-weight:600;color:#ED1C24;">{} product{}</a>',
            url,
            count,
            's' if count != 1 else '',
        )

    # ------------------------------------------------------------------ #
    #  Detail view — products list                                         #
    # ------------------------------------------------------------------ #

    @admin.display(description='Products currently using this rate')
    def products_assigned_detail(self, obj):
        products = Product.objects.filter(tax_rate=obj, is_active=True).order_by('name')[:50]
        if not products:
            return 'No active products assigned to this tax rate yet.'
        rows = ''.join(
            f'<li style="padding:2px 0;">{p.name} &nbsp;<span style="color:#888;font-size:0.82rem;">({p.barcode})</span></li>'
            for p in products
        )
        return format_html(
            '<ul style="margin:0;padding-left:18px;max-height:220px;overflow-y:auto;">{}</ul>',
            rows,
        )

    # ------------------------------------------------------------------ #
    #  Admin actions                                                       #
    # ------------------------------------------------------------------ #

    @admin.action(description='Enable selected tax rate(s)')
    def enable_tax_rates(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(
            request,
            f'{updated} tax rate(s) enabled.',
            level=messages.SUCCESS,
        )

    @admin.action(description='Disable selected tax rate(s)')
    def disable_tax_rates(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(
            request,
            f'{updated} tax rate(s) disabled.',
            level=messages.WARNING,
        )

    @admin.action(description='Apply selected rate to ALL products (overwrites existing)')
    def apply_to_all_products(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(
                request,
                'Select exactly one tax rate to apply to all products.',
                level=messages.WARNING,
            )
            return
        tax_rate = queryset.first()
        updated = Product.objects.update(tax_rate=tax_rate)
        self.message_user(
            request,
            f'"{tax_rate.name} ({tax_rate.rate}%)" applied to {updated} product(s).',
            level=messages.SUCCESS,
        )

    @admin.action(description='Apply selected rate to products that have NO tax rate assigned')
    def apply_to_unassigned_products(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(
                request,
                'Select exactly one tax rate to apply to unassigned products.',
                level=messages.WARNING,
            )
            return
        tax_rate = queryset.first()
        updated = Product.objects.filter(tax_rate__isnull=True).update(tax_rate=tax_rate)
        if updated:
            self.message_user(
                request,
                f'"{tax_rate.name} ({tax_rate.rate}%)" applied to {updated} unassigned product(s).',
                level=messages.SUCCESS,
            )
        else:
            self.message_user(
                request,
                'All products already have a tax rate assigned — nothing changed.',
                level=messages.INFO,
            )

    @admin.action(description='Remove selected rate from all products that use it')
    def remove_from_products(self, request, queryset):
        total = 0
        for tax_rate in queryset:
            updated = Product.objects.filter(tax_rate=tax_rate).update(tax_rate=None)
            total += updated
        self.message_user(
            request,
            f'Tax rate removed from {total} product(s).',
            level=messages.SUCCESS if total else messages.INFO,
        )


@admin.register(ProductDiscountGroup)
class ProductDiscountGroupAdmin(ImportExportModelAdmin):
    resource_classes = [ProductDiscountGroupResource]
    list_display = ('code', 'name', 'sort_order')
    list_editable = ('name', 'sort_order')
    ordering = ('sort_order', 'code')
    search_fields = ('code', 'name')


class ProductDiscountInline(admin.TabularInline):
    model = ProductDiscount
    extra = 0
    fields = ('name', 'is_active', 'valid_from', 'valid_to', 'discount_percent', 'discount_amount')


class ProductStockBatchInline(admin.TabularInline):
    model = ProductStockBatch
    extra = 0
    max_num = 2
    fields = ('tier', 'quantity', 'unit_price', 'cost', 'notes', 'updated_at')
    readonly_fields = ('updated_at',)
    verbose_name = 'Stock tier'
    verbose_name_plural = 'Old / new stock (price per tier)'

    def get_extra(self, request, obj=None, **kwargs):
        if obj is None:
            return 0
        existing = obj.stock_batches.count()
        return max(0, 2 - existing)


class ProductSaleUnitInline(admin.TabularInline):
    model = ProductSaleUnit
    extra = 1
    fields = (
        'sale_mode',
        'unit_label',
        'barcode',
        'price',
        'units_per_package',
        'is_active',
    )
    verbose_name = 'Sale unit'
    verbose_name_plural = 'Sale units (by piece & wholesale)'


@admin.register(ProductSaleUnit)
class ProductSaleUnitAdmin(ImportExportModelAdmin):
    resource_classes = [ProductSaleUnitResource]
    list_display = (
        'product',
        'sale_mode',
        'unit_label',
        'barcode',
        'price',
        'units_per_package',
        'is_active',
    )
    list_filter = ('sale_mode', 'is_active')
    search_fields = ('product__name', 'product__barcode', 'barcode', 'unit_label')
    autocomplete_fields = ('product',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(ProductStockBatch)
class ProductStockBatchAdmin(ImportExportModelAdmin):
    resource_classes = [ProductStockBatchResource]
    list_display = (
        'product',
        'tier',
        'quantity',
        'unit_price',
        'cost',
        'updated_at',
    )
    list_filter = ('tier',)
    search_fields = ('product__name', 'product__barcode', 'notes')
    autocomplete_fields = ('product',)
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('product__name', 'tier')


@admin.register(ProductDiscount)
class ProductDiscountAdmin(ImportExportModelAdmin):
    resource_classes = [ProductDiscountResource]
    list_display = (
        'name',
        'product',
        'discount_summary',
        'is_active',
        'valid_from',
        'valid_to',
        'updated_at',
    )
    list_filter = ('is_active',)
    search_fields = ('name', 'product__name', 'product__barcode')
    autocomplete_fields = ('product',)
    readonly_fields = ('created_at', 'updated_at')

    @admin.display(description='Discount')
    def discount_summary(self, obj):
        if obj.discount_percent is not None:
            return f'{obj.discount_percent}% off'
        if obj.discount_amount is not None:
            return f'₱{obj.discount_amount} off / unit'
        return '—'


@admin.register(GiveawayProduct)
class GiveawayProductAdmin(ImportExportModelAdmin):
    resource_classes = [GiveawayProductResource]
    list_display = (
        'product',
        'is_active',
        'units_given_away_display',
        'product_stock_display',
        'updated_at',
    )
    list_filter = ('is_active',)
    search_fields = ('product__name', 'product__barcode', 'notes')
    autocomplete_fields = ('product',)
    readonly_fields = ('created_at', 'updated_at', 'units_given_away_display')

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related('product')
            .annotate(
                units_given_away=Coalesce(
                    Sum(
                        'product__stock_transactions__quantity',
                        filter=_giveaway_stock_filter('product'),
                    ),
                    Value(0),
                ),
            )
        )

    @admin.display(description='Given away', ordering='units_given_away')
    def units_given_away_display(self, obj):
        count = int(getattr(obj, 'units_given_away', 0) or 0)
        if count:
            return format_html('<strong>{}</strong>', count)
        return '0'

    @admin.display(description='Stock on hand', ordering='product__stock_quantity')
    def product_stock_display(self, obj):
        return obj.product.stock_quantity


@admin.register(Category)
class CategoryAdmin(ImportExportModelAdmin):
    resource_classes = [CategoryResource]
    list_display = ['name', 'is_active', 'created_at']
    list_filter = ['is_active']
    search_fields = ['name']


@admin.register(Product)
class ProductAdmin(ImportExportModelAdmin):
    resource_classes = [ProductResource]
    inlines = [ProductSaleUnitInline, ProductStockBatchInline, ProductDiscountInline]
    list_display = [
        'name',
        'barcode',
        'barcode_image_preview',
        'category',
        'unit_type',
        'discount_group',
        'tax_rate',
        'price',
        'old_stock_display',
        'new_stock_display',
        'stock_quantity',
        'is_low_stock',
        'is_active',
    ]
    list_filter = ['is_active', 'unit_type', 'category', 'discount_group', 'tax_rate']
    search_fields = ['name', 'barcode']
    autocomplete_fields = ['discount_group', 'tax_rate']
    readonly_fields = ['barcode_image', 'created_at', 'updated_at']

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        raw = request.GET.get('discount_group')
        if not raw:
            return initial
        try:
            pk = int(raw)
        except (TypeError, ValueError):
            return initial
        if ProductDiscountGroup.objects.filter(pk=pk).exists():
            initial['discount_group'] = pk
        return initial

    @admin.display(description='Barcode Preview')
    def barcode_image_preview(self, obj):
        if not obj.barcode:
            return '-'
        try:
            barcode_class = barcode.get_barcode_class('code128')
            buffer = io.BytesIO()
            barcode_class(
                obj.barcode,
                writer=SVGWriter(),
            ).write(buffer, options={
                'write_text': True,
                'module_height': 5.0,
                'module_width': 0.4,
                'font_size': 4,
                'text_distance': 2.0,
                'quiet_zone': 1.0,
            })
            svg_data = buffer.getvalue().decode('utf-8')
            # Encode as base64 data URI for safe embedding
            b64 = base64.b64encode(svg_data.encode('utf-8')).decode('ascii')
            return format_html(
                '<img src="data:image/svg+xml;base64,{}" height="30" style="max-width:90px;" />',
                b64,
            )
        except Exception:
            # Fallback: show the barcode text
            return obj.barcode

    @admin.display(description='Old stock')
    def old_stock_display(self, obj):
        batch = obj.old_stock_batch
        if not batch or batch.quantity == 0:
            return format_html('<span style="color:#999;">—</span>')
        return format_html(
            '<span title="Old stock sell/buy">{} · sell ₱{} · buy ₱{}</span>',
            batch.quantity,
            batch.unit_price,
            batch.cost,
        )

    @admin.display(description='New stock')
    def new_stock_display(self, obj):
        batch = obj.new_stock_batch
        if not batch or batch.quantity == 0:
            return format_html('<span style="color:#999;">—</span>')
        return format_html(
            '<span title="New stock sell/buy">{} · sell ₱{} · buy ₱{}</span>',
            batch.quantity,
            batch.unit_price,
            batch.cost,
        )

    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'description', 'barcode', 'category', 'image', 'barcode_image')
        }),
        ('Pricing', {
            'fields': ('price', 'cost', 'unit_type', 'tax_rate', 'discount_group'),
            'description': (
                'Assign a <strong>Tax rate</strong> to apply VAT or other taxes at checkout '
                '(managed under Inventory → Tax rates). '
                'Segment discounts at checkout: choose a <strong>Product discount group</strong> so member / '
                'senior–PWD fixed-peso rules apply (configured under Members → Segment product discounts). '
                'Promotional price rules are added below as product discounts.'
            ),
        }),
        ('Inventory', {
            'fields': ('stock_quantity', 'low_stock_threshold'),
            'description': (
                '<strong>Stock quantity</strong> is counted in pieces or kilograms, matching <strong>Sold by</strong>. '
                'Add <strong>Sale units</strong> below for by-piece retail and wholesale box pricing — '
                'each unit gets its own barcode and price; wholesale deducts '
                '<em>units per package</em> from stock per box sold. '
                'Kilogram products do not use wholesale boxes. '
                'Use <strong>Old / new stock</strong> to split remaining units by price tier. '
                'Total <em>Stock quantity</em> should match old + new on hand.'
            ),
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(StockTransaction)
class StockTransactionAdmin(ExportMixin, admin.ModelAdmin):
    resource_classes = [StockTransactionResource]
    list_display = ['product', 'transaction_type', 'quantity', 'stock_after', 'created_at']
    list_filter = ['transaction_type', 'created_at']
    search_fields = ['product__name']
    readonly_fields = ['created_at']


@admin.register(ProductStockHistory)
class ProductStockHistoryAdmin(ExportMixin, admin.ModelAdmin):
    resource_classes = [ProductStockHistoryResource]
    list_display = [
        'product',
        'change_type',
        'total_before',
        'total_after',
        'unit_price_before',
        'unit_price',
        'cost_before',
        'cost',
        'quantity_sold',
        'changed_by',
        'created_at',
    ]
    list_filter = ['change_type', 'created_at']
    search_fields = ['product__name', 'product__barcode', 'note']
    autocomplete_fields = ['product']
    readonly_fields = [
        'product',
        'change_type',
        'old_stock_before',
        'old_stock_after',
        'new_stock_before',
        'new_stock_after',
        'total_before',
        'total_after',
        'quantity_sold',
        'unit_price_before',
        'unit_price',
        'cost_before',
        'cost',
        'old_stock_price_before',
        'old_stock_price_after',
        'new_stock_price_before',
        'new_stock_price_after',
        'note',
        'changed_by',
        'created_at',
    ]
    ordering = ['-created_at']

    def has_add_permission(self, request):
        return False
