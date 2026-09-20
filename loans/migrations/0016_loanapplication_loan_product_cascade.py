# Generated manually for loan product delete support

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("loans", "0015_loanproduct_requires_insurance_default_false"),
    ]

    operations = [
        migrations.AlterField(
            model_name="loanapplication",
            name="loan_product",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="applications",
                to="loans.loanproduct",
            ),
        ),
    ]
