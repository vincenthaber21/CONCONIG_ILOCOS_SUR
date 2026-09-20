from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("transactions", "0018_walk_in_customer"),
    ]

    operations = [
        migrations.AlterField(
            model_name="transaction",
            name="payment_method",
            field=models.CharField(
                choices=[
                    ("debit", "Debit (Member Account)"),
                    ("credit", "Credit"),
                    ("cash", "Cash"),
                ],
                max_length=20,
            ),
        ),
    ]
