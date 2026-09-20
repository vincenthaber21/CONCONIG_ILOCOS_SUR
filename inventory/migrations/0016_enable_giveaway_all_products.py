from django.db import migrations, models


def enable_giveaway_for_all_active_products(apps, schema_editor):
    Product = apps.get_model('inventory', 'Product')
    GiveawayProduct = apps.get_model('inventory', 'GiveawayProduct')
    for product_id in Product.objects.filter(is_active=True).values_list('id', flat=True):
        GiveawayProduct.objects.update_or_create(
            product_id=product_id,
            defaults={'is_active': True},
        )


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0015_giveawayproduct'),
    ]

    operations = [
        migrations.RunPython(
            enable_giveaway_for_all_active_products,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name='giveawayproduct',
            name='is_active',
            field=models.BooleanField(
                default=True,
                help_text='Kept in sync for active products; all active inventory items are giveaway-eligible.',
            ),
        ),
    ]
