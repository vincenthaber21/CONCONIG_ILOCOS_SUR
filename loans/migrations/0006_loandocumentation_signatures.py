# Generated manually for signature image fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("loans", "0005_creditinvestigation_score_decimal"),
    ]

    operations = [
        migrations.AddField(
            model_name="loandocumentation",
            name="borrower_signature",
            field=models.ImageField(
                blank=True, null=True, upload_to="loan_signatures/%Y/%m/"
            ),
        ),
        migrations.AddField(
            model_name="loandocumentation",
            name="personnel_signature",
            field=models.ImageField(
                blank=True, null=True, upload_to="loan_signatures/%Y/%m/"
            ),
        ),
    ]
