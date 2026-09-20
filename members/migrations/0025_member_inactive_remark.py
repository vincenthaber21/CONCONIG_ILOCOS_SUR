from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("members", "0024_add_loan_officer_role"),
    ]

    operations = [
        migrations.AddField(
            model_name="member",
            name="inactive_remark",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Required when the member is inactive. Explain why the account was deactivated.",
            ),
        ),
    ]
