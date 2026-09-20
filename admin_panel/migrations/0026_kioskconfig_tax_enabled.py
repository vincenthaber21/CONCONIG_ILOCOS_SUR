from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('admin_panel', '0025_kioskconfig_receipt_header_store_description'),
    ]

    operations = [
        migrations.AddField(
            model_name='kioskconfig',
            name='tax_enabled',
            field=models.BooleanField(
                default=True,
                help_text=(
                    'Enable or disable tax (VAT) calculation system-wide. '
                    'When disabled, no tax is computed or displayed on the kiosk, '
                    'receipts, or stored on transactions.'
                ),
            ),
        ),
    ]
