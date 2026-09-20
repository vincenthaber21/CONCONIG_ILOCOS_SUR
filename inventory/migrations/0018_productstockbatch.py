from django.db import migrations, models
import django.db.models.deletion


def seed_old_stock_batches(apps, schema_editor):
    Product = apps.get_model('inventory', 'Product')
    ProductStockBatch = apps.get_model('inventory', 'ProductStockBatch')

    batches = []
    for product in Product.objects.filter(stock_quantity__gt=0).iterator():
        batches.append(
            ProductStockBatch(
                product_id=product.pk,
                tier='old',
                quantity=product.stock_quantity,
                unit_price=product.price,
                cost=product.cost,
                notes='Migrated from existing on-hand stock.',
            )
        )
    if batches:
        ProductStockBatch.objects.bulk_create(batches, ignore_conflicts=True)


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0017_taxrate_product_tax_rate'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProductStockBatch',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tier', models.CharField(
                    choices=[('old', 'Old stock'), ('new', 'New stock')],
                    help_text='Old stock = remaining units at the previous price. New stock = units received at the current price.',
                    max_length=10,
                )),
                ('quantity', models.PositiveIntegerField(default=0, help_text='Units on hand in this tier.')),
                ('unit_price', models.DecimalField(decimal_places=2, help_text='Selling price per unit for this stock tier.', max_digits=10)),
                ('cost', models.DecimalField(decimal_places=2, default=0.0, help_text='Optional cost per unit for this stock tier.', max_digits=10)),
                ('notes', models.TextField(blank=True, help_text='Optional note (e.g. date received, supplier batch).')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('product', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='stock_batches', to='inventory.product')),
            ],
            options={
                'verbose_name': 'Product stock batch',
                'verbose_name_plural': 'Product stock batches',
                'ordering': ['tier', '-updated_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='productstockbatch',
            constraint=models.UniqueConstraint(fields=('product', 'tier'), name='unique_product_stock_tier'),
        ),
        migrations.RunPython(seed_old_stock_batches, migrations.RunPython.noop),
    ]
