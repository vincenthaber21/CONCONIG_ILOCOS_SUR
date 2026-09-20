from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admin_panel", "0024_printersettings_paper_size_57mm"),
    ]

    operations = [
        migrations.AddField(
            model_name="kioskconfig",
            name="receipt_header_store_description",
            field=models.TextField(
                blank=True,
                help_text=(
                    "Short description of the store printed under the store name on receipts "
                    "(e.g. cooperative type, services offered, or branch note)."
                ),
            ),
        ),
    ]
