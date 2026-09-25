from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("savings", "0016_savingswalkin_address_help"),
    ]

    operations = [
        migrations.AddField(
            model_name="savingswalkin",
            name="street",
            field=models.CharField(
                blank=True,
                help_text="House number and street.",
                max_length=150,
            ),
        ),
        migrations.AddField(
            model_name="savingswalkin",
            name="barangay",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name="savingswalkin",
            name="municipality",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name="savingswalkin",
            name="province",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AlterField(
            model_name="savingswalkin",
            name="address",
            field=models.CharField(
                blank=True,
                help_text="Formatted home address: street, barangay, municipality, province.",
                max_length=500,
            ),
        ),
    ]
