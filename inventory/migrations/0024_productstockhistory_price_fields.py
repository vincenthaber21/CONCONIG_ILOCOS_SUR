from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0023_productstockhistory'),
    ]

    operations = [
        migrations.AddField(
            model_name='productstockhistory',
            name='unit_price_before',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Product selling price before this change.',
                max_digits=10,
                null=True,
                verbose_name='Selling price before',
            ),
        ),
        migrations.AddField(
            model_name='productstockhistory',
            name='cost_before',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Product buying price before this change.',
                max_digits=10,
                null=True,
                verbose_name='Buying price before',
            ),
        ),
        migrations.AddField(
            model_name='productstockhistory',
            name='old_stock_price_before',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Old-stock tier selling price before.',
                max_digits=10,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='productstockhistory',
            name='old_stock_price_after',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Old-stock tier selling price after.',
                max_digits=10,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='productstockhistory',
            name='new_stock_price_before',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='New-stock tier selling price before.',
                max_digits=10,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='productstockhistory',
            name='new_stock_price_after',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='New-stock tier selling price after.',
                max_digits=10,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name='productstockhistory',
            name='change_type',
            field=models.CharField(
                choices=[
                    ('created', 'Product created'),
                    ('edit', 'Manual edit'),
                    ('restock', 'Restock'),
                    ('sale', 'Sale'),
                    ('promotion', 'New → Old promotion'),
                    ('adjustment', 'Adjustment'),
                    ('refund', 'Refund restock'),
                    ('price', 'Price change'),
                ],
                default='edit',
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name='productstockhistory',
            name='unit_price',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Product selling price after this change.',
                max_digits=10,
                null=True,
                verbose_name='Selling price after',
            ),
        ),
        migrations.AlterField(
            model_name='productstockhistory',
            name='cost',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Product buying price after this change.',
                max_digits=10,
                null=True,
                verbose_name='Buying price after',
            ),
        ),
    ]
