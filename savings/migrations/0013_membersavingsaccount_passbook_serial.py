from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("savings", "0012_savingsproduct_min_max_amount"),
    ]

    operations = [
        migrations.AddField(
            model_name="membersavingsaccount",
            name="passbook_serial",
            field=models.CharField(
                blank=True,
                help_text="Printed serial number on the member's savings passbook.",
                max_length=40,
                null=True,
                unique=True,
            ),
        ),
    ]
