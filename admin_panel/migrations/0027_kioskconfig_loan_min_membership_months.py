from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admin_panel", "0026_kioskconfig_tax_enabled"),
    ]

    operations = [
        migrations.AddField(
            model_name="kioskconfig",
            name="loan_min_membership_months",
            field=models.PositiveIntegerField(
                default=3,
                help_text=(
                    "Minimum months a member must be registered before they can request a loan. "
                    "Example: 3 means a member who joined only 1 week ago cannot apply yet. "
                    "Set to 0 to allow loan requests immediately."
                ),
            ),
        ),
    ]
