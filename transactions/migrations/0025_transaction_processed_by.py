from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0024_transactionitem_refunded_at_partial_status'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='transaction',
            name='processed_by',
            field=models.ForeignKey(
                blank=True,
                help_text='Staff or cashier who processed this transaction (set on admin-assisted sales).',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='processed_transactions',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
