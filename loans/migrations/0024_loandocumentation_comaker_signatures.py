from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("loans", "0023_loandocumentation_spouse_prepared_by_signatures"),
    ]

    operations = [
        migrations.AddField(
            model_name="loandocumentation",
            name="comaker1_name",
            field=models.CharField(
                blank=True,
                help_text="Name of the first co-maker.",
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="loandocumentation",
            name="comaker1_signature",
            field=models.ImageField(
                blank=True, null=True, upload_to="loan_signatures/%Y/%m/"
            ),
        ),
        migrations.AddField(
            model_name="loandocumentation",
            name="comaker2_name",
            field=models.CharField(
                blank=True,
                help_text="Name of the second co-maker.",
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="loandocumentation",
            name="comaker2_signature",
            field=models.ImageField(
                blank=True, null=True, upload_to="loan_signatures/%Y/%m/"
            ),
        ),
        migrations.AddField(
            model_name="loandocumentation",
            name="signed_by_comaker1_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="loandocumentation",
            name="signed_by_comaker2_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
