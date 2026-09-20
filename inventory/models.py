import io
import json

import barcode
from barcode.writer import ImageWriter
from django.core.files.base import ContentFile
from django.core.validators import MinValueValidator
from django.db import models
from PIL import Image

from .units import UNIT_CHOICES, UNIT_KILO, UNIT_PIECE, format_qty_display

class Category(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Category"
        verbose_name_plural = "Categories"


class TaxRate(models.Model):
    """
    Named tax rate that can be assigned to products.
    Supports both inclusive (VAT-inclusive price) and exclusive (tax added on top) modes.
    """

    TAX_TYPE_CHOICES = [
        ('inclusive', 'Inclusive — tax is already embedded in the price'),
        ('exclusive', 'Exclusive — tax is added on top of the price'),
    ]

    name = models.CharField(
        max_length=100,
        unique=True,
        help_text='Label shown on receipts and admin (e.g. "VAT 12%", "Tax Exempt").',
    )
    rate = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=0.0000,
        help_text='Tax rate as a percentage (e.g. 12.0000 = 12%). Use 0 for tax-exempt.',
    )
    tax_type = models.CharField(
        max_length=10,
        choices=TAX_TYPE_CHOICES,
        default='inclusive',
        help_text='Inclusive: price already contains the tax. Exclusive: tax is added on top.',
    )
    is_active = models.BooleanField(default=True)
    description = models.TextField(
        blank=True,
        help_text='Optional internal notes (e.g. BIR code, applicable product categories).',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Tax rate'
        verbose_name_plural = 'Tax rates'
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.rate}%)'

    @property
    def rate_decimal(self):
        """Return rate as a fraction (e.g. 12 → 0.12)."""
        from decimal import Decimal
        return self.rate / Decimal('100')


class ProductDiscountGroup(models.Model):
    """
    Stable code + human-editable name for segment fixed-peso rules (see members.SegmentProductGroupDiscount).
    Product.discount_group points here; checkout keys rules by group code.
    """

    code = models.CharField(
        max_length=32,
        unique=True,
        db_index=True,
        help_text='Stable key used at checkout and in APIs (changing it breaks product links).',
    )
    name = models.CharField(max_length=120)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'code']
        verbose_name = 'Product discount group'
        verbose_name_plural = 'Product discount groups'

    def __str__(self):
        return self.name


class Product(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    barcode = models.CharField(max_length=100, unique=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True)
    
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name='Selling price',
        help_text='Retail / list selling price per piece or per kg (₱).',
    )
    cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        verbose_name='Buying price',
        help_text='Purchase / cost price per piece or per kg (₱). Used for margin tracking.',
    )
    unit_type = models.CharField(
        max_length=10,
        choices=UNIT_CHOICES,
        default=UNIT_PIECE,
        db_index=True,
        help_text='By piece = counted units. By kilogram = weighable goods with decimal kg stock.',
    )

    tax_rate = models.ForeignKey(
        TaxRate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='products',
        help_text='Tax rule applied to this product at checkout.',
    )

    discount_group = models.ForeignKey(
        ProductDiscountGroup,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='products',
        help_text=(
            'Used for fixed-peso member / senior–PWD discounts at checkout. '
            'Edit group display names under Inventory → Product discount groups.'
        ),
    )
    
    stock_quantity = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        default=0,
        validators=[MinValueValidator(0)],
        help_text='On-hand quantity in pieces or kilograms, matching unit type.',
    )
    low_stock_threshold = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        default=10,
        validators=[MinValueValidator(0)],
        help_text='Low-stock warning level in pieces or kilograms.',
    )
    
    image = models.ImageField(upload_to='products/', null=True, blank=True)
    barcode_image = models.ImageField(upload_to='products/barcodes/', null=True, blank=True)
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.barcode})"

    @property
    def discount_group_code(self):
        if self.discount_group_id:
            return self.discount_group.code
        return ''

    @property
    def is_low_stock(self):
        return self.stock_quantity <= self.low_stock_threshold

    @property
    def is_out_of_stock(self):
        return self.stock_quantity <= 0

    @property
    def stock_deficit(self):
        """Calculate how many units are below the threshold"""
        if self.stock_quantity <= 0:
            return self.low_stock_threshold
        elif self.stock_quantity < self.low_stock_threshold:
            return self.low_stock_threshold - self.stock_quantity
        return 0

    def generate_barcode_image(self):
        if not self.barcode:
            return
        # Choose Code128 which accepts any alphanumeric string
        barcode_class = barcode.get_barcode_class('code128')
        buffer = io.BytesIO()
        barcode_class(self.barcode, writer=ImageWriter()).write(buffer)
        filename = f"{self.barcode}.png"
        self.barcode_image.save(filename, ContentFile(buffer.getvalue()), save=False)

    def save(self, *args, **kwargs):
        # Regenerate barcode image when barcode value changes or image is missing
        old_barcode = None
        if self.pk:
            try:
                old_barcode = Product.objects.get(pk=self.pk).barcode
            except Product.DoesNotExist:
                pass
        if self.barcode and (not self.barcode_image or old_barcode != self.barcode):
            self.generate_barcode_image()
        super().save(*args, **kwargs)

    def add_stock(self, quantity):
        self.stock_quantity += quantity
        self.save()

    def reduce_stock(self, quantity):
        if self.stock_quantity >= quantity:
            self.stock_quantity -= quantity
            self.save()
            return True
        return False

    def get_stock_batch(self, tier):
        """Return the old or new stock batch for this product, if configured."""
        if (
            hasattr(self, '_prefetched_objects_cache')
            and 'stock_batches' in getattr(self, '_prefetched_objects_cache', {})
        ):
            for batch in self.stock_batches.all():
                if batch.tier == tier:
                    return batch
            return None
        return self.stock_batches.filter(tier=tier).first()

    @property
    def old_stock_batch(self):
        return self.get_stock_batch(ProductStockBatch.TIER_OLD)

    @property
    def new_stock_batch(self):
        return self.get_stock_batch(ProductStockBatch.TIER_NEW)

    @property
    def is_sold_by_kilo(self):
        return self.unit_type == UNIT_KILO

    @property
    def stock_unit_suffix(self):
        return 'kg' if self.is_sold_by_kilo else 'pcs'

    def format_stock(self, quantity=None, *, with_unit=True):
        qty = self.stock_quantity if quantity is None else quantity
        return format_qty_display(qty, self.unit_type, with_unit=with_unit)

    @property
    def is_giveaway(self):
        """All active products are eligible for staff Record Giveaway."""
        return self.is_active

    def get_sale_unit_by_barcode(self, barcode):
        """Resolve a scanned barcode to an active sale unit for this product."""
        if not barcode:
            return None
        return self.sale_units.filter(barcode=barcode, is_active=True).first()

    def dashboard_sale_units_payload(self):
        return [
            {
                'id': unit.id,
                'sale_mode': unit.sale_mode,
                'unit_label': unit.unit_label,
                'barcode': unit.barcode,
                'price': str(unit.price),
                'units_per_package': unit.units_per_package,
                'is_active': unit.is_active,
            }
            for unit in self.sale_units.order_by('sale_mode', 'id')
        ]

    @property
    def dashboard_sale_units_json(self):
        return json.dumps(self.dashboard_sale_units_payload())

    class Meta:
        verbose_name = "Product"
        verbose_name_plural = "Products"
        ordering = ['name']


class ProductSaleUnit(models.Model):
    """
    Alternate ways to sell the same product — e.g. pencil by piece (retail),
    rice by kilogram, or a box (wholesale). Stock is tracked on Product in
    pieces or kilograms; wholesale deducts quantity × units_per_package.
    """

    SALE_MODE_RETAIL = 'retail'
    SALE_MODE_WHOLESALE = 'wholesale'
    SALE_MODE_CHOICES = [
        (SALE_MODE_RETAIL, 'By piece (retail)'),
        (SALE_MODE_WHOLESALE, 'Wholesale (box / bulk)'),
    ]

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='sale_units',
    )
    sale_mode = models.CharField(
        max_length=20,
        choices=SALE_MODE_CHOICES,
        default=SALE_MODE_RETAIL,
        help_text='Retail = sold per piece or per kg. Wholesale = sold per box, pack, or case.',
    )
    unit_label = models.CharField(
        max_length=50,
        help_text='Shown on receipts and admin (e.g. "Piece", "Kilogram", "Box of 12").',
    )
    barcode = models.CharField(
        max_length=100,
        unique=True,
        help_text='Unique barcode for this sale unit (scan at checkout).',
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text='Selling price for one of this sale unit (one box, one piece, etc.).',
    )
    units_per_package = models.PositiveIntegerField(
        default=1,
        help_text=(
            'Base stock units consumed per 1 of this sale unit. '
            'Use 1 for per-piece or per-kg; e.g. 12 when one box contains 12 pencils.'
        ),
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Product sale unit'
        verbose_name_plural = 'Product sale units'
        ordering = ['sale_mode', 'unit_label']
        constraints = [
            models.UniqueConstraint(
                fields=['product', 'barcode'],
                name='unique_product_sale_unit_barcode',
            ),
        ]

    def __str__(self):
        return f'{self.product.name} — {self.unit_label} ({self.barcode})'

    def clean(self):
        from django.core.exceptions import ValidationError

        super().clean()
        if self.units_per_package < 1:
            raise ValidationError({'units_per_package': 'Must be at least 1.'})
        if self.price < 0:
            raise ValidationError({'price': 'Price cannot be negative.'})
        if (
            self.sale_mode == self.SALE_MODE_RETAIL
            and self.units_per_package != 1
        ):
            raise ValidationError({
                'units_per_package': 'Retail (by piece) units must use 1 piece per sale.',
            })
        if (
            self.sale_mode == self.SALE_MODE_WHOLESALE
            and self.units_per_package < 2
        ):
            raise ValidationError({
                'units_per_package': 'Wholesale units must contain at least 2 pieces per package.',
            })

    @property
    def stock_units_per_sale(self):
        """Pieces deducted from Product.stock_quantity per 1 sold."""
        return self.units_per_package


class GiveawayProduct(models.Model):
    """
    Marks a product as eligible for staff Record Giveaway distribution.
    Stock is deducted via the inventory giveaway modal; units given away are
    tracked on stock-out transactions with giveaway notes.
    """

    product = models.OneToOneField(
        Product,
        on_delete=models.CASCADE,
        related_name='giveaway',
    )
    is_active = models.BooleanField(
        default=True,
        help_text='Kept in sync for active products; all active inventory items are giveaway-eligible.',
    )
    notes = models.TextField(
        blank=True,
        help_text='Optional internal note (e.g. distribution program name).',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Giveaway product'
        verbose_name_plural = 'Giveaway products'
        ordering = ['product__name']

    def __str__(self):
        return f'Giveaway: {self.product.name}'


class ProductDiscount(models.Model):
    """
    Time-bound discount on a single product. Multiple rules may exist; checkout
    applies the single lowest resulting unit price. Managed in Django admin.
    """

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='discounts',
    )
    name = models.CharField(
        max_length=200,
        help_text='Short label (e.g. "Member weekend 10%").',
    )
    is_active = models.BooleanField(default=True)
    valid_from = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Optional. Blank = no start limit.',
    )
    valid_to = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Optional. Blank = no end date.',
    )
    discount_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Percent off list price (e.g. 15.00 = 15%). Leave blank if using fixed amount.',
    )
    discount_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Fixed amount off each unit. Leave blank if using percent.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Product discount'
        verbose_name_plural = 'Product discounts'

    def __str__(self):
        return f'{self.name} — {self.product.name}'

    def clean(self):
        from django.core.exceptions import ValidationError

        super().clean()
        pct = self.discount_percent
        amt = self.discount_amount
        has_pct = pct is not None
        has_amt = amt is not None
        if has_pct == has_amt:
            raise ValidationError('Set exactly one of percent discount or fixed amount per unit.')
        if has_pct:
            if pct <= 0 or pct > 100:
                raise ValidationError('Percent must be greater than 0 and at most 100.')
        else:
            if amt <= 0:
                raise ValidationError('Fixed discount must be greater than zero.')


class ProductStockBatch(models.Model):
    """
    Tracks old vs new inventory for a product.
    Each tier stores quantity plus selling price (unit_price) and buying price (cost).
    Each product may have at most one old-stock row and one new-stock row.
    """

    TIER_OLD = 'old'
    TIER_NEW = 'new'
    TIER_CHOICES = [
        (TIER_OLD, 'Old stock'),
        (TIER_NEW, 'New stock'),
    ]

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='stock_batches',
    )
    tier = models.CharField(
        max_length=10,
        choices=TIER_CHOICES,
        help_text='Old stock = remaining units. New stock = newly received units. Quantities are pieces or kg.',
    )
    quantity = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        default=0,
        validators=[MinValueValidator(0)],
        help_text='Units on hand in this tier (pieces or kilograms).',
    )
    unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name='Selling price',
        help_text='Selling price per piece or per kg for this stock tier (₱).',
    )
    cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        verbose_name='Buying price',
        help_text='Buying / purchase cost per piece or per kg for this stock tier (₱).',
    )
    notes = models.TextField(
        blank=True,
        help_text='Optional note (e.g. date received, supplier batch).',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Product stock batch'
        verbose_name_plural = 'Product stock batches'
        ordering = ['tier', '-updated_at']
        constraints = [
            models.UniqueConstraint(
                fields=['product', 'tier'],
                name='unique_product_stock_tier',
            ),
        ]

    def __str__(self):
        return f'{self.product.name} — {self.get_tier_display()} ({self.quantity} @ ₱{self.unit_price})'

    def clean(self):
        from django.core.exceptions import ValidationError

        super().clean()
        if self.quantity < 0:
            raise ValidationError({'quantity': 'Quantity cannot be negative.'})
        if self.unit_price < 0:
            raise ValidationError({'unit_price': 'Unit price cannot be negative.'})
        if self.cost < 0:
            raise ValidationError({'cost': 'Cost cannot be negative.'})


class StockTransaction(models.Model):
    TRANSACTION_TYPES = [
        ('in', 'Stock In'),
        ('out', 'Stock Out'),
        ('adjustment', 'Adjustment'),
    ]

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='stock_transactions')
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    quantity = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    stock_before = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    stock_after = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.product.name} - {self.transaction_type} - {self.quantity}"

    class Meta:
        verbose_name = "Stock Transaction"
        verbose_name_plural = "Stock Transactions"
        ordering = ['-created_at']


class ProductStockHistory(models.Model):
    """
    Audit log capturing every change to a product's stock and prices.
    Snapshots old/new stock tiers (before and after), total on hand, and
    selling/buying prices so inventory can monitor qty and price history.
    """

    CHANGE_CREATED = 'created'
    CHANGE_EDIT = 'edit'
    CHANGE_RESTOCK = 'restock'
    CHANGE_SALE = 'sale'
    CHANGE_PROMOTION = 'promotion'
    CHANGE_ADJUSTMENT = 'adjustment'
    CHANGE_REFUND = 'refund'
    CHANGE_PRICE = 'price'
    CHANGE_TYPE_CHOICES = [
        (CHANGE_CREATED, 'Product created'),
        (CHANGE_EDIT, 'Manual edit'),
        (CHANGE_RESTOCK, 'Restock'),
        (CHANGE_SALE, 'Sale'),
        (CHANGE_PROMOTION, 'New → Old promotion'),
        (CHANGE_ADJUSTMENT, 'Adjustment'),
        (CHANGE_REFUND, 'Refund restock'),
        (CHANGE_PRICE, 'Price change'),
    ]

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='stock_history',
    )
    change_type = models.CharField(
        max_length=20,
        choices=CHANGE_TYPE_CHOICES,
        default=CHANGE_EDIT,
    )

    old_stock_before = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    old_stock_after = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    new_stock_before = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    new_stock_after = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    total_before = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    total_after = models.DecimalField(max_digits=14, decimal_places=3, default=0)

    quantity_sold = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        default=0,
        help_text='Units sold in this event (only for sale changes).',
    )

    unit_price_before = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='Selling price before',
        help_text='Product selling price before this change.',
    )
    unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='Selling price after',
        help_text='Product selling price after this change.',
    )
    cost_before = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='Buying price before',
        help_text='Product buying price before this change.',
    )
    cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='Buying price after',
        help_text='Product buying price after this change.',
    )

    old_stock_price_before = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text='Old-stock tier selling price before.',
    )
    old_stock_price_after = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text='Old-stock tier selling price after.',
    )
    new_stock_price_before = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text='New-stock tier selling price before.',
    )
    new_stock_price_after = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text='New-stock tier selling price after.',
    )

    note = models.CharField(max_length=255, blank=True)
    changed_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Product stock history'
        verbose_name_plural = 'Product stock history'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['product', '-created_at'], name='inv_stockhist_prod_created_idx'),
        ]

    def __str__(self):
        return (
            f'{self.product.name} — {self.get_change_type_display()} '
            f'({self.total_before} → {self.total_after})'
        )

    @property
    def total_change(self):
        return self.total_after - self.total_before

    @property
    def price_changed(self):
        return (
            self.unit_price_before != self.unit_price
            or self.cost_before != self.cost
            or self.old_stock_price_before != self.old_stock_price_after
            or self.new_stock_price_before != self.new_stock_price_after
        )
