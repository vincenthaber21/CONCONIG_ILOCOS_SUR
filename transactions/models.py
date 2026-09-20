import secrets

from django.contrib.auth.models import User
from django.db import models
from members.models import Member
from inventory.models import Product
from django.conf import settings
from django.utils import timezone
from decimal import Decimal


def user_processor_display(user):
    """Human-readable staff/cashier name for receipts and reports."""
    if not user:
        return ''
    member = (
        Member.objects.filter(user_id=user.pk)
        .only('first_name', 'last_name')
        .first()
    )
    if member:
        return member.full_name
    full = user.get_full_name().strip()
    return full or user.username


class WalkInCustomer(models.Model):
    """Registered walk-in / non-member customer names from the kiosk."""

    name_key = models.CharField(
        max_length=200,
        unique=True,
        help_text="Normalized name for deduplication (case-insensitive).",
    )
    display_name = models.CharField(max_length=200)
    total_manual_discount_php = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Total manual Discount ₱ from completed walk-in sales (synced from line items).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "Walk-in customer"
        verbose_name_plural = "Walk-in customers"
        ordering = ["display_name"]

    def __str__(self):
        return self.display_name


class WalkInCustomerProductDiscount(models.Model):
    """Per-product manual discount totals for a walk-in customer (kiosk Discount ₱)."""

    walk_in_customer = models.ForeignKey(
        WalkInCustomer,
        on_delete=models.CASCADE,
        related_name='product_discounts',
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='walk_in_product_discounts',
    )
    product_name = models.CharField(max_length=200)
    total_manual_discount_php = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Sum of manual Discount ₱ for this product on completed sales.",
    )
    line_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of receipt lines with a manual discount for this product.",
    )
    last_sale_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Most recent completed sale date for this product discount row.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Walk-in product discount"
        verbose_name_plural = "Walk-in product discounts"
        ordering = ['-total_manual_discount_php', 'product_name']
        constraints = [
            models.UniqueConstraint(
                fields=['walk_in_customer', 'product_name'],
                name='uniq_walkin_product_discount_name',
            ),
        ]

    def __str__(self):
        return f'{self.walk_in_customer.display_name} — {self.product_name}: ₱{self.total_manual_discount_php}'


class Transaction(models.Model):
    PAYMENT_METHODS = [
        ('debit', 'Debit (Member Account)'),
        ('credit', 'Credit (Utang)'),
        ('cash', 'Cash'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('refund_requested', 'Refund Requested'),
        ('return_window', 'Return Window (Awaiting Item)'),
        ('partially_refunded', 'Partially Refunded'),
        ('refunded', 'Refunded'),
        ('return_expired', 'Return Expired (No Refund)'),
    ]

    transaction_number = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        help_text="Leave blank when creating in admin; a unique TXN number is assigned on save.",
    )
    member = models.ForeignKey(Member, on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions')
    guest_customer_name = models.CharField(
        max_length=200,
        blank=True,
        help_text="Walk-in customer name when no member is linked to the transaction.",
    )
    walk_in_customer = models.ForeignKey(
        WalkInCustomer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
    )

    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    # Vatable sale is the portion of the subtotal that is subject to VAT
    vatable_sale = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    vat_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    amount_from_balance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    notes = models.TextField(blank=True)
    credit_settled_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this credit (utang) sale was paid off at the dashboard.",
    )
    credit_payment = models.ForeignKey(
        "CreditPayment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="settled_sales",
    )
    credit_interest_accrued = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Total interest charged on this credit sale (after grace period).",
    )
    credit_interest_paid = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Interest amount already paid toward this credit sale.",
    )
    credit_interest_last_applied_on = models.DateField(
        null=True,
        blank=True,
        help_text="Date of the last monthly interest period applied.",
    )
    processed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='processed_transactions',
        help_text="Staff or cashier who processed this transaction (set on admin-assisted sales).",
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def customer_display_name(self):
        guest = (self.guest_customer_name or '').strip()
        if guest:
            return guest
        if self.member_id:
            return self.member.full_name
        return 'Guest'

    @property
    def processed_by_display(self):
        return user_processor_display(self.processed_by)

    @property
    def credit_interest_outstanding(self) -> Decimal:
        """Unpaid interest on this credit (utang) sale."""
        accrued = Decimal(self.credit_interest_accrued or 0).quantize(Decimal("0.01"))
        paid = Decimal(self.credit_interest_paid or 0).quantize(Decimal("0.01"))
        return max((accrued - paid).quantize(Decimal("0.01")), Decimal("0.00"))

    def __str__(self):
        num = self.transaction_number or "(pending)"
        return f"{num} - {self.customer_display_name}"

    def save(self, *args, **kwargs):
        if not (self.transaction_number or "").strip():
            from helper.kiosk_helper import generate_transaction_number

            for _ in range(24):
                candidate = generate_transaction_number()
                if not Transaction.objects.filter(transaction_number=candidate).exclude(
                    pk=self.pk
                ).exists():
                    self.transaction_number = candidate
                    break
            else:
                raise RuntimeError("Could not allocate a unique transaction_number")
        super().save(*args, **kwargs)

    def active_items(self):
        """Line items not yet refunded."""
        return self.items.filter(refunded_at__isnull=True)

    def recalculate_totals_from_active_items(self, save=True):
        """Recompute header amounts from lines that are not refunded."""
        active = list(self.active_items())
        subtotal = sum((item.total_price for item in active), Decimal('0.00'))
        vat_amount = sum((item.vat_amount for item in active), Decimal('0.00'))
        vatable_sale = sum((item.vatable_sale for item in active), Decimal('0.00'))
        # When tax is disabled, legacy lines may have zero VAT fields — fall back to subtotal.
        if (vat_amount + vatable_sale) == 0 and subtotal > 0:
            vatable_sale = subtotal
        self.subtotal = subtotal.quantize(Decimal('0.01'))
        self.vat_amount = vat_amount.quantize(Decimal('0.01'))
        self.vatable_sale = vatable_sale.quantize(Decimal('0.01'))
        self.total_amount = (self.vat_amount + self.vatable_sale).quantize(Decimal('0.01'))
        if save:
            self.save(
                update_fields=[
                    'subtotal', 'vat_amount', 'vatable_sale', 'total_amount', 'updated_at',
                ]
            )

    def calculate_totals(self):
        # Sum per-item totals and per-item VAT amounts to avoid mismatches.
        # Sum per-item totals (non-refunded lines only when any line was refunded)
        qs = self.items.all()
        if self.items.filter(refunded_at__isnull=False).exists():
            qs = self.active_items()
        subtotal = sum((item.total_price for item in qs), Decimal('0.00'))
        vat_amount = sum((item.vat_amount for item in qs), Decimal('0.00'))
        vatable_sale = sum((item.vatable_sale for item in qs), Decimal('0.00'))

        # total = vat_total + vatable_sale (per your formula).
        # Tax-disabled / legacy lines may store VAT fields as zero — use subtotal.
        if (vat_amount + vatable_sale) == 0 and subtotal > 0:
            vatable_sale = subtotal
        total_amount = vat_amount + vatable_sale

        # Quantize to 2 decimal places (currency)
        self.subtotal = Decimal(subtotal).quantize(Decimal('0.01'))
        self.vatable_sale = Decimal(vatable_sale).quantize(Decimal('0.01'))
        self.vat_amount = Decimal(vat_amount).quantize(Decimal('0.01'))
        self.total_amount = Decimal(total_amount).quantize(Decimal('0.01'))
        self.save()

    class Meta:
        verbose_name = "Transaction"
        verbose_name_plural = "Transactions"
        ordering = ['-created_at']


class TransactionItem(models.Model):
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True)
    
    product_name = models.CharField(max_length=200)
    product_barcode = models.CharField(max_length=100)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.DecimalField(max_digits=14, decimal_places=3, default=1)
    manual_discount_php = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        help_text="Additional peso discount for this line from the kiosk cart (Discount ₱).",
    )
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    vat_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    vatable_sale = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    credit_settled_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this line on a credit sale was paid off (partial utang settlement).",
    )
    credit_payment = models.ForeignKey(
        "CreditPayment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="settled_items",
    )
    credit_amount_paid = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Peso amount already paid toward this line on open credit sales.",
    )
    refunded_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this line was refunded (partial or full refund).",
    )

    created_at = models.DateTimeField(default=timezone.now)

    @property
    def is_refunded(self):
        return self.refunded_at is not None

    @property
    def quantity_display(self):
        from inventory.units import UNIT_KILO, UNIT_PIECE, format_qty_display

        unit_type = UNIT_PIECE
        if self.product_id and getattr(self.product, 'unit_type', None):
            unit_type = self.product.unit_type
        elif self.quantity is not None and Decimal(self.quantity) != Decimal(self.quantity).to_integral_value():
            unit_type = UNIT_KILO
        return format_qty_display(self.quantity, unit_type, with_unit=True)

    @property
    def credit_line_amount(self) -> Decimal:
        """Amount owed for this line (VAT-inclusive line total)."""
        return (self.vat_amount + self.vatable_sale).quantize(Decimal("0.01"))

    @property
    def credit_line_outstanding(self) -> Decimal:
        """Remaining utang for this line after prior partial payments."""
        paid = Decimal(self.credit_amount_paid or 0).quantize(Decimal("0.01"))
        owing = (self.credit_line_amount - paid).quantize(Decimal("0.01"))
        return max(owing, Decimal("0.00"))

    def save(self, *args, **kwargs):
        # Calculate total price and VAT per line item using Decimal arithmetic
        qty_dec = Decimal(self.quantity)
        line_gross = (self.unit_price * qty_dec).quantize(Decimal('0.01'))
        disc = self.manual_discount_php if self.manual_discount_php is not None else Decimal('0.00')
        disc = Decimal(str(disc)).quantize(Decimal('0.01'))
        if disc < 0:
            disc = Decimal('0.00')
        if disc > line_gross:
            disc = line_gross
        self.manual_discount_php = disc
        self.total_price = (line_gross - disc).quantize(Decimal('0.01'))

        # Check global tax toggle from KioskConfig.
        try:
            from admin_panel.models import KioskConfig as _KC
            _tax_enabled = _KC.get().tax_enabled
        except Exception:
            _tax_enabled = True

        if not _tax_enabled:
            # Tax disabled system-wide — no VAT split, but the full line
            # amount must still flow into transaction.total_amount
            # (total = vat_amount + vatable_sale).
            self.vat_amount = Decimal('0.00')
            self.vatable_sale = self.total_price
        else:
            # Resolve tax rate: prefer the product's assigned TaxRate, then the active TaxRate
            # from admin (inventory/taxrate), and finally fall back to the global Django setting.
            vat_rate = Decimal(str(settings.VAT_RATE))
            tax_type = 'inclusive'
            try:
                product = self.product  # uses cached FK instance when available
                if product is not None and product.tax_rate_id:
                    tr = product.tax_rate
                    vat_rate = (tr.rate / Decimal('100')).quantize(Decimal('0.000001'))
                    tax_type = tr.tax_type or 'inclusive'
                else:
                    # No per-product rate — use the active TaxRate configured in admin.
                    from inventory.models import TaxRate as _TaxRate
                    active_tr = _TaxRate.objects.filter(is_active=True).order_by('name').first()
                    if active_tr:
                        vat_rate = (active_tr.rate / Decimal('100')).quantize(Decimal('0.000001'))
                        tax_type = active_tr.tax_type or 'inclusive'
            except Exception:
                pass

            if tax_type == 'exclusive':
                # Tax is added on top of the net price.
                vat = (self.total_price * vat_rate)
                self.vatable_sale = self.total_price.quantize(Decimal('0.01'))
                self.vat_amount = vat.quantize(Decimal('0.01'))
                self.total_price = (self.total_price + vat).quantize(Decimal('0.01'))
            else:
                # Tax is embedded in the price (inclusive): tax = price × rate / (1 + rate)
                divisor = Decimal('1') + vat_rate
                vat = (self.total_price * vat_rate / divisor).quantize(Decimal('0.01'))
                vatable = (self.total_price - vat).quantize(Decimal('0.01'))
                self.vat_amount = vat
                self.vatable_sale = vatable

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.product_name} x {self.quantity}"


class RefundReason(models.Model):
    REASON_CHOICES = [
        ('defective',          'Defective / Damaged Product'),
        ('wrong_item',         'Wrong Item Received'),
        ('change_of_mind',     'Change of Mind'),
        ('overcharged',        'Overcharged / Billing Error'),
        ('duplicate',          'Duplicate Transaction'),
        ('not_received',       'Item Not Received'),
        ('product_unavailable','Product Unavailable / Out of Stock'),
        ('expired',            'Expired Product'),
        ('other',              'Other'),
    ]

    transaction = models.OneToOneField(
        Transaction, on_delete=models.CASCADE, related_name='refund_reason'
    )
    reason_type = models.CharField(
        max_length=30, choices=REASON_CHOICES, default='other',
        verbose_name='Reason Category'
    )
    details = models.TextField(
        blank=True,
        verbose_name='Additional Details',
        help_text='Describe the specific reason for the refund request.'
    )
    refund_items = models.ManyToManyField(
        'TransactionItem',
        blank=True,
        related_name='refund_reasons',
        verbose_name='Items to Refund',
        help_text='Specific items the member wants refunded. Empty means all items.'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.transaction.transaction_number} — {self.get_reason_type_display()}"

    class Meta:
        verbose_name = "Refund Reason"
        verbose_name_plural = "Refund Reasons"


class RefundReturnWindow(models.Model):
    """Tracks the 3-day return window after an admin approves a refund request.
    The member must physically return the item within 3 days.
    If they do not return it, the refund is NOT processed.
    """
    RETURN_WINDOW_DAYS = 3

    transaction = models.OneToOneField(
        Transaction, on_delete=models.CASCADE, related_name='return_window'
    )
    approved_at = models.DateTimeField(auto_now_add=True)
    return_deadline = models.DateTimeField()
    is_returned = models.BooleanField(default=False)
    return_confirmed_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='approved_return_windows'
    )

    def save(self, *args, **kwargs):
        if not self.pk and not self.return_deadline:
            from django.utils import timezone
            from datetime import timedelta
            self.return_deadline = timezone.now() + timedelta(days=self.RETURN_WINDOW_DAYS)
        super().save(*args, **kwargs)

    def is_expired(self):
        from django.utils import timezone
        return not self.is_returned and timezone.now() > self.return_deadline

    def days_remaining(self):
        from django.utils import timezone
        delta = self.return_deadline - timezone.now()
        return max(0, delta.days)

    def __str__(self):
        return f"{self.transaction.transaction_number} — deadline {self.return_deadline.date()}"

    class Meta:
        verbose_name = "Refund Return Window"
        verbose_name_plural = "Refund Return Windows"


class CreditPayment(models.Model):
    """Records a member paying off outstanding credit (utang) sales."""

    PAYMENT_METHODS = [
        ("cash", "Cash"),
        ("debit", "Debit (Member Balance)"),
    ]

    settlement_number = models.CharField(
        max_length=32,
        unique=True,
        db_index=True,
        editable=False,
    )
    member = models.ForeignKey(
        Member,
        on_delete=models.PROTECT,
        related_name="credit_payments",
    )
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2)
    interest_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Portion of amount_paid applied to credit interest.",
    )
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS)
    balance_before = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Member balance before payment when paid via debit.",
    )
    balance_after = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Member balance after payment when paid via debit.",
    )
    performed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="credit_payments_performed",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.settlement_number:
            for _ in range(24):
                candidate = f"SET-{secrets.token_hex(6).upper()}"
                if not CreditPayment.objects.filter(settlement_number=candidate).exclude(
                    pk=self.pk
                ).exists():
                    self.settlement_number = candidate
                    break
            else:
                raise RuntimeError("Could not allocate a unique settlement_number")
        super().save(*args, **kwargs)

    @property
    def performed_by_display(self):
        return user_processor_display(self.performed_by)

    def __str__(self):
        return f"{self.settlement_number} — {self.member.full_name} ₱{self.amount_paid}"

    class Meta:
        verbose_name = "Credit payment"
        verbose_name_plural = "Credit payments"
        ordering = ["-created_at"]


class CreditPaymentLine(models.Model):
    """Per-product amount applied in a single credit settlement payment."""

    payment = models.ForeignKey(
        CreditPayment,
        on_delete=models.CASCADE,
        related_name="payment_lines",
    )
    item = models.ForeignKey(
        TransactionItem,
        on_delete=models.CASCADE,
        related_name="credit_payment_lines",
    )
    amount_applied = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = "Credit payment line"
        verbose_name_plural = "Credit payment lines"
        ordering = ["item__transaction__created_at", "item__transaction_id", "item_id"]

    def __str__(self):
        return f"{self.payment.settlement_number} — {self.item.product_name} ₱{self.amount_applied}"
