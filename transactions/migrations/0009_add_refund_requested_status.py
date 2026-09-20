from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("transactions", "0008_add_refunded_status"),
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
                    ("refund_requested", "Refund Requested"),
                    ("refunded", "Refunded"),
                ],
                default="pending",
            ),
        ),
    ]
