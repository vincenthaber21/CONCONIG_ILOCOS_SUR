# Generated manually for savings product delete support

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("savings", "0004_savings_account_list_index"),
    ]

    operations = [
        migrations.AlterField(
            model_name="membersavingsaccount",
            name="product",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="accounts",
                to="savings.savingsproduct",
            ),
        ),
    ]
