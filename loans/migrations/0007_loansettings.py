from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("loans", "0006_loandocumentation_signatures"),
    ]

    operations = [
        migrations.CreateModel(
            name="LoanSettings",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "grace_period_days",
                    models.PositiveIntegerField(
                        default=0,
                        help_text=(
                            "Days after an installment due date before late-payment interest applies. "
                            "Example: 5 means a member can still pay without late interest until 5 days "
                            "after the due date. Set to 0 to charge late interest starting the day after "
                            "the due date."
                        ),
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Loan Settings",
                "verbose_name_plural": "Loan Settings",
            },
        ),
    ]
