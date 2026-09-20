from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0009_alter_product_discount_group_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='is_giveaway',
            field=models.BooleanField(
                default=False,
                help_text='When enabled, kiosk and mobile checkout charge ₱0 for this product (stock still applies).',
            ),
        ),
    ]
