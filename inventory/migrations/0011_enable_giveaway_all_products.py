from django.db import migrations, models


def enable_giveaway_on_all_products(apps, schema_editor):
    Product = apps.get_model('inventory', 'Product')
    Product.objects.filter(is_giveaway=False).update(is_giveaway=True)


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0010_product_is_giveaway'),
    ]

    operations = [
        migrations.RunPython(enable_giveaway_on_all_products, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='product',
            name='is_giveaway',
            field=models.BooleanField(
                default=True,
                help_text='Staff distribution item: hidden from member kiosk/mobile; stock deducted via Record Giveaway.',
            ),
        ),
    ]
