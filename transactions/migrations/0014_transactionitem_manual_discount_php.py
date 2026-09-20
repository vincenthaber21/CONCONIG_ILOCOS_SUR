# Generated manually for kiosk cart line discounts (Discount ₱).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("transactions", "0013_refund_return_window"),
    ]

    operations = [
        migrations.AddField(
            model_name="transactionitem",
            name="manual_discount_php",
            field=models.DecimalField(
                decimal_places=2,
                default=0.0,
                help_text="Additional peso discount for this line from the kiosk cart (Discount ₱).",
                max_digits=10,
            ),
        ),
    ]
