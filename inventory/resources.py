"""Import/export resources for inventory models (Django admin)."""

from import_export import fields, resources
from import_export.widgets import ForeignKeyWidget

from helper.import_export_widgets import LenientForeignKeyWidget

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


class CategoryResource(resources.ModelResource):
    class Meta:
        model = Category
        fields = ('id', 'name', 'description', 'is_active')
        export_order = fields
        import_id_fields = ('name',)
        skip_unchanged = True
        report_skipped = True


class TaxRateResource(resources.ModelResource):
    class Meta:
        model = TaxRate
        fields = ('id', 'name', 'rate', 'tax_type', 'is_active', 'description')
        export_order = fields
        import_id_fields = ('name',)
        skip_unchanged = True
        report_skipped = True


class ProductDiscountGroupResource(resources.ModelResource):
    class Meta:
        model = ProductDiscountGroup
        fields = ('id', 'code', 'name', 'sort_order')
        export_order = fields
        import_id_fields = ('code',)
        skip_unchanged = True
        report_skipped = True


class ProductResource(resources.ModelResource):
    """
    Bulk import/export products by barcode.
    Leave id blank for new rows; matching barcode updates an existing product.
    category = category name, tax_rate = tax rate name, discount_group = group code.
    """

    category = fields.Field(
        column_name='category',
        attribute='category',
        widget=ForeignKeyWidget(Category, field='name'),
    )
    tax_rate = fields.Field(
        column_name='tax_rate',
        attribute='tax_rate',
        widget=ForeignKeyWidget(TaxRate, field='name'),
    )
    discount_group = fields.Field(
        column_name='discount_group',
        attribute='discount_group',
        widget=ForeignKeyWidget(ProductDiscountGroup, field='code'),
    )

    class Meta:
        model = Product
        fields = (
            'id',
            'name',
            'description',
            'barcode',
            'category',
            'price',
            'cost',
            'tax_rate',
            'discount_group',
            'stock_quantity',
            'low_stock_threshold',
            'image',
            'barcode_image',
            'is_active',
        )
        export_order = fields
        import_id_fields = ('barcode',)
        skip_unchanged = True
        report_skipped = True

    def before_import_row(self, row, **kwargs):
        for key in ('category', 'tax_rate', 'discount_group'):
            if key in row and (row[key] is None or str(row[key]).strip() == ''):
                row[key] = None
        # TextField(blank=True) is NOT null=True — empty must be "" not None.
        if 'description' in row and row['description'] is None:
            row['description'] = ''
        for key in ('image', 'barcode_image'):
            if key in row and (row[key] is None or str(row[key]).strip() == ''):
                row[key] = ''


class ProductSaleUnitResource(resources.ModelResource):
    product = fields.Field(
        column_name='product_barcode',
        attribute='product',
        widget=ForeignKeyWidget(Product, field='barcode'),
    )

    class Meta:
        model = ProductSaleUnit
        fields = (
            'id',
            'product',
            'sale_mode',
            'unit_label',
            'barcode',
            'price',
            'units_per_package',
            'is_active',
        )
        export_order = fields
        import_id_fields = ('barcode',)
        skip_unchanged = True
        report_skipped = True


class ProductDiscountResource(resources.ModelResource):
    product = fields.Field(
        column_name='product_barcode',
        attribute='product',
        widget=ForeignKeyWidget(Product, field='barcode'),
    )

    class Meta:
        model = ProductDiscount
        fields = (
            'id',
            'product',
            'name',
            'is_active',
            'valid_from',
            'valid_to',
            'discount_percent',
            'discount_amount',
        )
        export_order = fields
        import_id_fields = ('id',)
        skip_unchanged = True
        report_skipped = True


class ProductStockBatchResource(resources.ModelResource):
    product = fields.Field(
        column_name='product_barcode',
        attribute='product',
        widget=ForeignKeyWidget(Product, field='barcode'),
    )

    class Meta:
        model = ProductStockBatch
        fields = (
            'id',
            'product',
            'tier',
            'quantity',
            'unit_price',
            'cost',
            'notes',
        )
        export_order = fields
        import_id_fields = ('id',)
        skip_unchanged = True
        report_skipped = True


class GiveawayProductResource(resources.ModelResource):
    product = fields.Field(
        column_name='product_barcode',
        attribute='product',
        widget=ForeignKeyWidget(Product, field='barcode'),
    )

    class Meta:
        model = GiveawayProduct
        fields = ('id', 'product', 'is_active', 'notes')
        export_order = fields
        import_id_fields = ('product',)
        skip_unchanged = True
        report_skipped = True

    def before_import_row(self, row, **kwargs):
        if 'notes' in row and row['notes'] is None:
            row['notes'] = ''
        # Never apply exported giveaway PK onto auto-created rows.
        row.pop('id', None)

    def get_or_init_instance(self, instance_loader, row):
        """
        Prefer lookup by product barcode. Auto-created giveaway rows often have
        different primary keys than the export file.
        """
        barcode = str(row.get('product_barcode') or '').strip()
        if barcode:
            product = Product.objects.filter(barcode=barcode).first()
            if product:
                existing = GiveawayProduct.objects.filter(product=product).first()
                if existing:
                    return existing, False
                instance = GiveawayProduct(product=product)
                return instance, True
        return super().get_or_init_instance(instance_loader, row)


class StockTransactionResource(resources.ModelResource):
    """Stock movement history (importable for full restore)."""

    product = fields.Field(
        column_name='product_barcode',
        attribute='product',
        widget=LenientForeignKeyWidget(Product, field='barcode'),
    )

    class Meta:
        model = StockTransaction
        fields = (
            'id',
            'product',
            'transaction_type',
            'quantity',
            'stock_before',
            'stock_after',
            'notes',
            'created_at',
        )
        export_order = fields
        import_id_fields = ('id',)
        skip_unchanged = True
        report_skipped = True

    def before_import_row(self, row, **kwargs):
        if 'notes' in row and row['notes'] is None:
            row['notes'] = ''
        if not row.get('product_barcode'):
            row['product_barcode'] = None

    def skip_row(self, instance, original, row, import_validation_errors=None):
        # product is required — skip if barcode did not resolve
        if getattr(instance, 'product_id', None) is None:
            return True
        return super().skip_row(
            instance, original, row, import_validation_errors=import_validation_errors
        )


class ProductStockHistoryResource(resources.ModelResource):
    product = fields.Field(
        column_name='product_barcode',
        attribute='product',
        widget=LenientForeignKeyWidget(Product, field='barcode'),
    )

    class Meta:
        model = ProductStockHistory
        fields = (
            'id',
            'product',
            'change_type',
            'total_before',
            'total_after',
            'unit_price_before',
            'unit_price',
            'cost_before',
            'cost',
            'quantity_sold',
            'note',
            'created_at',
        )
        export_order = fields
        import_id_fields = ('id',)
        skip_unchanged = True
        report_skipped = True

    def before_import_row(self, row, **kwargs):
        if 'note' in row and row['note'] is None:
            row['note'] = ''
        if not row.get('product_barcode'):
            row['product_barcode'] = None

    def skip_row(self, instance, original, row, import_validation_errors=None):
        if getattr(instance, 'product_id', None) is None:
            return True
        return super().skip_row(
            instance, original, row, import_validation_errors=import_validation_errors
        )
