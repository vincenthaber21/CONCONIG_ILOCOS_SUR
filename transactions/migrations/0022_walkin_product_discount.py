import decimal

import django.db.models.deletion
from django.db import migrations, models


def backfill_walk_in_discounts(apps, schema_editor):
    from collections import defaultdict

    WalkInCustomer = apps.get_model('transactions', 'WalkInCustomer')
    TransactionItem = apps.get_model('transactions', 'TransactionItem')
    WalkInCustomerProductDiscount = apps.get_model('transactions', 'WalkInCustomerProductDiscount')

    for customer in WalkInCustomer.objects.iterator():
        items = TransactionItem.objects.filter(
            transaction__walk_in_customer_id=customer.id,
            transaction__status='completed',
            manual_discount_php__gt=0,
        ).select_related('transaction')

        buckets = defaultdict(
            lambda: {
                'product_id': None,
                'product_name': '',
                'total': decimal.Decimal('0.00'),
                'line_count': 0,
                'last_sale_at': None,
            }
        )
        for item in items:
            name = (item.product_name or '').strip() or '—'
            key = name.casefold()
            bucket = buckets[key]
            bucket['product_name'] = name
            if item.product_id and not bucket['product_id']:
                bucket['product_id'] = item.product_id
            disc = decimal.Decimal(str(item.manual_discount_php or 0)).quantize(decimal.Decimal('0.01'))
            bucket['total'] += disc
            bucket['line_count'] += 1
            sale_at = item.transaction.created_at
            if bucket['last_sale_at'] is None or sale_at > bucket['last_sale_at']:
                bucket['last_sale_at'] = sale_at

        WalkInCustomerProductDiscount.objects.filter(walk_in_customer_id=customer.id).delete()
        grand_total = decimal.Decimal('0.00')
        for bucket in buckets.values():
            total = bucket['total'].quantize(decimal.Decimal('0.01'))
            grand_total += total
            WalkInCustomerProductDiscount.objects.create(
                walk_in_customer_id=customer.id,
                product_id=bucket['product_id'],
                product_name=bucket['product_name'],
                total_manual_discount_php=total,
                line_count=bucket['line_count'],
                last_sale_at=bucket['last_sale_at'],
            )
        customer.total_manual_discount_php = grand_total.quantize(decimal.Decimal('0.01'))
        customer.save(update_fields=['total_manual_discount_php'])


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0009_alter_product_discount_group_and_more'),
        ('transactions', '0021_transactionitem_credit_settlement'),
    ]

    operations = [
        migrations.AddField(
            model_name='walkincustomer',
            name='total_manual_discount_php',
            field=models.DecimalField(
                decimal_places=2,
                default=decimal.Decimal('0.00'),
                help_text='Total manual Discount ₱ from completed walk-in sales (synced from line items).',
                max_digits=12,
            ),
        ),
        migrations.CreateModel(
            name='WalkInCustomerProductDiscount',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('product_name', models.CharField(max_length=200)),
                (
                    'total_manual_discount_php',
                    models.DecimalField(
                        decimal_places=2,
                        default=decimal.Decimal('0.00'),
                        help_text='Sum of manual Discount ₱ for this product on completed sales.',
                        max_digits=12,
                    ),
                ),
                (
                    'line_count',
                    models.PositiveIntegerField(
                        default=0,
                        help_text='Number of receipt lines with a manual discount for this product.',
                    ),
                ),
                (
                    'last_sale_at',
                    models.DateTimeField(
                        blank=True,
                        help_text='Most recent completed sale date for this product discount row.',
                        null=True,
                    ),
                ),
                ('updated_at', models.DateTimeField(auto_now=True)),
                (
                    'product',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='walk_in_product_discounts',
                        to='inventory.product',
                    ),
                ),
                (
                    'walk_in_customer',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='product_discounts',
                        to='transactions.walkincustomer',
                    ),
                ),
            ],
            options={
                'verbose_name': 'Walk-in product discount',
                'verbose_name_plural': 'Walk-in product discounts',
                'ordering': ['-total_manual_discount_php', 'product_name'],
            },
        ),
        migrations.AddConstraint(
            model_name='walkincustomerproductdiscount',
            constraint=models.UniqueConstraint(
                fields=('walk_in_customer', 'product_name'),
                name='uniq_walkin_product_discount_name',
            ),
        ),
        migrations.RunPython(backfill_walk_in_discounts, migrations.RunPython.noop),
    ]
