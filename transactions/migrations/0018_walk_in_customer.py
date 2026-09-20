import django.utils.timezone
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0017_transaction_guest_customer_name'),
    ]

    operations = [
        migrations.CreateModel(
            name='WalkInCustomer',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name_key', models.CharField(help_text='Normalized name for deduplication (case-insensitive).', max_length=200, unique=True)),
                ('display_name', models.CharField(max_length=200)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('last_seen_at', models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={
                'verbose_name': 'Walk-in customer',
                'verbose_name_plural': 'Walk-in customers',
                'ordering': ['display_name'],
            },
        ),
        migrations.AddField(
            model_name='transaction',
            name='walk_in_customer',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='transactions',
                to='transactions.walkincustomer',
            ),
        ),
    ]
