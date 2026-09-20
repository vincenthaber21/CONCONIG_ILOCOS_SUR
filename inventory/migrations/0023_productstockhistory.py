from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('inventory', '0022_alter_productstockbatch_sell_buy_price_labels'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProductStockHistory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('change_type', models.CharField(
                    choices=[
                        ('created', 'Product created'),
                        ('edit', 'Manual edit'),
                        ('restock', 'Restock'),
                        ('sale', 'Sale'),
                        ('promotion', 'New → Old promotion'),
                        ('adjustment', 'Adjustment'),
                        ('refund', 'Refund restock'),
                    ],
                    default='edit',
                    max_length=20,
                )),
                ('old_stock_before', models.IntegerField(default=0)),
                ('old_stock_after', models.IntegerField(default=0)),
                ('new_stock_before', models.IntegerField(default=0)),
                ('new_stock_after', models.IntegerField(default=0)),
                ('total_before', models.IntegerField(default=0)),
                ('total_after', models.IntegerField(default=0)),
                ('quantity_sold', models.PositiveIntegerField(default=0, help_text='Units sold in this event (only for sale changes).')),
                ('unit_price', models.DecimalField(blank=True, decimal_places=2, help_text='Snapshot of the selling price at the time of the change.', max_digits=10, null=True, verbose_name='Selling price')),
                ('cost', models.DecimalField(blank=True, decimal_places=2, help_text='Snapshot of the buying price at the time of the change.', max_digits=10, null=True, verbose_name='Buying price')),
                ('note', models.CharField(blank=True, max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('changed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('product', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='stock_history', to='inventory.product')),
            ],
            options={
                'verbose_name': 'Product stock history',
                'verbose_name_plural': 'Product stock history',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='productstockhistory',
            index=models.Index(fields=['product', '-created_at'], name='inv_stockhist_prod_created_idx'),
        ),
    ]
