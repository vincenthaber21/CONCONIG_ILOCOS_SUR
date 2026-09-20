from django.db import migrations, models


def disable_giveaway_on_all_products(apps, schema_editor):
    Product = apps.get_model('inventory', 'Product')
    Product.objects.filter(is_giveaway=True).update(is_giveaway=False)


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0011_enable_giveaway_all_products'),
    ]

    operations = [
        migrations.RunPython(disable_giveaway_on_all_products, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='product',
            name='is_giveaway',
            field=models.BooleanField(
                default=False,
                help_text='Staff distribution item: hidden from member kiosk/mobile; stock deducted via Record Giveaway.',
            ),
        ),
    ]
