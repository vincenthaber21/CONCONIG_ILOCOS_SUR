from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("transactions", "0007_delete_refundrequest"),
    ]

    operations = [
        migrations.AlterField(
            model_name="transaction",
            name="status",
            field=models.CharField(
                max_length=20,
                choices=[
                    ("pending", "Pending"),
                    ("completed", "Completed"),
                    ("cancelled", "Cancelled"),
                    ("refunded", "Refunded"),
                ],
                default="pending",
            ),
        ),
    ]
