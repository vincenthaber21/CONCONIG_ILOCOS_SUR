from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("loans", "0008_loansettings_min_membership_months"),
    ]

    operations = [
        migrations.AddField(
            model_name="committeereview",
            name="staff_signature",
            field=models.ImageField(
                blank=True,
                null=True,
                upload_to="loan_signatures/staff_decisions/%Y/%m/",
            ),
        ),
    ]
