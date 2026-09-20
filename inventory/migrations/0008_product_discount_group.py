# Generated manually for editable segment discount group names.

import django.db.models.deletion
from django.db import migrations, models


def seed_product_discount_groups(apps, schema_editor):
    ProductDiscountGroup = apps.get_model('inventory', 'ProductDiscountGroup')
    seed = [
        ('dairy_1l_500ml', 'Dairy — 1L or 500ml only', 0),
        ('dairy_250ml', 'Dairy — 250ml only', 1),
        ('pastillas', 'Pastillas', 2),
        ('espasol_polvoron', 'Espasol & Polvoron', 3),
    ]
    for code, name, sort_order in seed:
        ProductDiscountGroup.objects.update_or_create(
            code=code,
            defaults={'name': name, 'sort_order': sort_order},
        )


def copy_product_char_discount_group_to_fk(apps, schema_editor):
    Product = apps.get_model('inventory', 'Product')
    ProductDiscountGroup = apps.get_model('inventory', 'ProductDiscountGroup')
    lookup = {g.code: g.pk for g in ProductDiscountGroup.objects.all()}
    for p in Product.objects.iterator():
        code = (getattr(p, 'discount_group', None) or '').strip()
        if not code:
            p.product_discount_group_id = None
        else:
            p.product_discount_group_id = lookup.get(code)
        p.save(update_fields=['product_discount_group_id'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0007_segment_discount_groups'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProductDiscountGroup',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                (
                    'code',
                    models.CharField(
                        db_index=True,
                        help_text='Stable key used by checkout and APIs (do not change without updating products).',
                        max_length=32,
                        unique=True,
                    ),
                ),
                ('name', models.CharField(max_length=120)),
                ('sort_order', models.PositiveSmallIntegerField(default=0)),
            ],
            options={
                'verbose_name': 'Product discount group',
                'verbose_name_plural': 'Product discount groups',
                'ordering': ['sort_order', 'code'],
            },
        ),
        migrations.RunPython(seed_product_discount_groups, noop_reverse),
        migrations.AddField(
            model_name='product',
            name='product_discount_group',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='products',
                to='inventory.productdiscountgroup',
            ),
        ),
        migrations.RunPython(copy_product_char_discount_group_to_fk, noop_reverse),
        migrations.RemoveField(
            model_name='product',
            name='discount_group',
        ),
        migrations.RenameField(
            model_name='product',
            old_name='product_discount_group',
            new_name='discount_group',
        ),
    ]
