from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("savings", "0015_savings_beneficiary"),
    ]

    operations = [
        migrations.AlterField(
            model_name="savingswalkin",
            name="address",
            field=models.CharField(
                blank=True,
                help_text="Home address of this walk-in savings customer.",
                max_length=255,
            ),
        ),
    ]
