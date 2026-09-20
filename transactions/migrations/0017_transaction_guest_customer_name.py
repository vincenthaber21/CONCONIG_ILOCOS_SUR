from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0016_transaction_number_auto_blank'),
    ]

    operations = [
        migrations.AddField(
            model_name='transaction',
            name='guest_customer_name',
            field=models.CharField(
                blank=True,
                help_text='Walk-in customer name when no member is linked to the transaction.',
                max_length=200,
            ),
        ),
    ]
