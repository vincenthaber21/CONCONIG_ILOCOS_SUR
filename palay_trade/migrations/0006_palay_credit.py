from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("palay_trade", "0005_seed_rice_palay_and_bigas"),
    ]

    operations = [
        migrations.AddField(
            model_name="palaytradeproduct",
            name="credit_enabled",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Allow members to post this product on palay credit when palay credit "
                    "is enabled in settings."
                ),
            ),
        ),
        migrations.CreateModel(
            name="PalayCreditSettings",
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
                    "is_enabled",
                    models.BooleanField(
                        default=False,
                        help_text=(
                            "When enabled, staff can post eligible trades on palay credit "
                            "for members."
                        ),
                    ),
                ),
                (
                    "member_max_outstanding",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("0.00"),
                        help_text=(
                            "Maximum total unsettled palay credit per member. "
                            "Set to 0 for no limit."
                        ),
                        max_digits=12,
                    ),
                ),
                (
                    "grace_period_days",
                    models.PositiveIntegerField(
                        default=7,
                        help_text=(
                            "Days after a credit trade before interest may apply. "
                            "Members can pay within this period with no interest."
                        ),
                    ),
                ),
                (
                    "interest_rate",
                    models.DecimalField(
                        decimal_places=3,
                        default=Decimal("0.000"),
                        help_text=(
                            "Monthly interest on unpaid palay credit after grace. "
                            "Use 0.015 for 1.5% per month. Set to 0 to disable interest."
                        ),
                        max_digits=6,
                    ),
                ),
                (
                    "interest_enabled",
                    models.BooleanField(
                        default=False,
                        help_text="Apply monthly interest to overdue palay credit balances.",
                    ),
                ),
                (
                    "allow_credit_on_sell",
                    models.BooleanField(
                        default=True,
                        help_text=(
                            "Member may buy Rice Palay or Bigas on credit "
                            "(member owes the coop)."
                        ),
                    ),
                ),
                (
                    "allow_credit_on_buy",
                    models.BooleanField(
                        default=False,
                        help_text=(
                            "Member may sell palay on credit (coop pays later). "
                            "Usually disabled; enable only if your coop records farmer "
                            "advances this way."
                        ),
                    ),
                ),
                (
                    "min_membership_months",
                    models.PositiveIntegerField(
                        default=0,
                        help_text=(
                            "Minimum months registered before a member may use palay credit. "
                            "0 = no waiting period."
                        ),
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Palay credit settings",
                "verbose_name_plural": "Palay credit settings",
            },
        ),
        migrations.AddField(
            model_name="palaytrade",
            name="payment_method",
            field=models.CharField(
                choices=[("cash", "Cash"), ("credit", "Palay credit")],
                db_index=True,
                default="cash",
                max_length=8,
            ),
        ),
        migrations.AddField(
            model_name="palaytrade",
            name="credit_amount_paid",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                help_text="Amount already paid against this palay credit ticket.",
                max_digits=14,
            ),
        ),
        migrations.AddField(
            model_name="palaytrade",
            name="credit_settled_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When the palay credit balance for this ticket was fully paid.",
                null=True,
            ),
        ),
    ]
