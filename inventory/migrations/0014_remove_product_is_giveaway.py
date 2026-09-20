from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0013_giveaway_default_true_all_products'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='product',
            name='is_giveaway',
        ),
    ]
