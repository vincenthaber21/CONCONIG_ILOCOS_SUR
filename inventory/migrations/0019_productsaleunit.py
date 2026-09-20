from django.db import migrations, models
import django.db.models.deletion


def seed_retail_sale_units(apps, schema_editor):
    Product = apps.get_model('inventory', 'Product')
    ProductSaleUnit = apps.get_model('inventory', 'ProductSaleUnit')

    units = []
    for product in Product.objects.iterator():
        units.append(
            ProductSaleUnit(
                product_id=product.pk,
                sale_mode='retail',
                unit_label='Piece',
                barcode=product.barcode,
                price=product.price,
                units_per_package=1,
                is_active=product.is_active,
            )
        )
    if units:
        ProductSaleUnit.objects.bulk_create(units, ignore_conflicts=True)


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0018_productstockbatch'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProductSaleUnit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                (
                    'sale_mode',
                    models.CharField(
                        choices=[('retail', 'By piece (retail)'), ('wholesale', 'Wholesale (box / bulk)')],
                        default='retail',
                        help_text='Retail = sold per piece. Wholesale = sold per box, pack, or case.',
                        max_length=20,
                    ),
                ),
                (
                    'unit_label',
                    models.CharField(
                        help_text='Shown on receipts and admin (e.g. "Piece", "Box of 12").',
                        max_length=50,
                    ),
                ),
                (
                    'barcode',
                    models.CharField(
                        help_text='Unique barcode for this sale unit (scan at checkout).',
                        max_length=100,
                        unique=True,
                    ),
                ),
                (
                    'price',
                    models.DecimalField(
                        decimal_places=2,
                        help_text='Selling price for one of this sale unit (one box, one piece, etc.).',
                        max_digits=10,
                    ),
                ),
                (
                    'units_per_package',
                    models.PositiveIntegerField(
                        default=1,
                        help_text=(
                            'Base pieces consumed from inventory per 1 of this sale unit. '
                            'Use 1 for per-piece; e.g. 12 when one box contains 12 pencils.'
                        ),
                    ),
                ),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                (
                    'product',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='sale_units',
                        to='inventory.product',
                    ),
                ),
            ],
            options={
                'verbose_name': 'Product sale unit',
                'verbose_name_plural': 'Product sale units',
                'ordering': ['sale_mode', 'unit_label'],
            },
        ),
        migrations.AddConstraint(
            model_name='productsaleunit',
            constraint=models.UniqueConstraint(
                fields=('product', 'barcode'),
                name='unique_product_sale_unit_barcode',
            ),
        ),
        migrations.RunPython(seed_retail_sale_units, migrations.RunPython.noop),
    ]
