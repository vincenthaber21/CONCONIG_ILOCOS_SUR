from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admin_panel", "0022_storeprofile_show_store_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="kioskconfig",
            name="member_max_credit",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0"),
                help_text=(
                    "Maximum total outstanding credit (utang) allowed per member. "
                    "Set to 0 for no limit. Credit purchases are blocked when "
                    "outstanding credit plus the new sale would exceed this amount."
                ),
                max_digits=12,
            ),
        ),
    ]
