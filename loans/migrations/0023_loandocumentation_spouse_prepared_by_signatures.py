from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("loans", "0022_loansettings_min_membership_enabled"),
    ]

    operations = [
        migrations.AddField(
            model_name="loandocumentation",
            name="spouse_signer_name",
            field=models.CharField(
                blank=True,
                help_text="Name of the spouse, child, or sibling who co-signs the contract.",
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="loandocumentation",
            name="spouse_signature",
            field=models.ImageField(
                blank=True, null=True, upload_to="loan_signatures/%Y/%m/"
            ),
        ),
        migrations.AddField(
            model_name="loandocumentation",
            name="prepared_by_name",
            field=models.CharField(
                blank=True,
                help_text="Name of the staff member who prepared the loan documents.",
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="loandocumentation",
            name="prepared_by_signature",
            field=models.ImageField(
                blank=True, null=True, upload_to="loan_signatures/%Y/%m/"
            ),
        ),
        migrations.AddField(
            model_name="loandocumentation",
            name="signed_by_spouse_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="loandocumentation",
            name="prepared_by_signed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
