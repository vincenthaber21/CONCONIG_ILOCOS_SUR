from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("savings", "0017_savingswalkin_address_parts"),
    ]

    operations = [
        migrations.AddField(
            model_name="savingsbeneficiary",
            name="street",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name="savingsbeneficiary",
            name="barangay",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name="savingsbeneficiary",
            name="municipality",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name="savingsbeneficiary",
            name="province",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name="savingsbeneficiary",
            name="address",
            field=models.CharField(blank=True, max_length=500),
        ),
    ]
