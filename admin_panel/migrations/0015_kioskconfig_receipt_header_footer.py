from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admin_panel", "0014_kioskconfig_receipt_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="kioskconfig",
            name="receipt_header_store_name",
            field=models.CharField(
                default="SHOP NAME",
                help_text="Store / business name printed at the top of every receipt.",
                max_length=200,
            ),
        ),
        migrations.AddField(
            model_name="kioskconfig",
            name="receipt_header_address",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Address line printed under the store name on receipts.",
                max_length=300,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="kioskconfig",
            name="receipt_header_phone",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Phone / contact number printed on the receipt header.",
                max_length=50,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="kioskconfig",
            name="receipt_footer_customer_tagline",
            field=models.CharField(
                default="We appreciate your business.",
                help_text="Tagline printed at the bottom of the customer copy.",
                max_length=200,
            ),
        ),
        migrations.AddField(
            model_name="kioskconfig",
            name="receipt_footer_merchant_note",
            field=models.CharField(
                default="Merchant copy \u2014 retain for records.",
                help_text="Note printed at the bottom of the merchant copy.",
                max_length=200,
            ),
        ),
    ]
