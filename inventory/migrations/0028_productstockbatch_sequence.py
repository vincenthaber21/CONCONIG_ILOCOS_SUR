from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0027_product_project_categories_to_category'),
    ]

    operations = [
        migrations.AddField(
            model_name='productstockbatch',
            name='sequence',
            field=models.PositiveIntegerField(
                default=0,
                help_text='Order within this tier. Lower numbers sell first. Extra new-stock rows use 1, 2, 3…',
            ),
        ),
        migrations.RemoveConstraint(
            model_name='productstockbatch',
            name='unique_product_stock_tier',
        ),
        migrations.AddConstraint(
            model_name='productstockbatch',
            constraint=models.UniqueConstraint(
                fields=('product', 'tier', 'sequence'),
                name='unique_product_stock_tier_sequence',
            ),
        ),
    ]
