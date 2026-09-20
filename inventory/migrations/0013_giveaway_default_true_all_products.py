from django.db import migrations, models


def enable_giveaway_on_all_products(apps, schema_editor):
    Product = apps.get_model('inventory', 'Product')
    Product.objects.filter(is_giveaway=False).update(is_giveaway=True)


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0012_giveaway_default_false'),
    ]

    operations = [
        migrations.RunPython(enable_giveaway_on_all_products, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='product',
            name='is_giveaway',
            field=models.BooleanField(
                default=True,
                help_text='Eligible for Record Giveaway. FREE is shown only while stock is on hand; checkout uses list price.',
            ),
        ),
    ]
