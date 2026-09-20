from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("admin_panel", "0027_kioskconfig_loan_min_membership_months"),
        ("loans", "0008_loansettings_min_membership_months"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="kioskconfig",
            name="loan_min_membership_months",
        ),
    ]
