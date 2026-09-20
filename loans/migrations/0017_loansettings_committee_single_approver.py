from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("loans", "0016_loanapplication_loan_product_cascade"),
    ]

    operations = [
        migrations.AddField(
            model_name="loansettings",
            name="committee_single_approver",
            field=models.BooleanField(
                default=True,
                help_text=(
                    "When enabled, one authorized approver (admin, loan officer, staff, or "
                    "credit committee) can approve or reject a loan. When disabled, a majority "
                    "of listed approvers is required."
                ),
            ),
        ),
    ]
