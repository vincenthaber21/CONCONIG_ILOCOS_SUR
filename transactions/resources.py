"""Import/export resources for transaction / purchase / revenue models."""

from import_export import fields, resources
from import_export.widgets import ForeignKeyWidget

from django.contrib.auth.models import User
from inventory.models import Product
from members.models import Member
from helper.import_export_widgets import LenientForeignKeyWidget

from .models import (
    CreditPayment,
    CreditPaymentLine,
    RefundReason,
    RefundReturnWindow,
    Transaction,
    TransactionItem,
    WalkInCustomer,
    WalkInCustomerProductDiscount,
)


def _blank_to_none(row, *keys):
    for key in keys:
        if key in row and (row[key] is None or str(row[key]).strip() == ''):
            row[key] = None


class WalkInCustomerResource(resources.ModelResource):
    class Meta:
        model = WalkInCustomer
        fields = (
            'id',
            'name_key',
            'display_name',
            'total_manual_discount_php',
            'last_seen_at',
            'created_at',
        )
        export_order = fields
        import_id_fields = ('name_key',)
        skip_unchanged = True
        report_skipped = True


class WalkInCustomerProductDiscountResource(resources.ModelResource):
    walk_in_customer = fields.Field(
        column_name='walk_in_customer',
        attribute='walk_in_customer',
        widget=ForeignKeyWidget(WalkInCustomer, field='name_key'),
    )
    product = fields.Field(
        column_name='linked_product_barcode',
        attribute='product',
        widget=LenientForeignKeyWidget(Product, field='barcode'),
    )

    class Meta:
        model = WalkInCustomerProductDiscount
        fields = (
            'id',
            'walk_in_customer',
            'product',
            'product_name',
            'total_manual_discount_php',
            'line_count',
            'last_sale_at',
        )
        export_order = fields
        import_id_fields = ('id',)
        skip_unchanged = True
        report_skipped = True

    def before_import_row(self, row, **kwargs):
        # Back-compat with older ZIPs that used product_barcode for the FK column.
        if not str(row.get('linked_product_barcode') or '').strip():
            row['linked_product_barcode'] = row.get('product_barcode') or None
        _blank_to_none(row, 'linked_product_barcode', 'product_barcode')


class CreditPaymentResource(resources.ModelResource):
    """Imported before transactions so sales can link to settlements."""

    member = fields.Field(
        column_name='member_id',
        attribute='member',
        widget=LenientForeignKeyWidget(Member, field='id'),
    )
    performed_by = fields.Field(
        column_name='performed_by',
        attribute='performed_by',
        widget=LenientForeignKeyWidget(User, field='username'),
    )

    class Meta:
        model = CreditPayment
        fields = (
            'id',
            'settlement_number',
            'member',
            'amount_paid',
            'payment_method',
            'balance_before',
            'balance_after',
            'performed_by',
            'notes',
            'created_at',
        )
        export_order = fields
        import_id_fields = ('settlement_number',)
        skip_unchanged = True
        report_skipped = True

    def before_import_row(self, row, **kwargs):
        _blank_to_none(row, 'member_id', 'performed_by', 'balance_before', 'balance_after')
        if 'notes' in row and row['notes'] is None:
            row['notes'] = ''


class TransactionResource(resources.ModelResource):
    """Full purchase / revenue header rows (sales, VAT, payment method, status)."""

    member = fields.Field(
        column_name='member_id',
        attribute='member',
        widget=LenientForeignKeyWidget(Member, field='id'),
    )
    walk_in_customer = fields.Field(
        column_name='walk_in_customer',
        attribute='walk_in_customer',
        widget=LenientForeignKeyWidget(WalkInCustomer, field='name_key'),
    )
    credit_payment = fields.Field(
        column_name='credit_payment_settlement',
        attribute='credit_payment',
        widget=LenientForeignKeyWidget(CreditPayment, field='settlement_number'),
    )
    processed_by = fields.Field(
        column_name='processed_by',
        attribute='processed_by',
        widget=LenientForeignKeyWidget(User, field='username'),
    )

    class Meta:
        model = Transaction
        fields = (
            'id',
            'transaction_number',
            'member',
            'guest_customer_name',
            'walk_in_customer',
            'subtotal',
            'vatable_sale',
            'vat_amount',
            'total_amount',
            'payment_method',
            'amount_paid',
            'amount_from_balance',
            'status',
            'notes',
            'credit_settled_at',
            'credit_payment',
            'processed_by',
            'created_at',
        )
        export_order = fields
        import_id_fields = ('transaction_number',)
        skip_unchanged = True
        report_skipped = True

    def before_import_row(self, row, **kwargs):
        _blank_to_none(
            row,
            'member_id',
            'walk_in_customer',
            'credit_payment_settlement',
            'processed_by',
            'credit_settled_at',
        )
        if 'guest_customer_name' in row and row['guest_customer_name'] is None:
            row['guest_customer_name'] = ''
        if 'notes' in row and row['notes'] is None:
            row['notes'] = ''


class TransactionItemResource(resources.ModelResource):
    transaction = fields.Field(
        column_name='transaction_number',
        attribute='transaction',
        widget=ForeignKeyWidget(Transaction, field='transaction_number'),
    )
    # Unique column name — do NOT reuse product_barcode (model CharField also exports that).
    product = fields.Field(
        column_name='linked_product_barcode',
        attribute='product',
        widget=LenientForeignKeyWidget(Product, field='barcode'),
    )
    credit_payment = fields.Field(
        column_name='credit_payment_settlement',
        attribute='credit_payment',
        widget=LenientForeignKeyWidget(CreditPayment, field='settlement_number'),
    )

    class Meta:
        model = TransactionItem
        fields = (
            'id',
            'transaction',
            'product',
            'product_name',
            'product_barcode',
            'unit_price',
            'quantity',
            'manual_discount_php',
            'total_price',
            'vat_amount',
            'vatable_sale',
            'credit_settled_at',
            'credit_payment',
            'credit_amount_paid',
            'refunded_at',
            'created_at',
        )
        export_order = fields
        import_id_fields = ('id',)
        skip_unchanged = True
        report_skipped = True

    def before_import_row(self, row, **kwargs):
        # Older ZIPs duplicated product_barcode for the FK; prefer linked_product_barcode.
        if not str(row.get('linked_product_barcode') or '').strip():
            # DictReader keeps the last duplicate header value as product_barcode.
            row['linked_product_barcode'] = row.get('product_barcode') or None
        _blank_to_none(
            row,
            'linked_product_barcode',
            'credit_payment_settlement',
            'credit_settled_at',
            'refunded_at',
        )
        if 'product_name' in row and row['product_name'] is None:
            row['product_name'] = ''
        if 'product_barcode' in row and row['product_barcode'] is None:
            row['product_barcode'] = ''


class RefundReasonResource(resources.ModelResource):
    transaction = fields.Field(
        column_name='transaction_number',
        attribute='transaction',
        widget=ForeignKeyWidget(Transaction, field='transaction_number'),
    )

    class Meta:
        model = RefundReason
        fields = ('id', 'transaction', 'reason_type', 'details', 'created_at')
        export_order = fields
        import_id_fields = ('id',)
        skip_unchanged = True
        report_skipped = True

    def before_import_row(self, row, **kwargs):
        if 'details' in row and row['details'] is None:
            row['details'] = ''


class RefundReturnWindowResource(resources.ModelResource):
    transaction = fields.Field(
        column_name='transaction_number',
        attribute='transaction',
        widget=ForeignKeyWidget(Transaction, field='transaction_number'),
    )
    approved_by = fields.Field(
        column_name='approved_by',
        attribute='approved_by',
        widget=LenientForeignKeyWidget(User, field='username'),
    )

    class Meta:
        model = RefundReturnWindow
        fields = (
            'id',
            'transaction',
            'return_deadline',
            'is_returned',
            'return_confirmed_at',
            'approved_by',
            'approved_at',
        )
        export_order = fields
        import_id_fields = ('id',)
        skip_unchanged = True
        report_skipped = True

    def before_import_row(self, row, **kwargs):
        _blank_to_none(row, 'approved_by', 'return_confirmed_at')


class CreditPaymentLineResource(resources.ModelResource):
    payment = fields.Field(
        column_name='settlement_number',
        attribute='payment',
        widget=ForeignKeyWidget(CreditPayment, field='settlement_number'),
    )
    item = fields.Field(
        column_name='item_id',
        attribute='item',
        widget=LenientForeignKeyWidget(TransactionItem, field='id'),
    )

    class Meta:
        model = CreditPaymentLine
        fields = ('id', 'payment', 'item', 'amount_applied')
        export_order = fields
        import_id_fields = ('id',)
        skip_unchanged = True
        report_skipped = True
