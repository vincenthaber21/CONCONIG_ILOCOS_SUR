from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("members", "0013_balancetransaction_txn_number_cardbalancerefill"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="cardbalancerefill",
            options={
                "ordering": ["-created_at"],
                "verbose_name": "Refill card balance",
                "verbose_name_plural": "Refill card balances",
            },
        ),
    ]
