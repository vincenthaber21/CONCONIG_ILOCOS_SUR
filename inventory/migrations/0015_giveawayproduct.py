from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0014_remove_product_is_giveaway'),
    ]

    operations = [
        migrations.CreateModel(
            name='GiveawayProduct',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('is_active', models.BooleanField(default=True, help_text='Inactive giveaway products are hidden from Record Giveaway.')),
                ('notes', models.TextField(blank=True, help_text='Optional internal note (e.g. distribution program name).')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('product', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='giveaway', to='inventory.product')),
            ],
            options={
                'verbose_name': 'Giveaway product',
                'verbose_name_plural': 'Giveaway products',
                'ordering': ['product__name'],
            },
        ),
    ]
