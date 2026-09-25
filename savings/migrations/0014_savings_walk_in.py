import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("savings", "0013_membersavingsaccount_passbook_serial"),
    ]

    operations = [
        migrations.CreateModel(
            name="SavingsWalkIn",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("first_name", models.CharField(max_length=100)),
                ("middle_name", models.CharField(blank=True, max_length=100)),
                ("last_name", models.CharField(max_length=100)),
                ("phone", models.CharField(blank=True, max_length=20)),
                ("address", models.CharField(blank=True, max_length=255)),
            ],
            options={
                "verbose_name": "Walk-in savings customer",
                "verbose_name_plural": "Walk-in savings customers",
                "ordering": ["last_name", "first_name"],
            },
        ),
        migrations.AlterField(
            model_name="membersavingsaccount",
            name="member",
            field=models.ForeignKey(
                blank=True,
                help_text="Primary account holder when the saver is a cooperative member.",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="savings_accounts",
                to="members.member",
            ),
        ),
        migrations.AddField(
            model_name="membersavingsaccount",
            name="walk_in",
            field=models.ForeignKey(
                blank=True,
                help_text="Set when this savings account belongs to a walk-in who is not a member.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="accounts",
                to="savings.savingswalkin",
            ),
        ),
    ]
