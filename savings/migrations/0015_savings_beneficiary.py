import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("members", "0036_member_multiple_roles"),
        ("savings", "0014_savings_walk_in"),
    ]

    operations = [
        migrations.CreateModel(
            name="SavingsBeneficiary",
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
                ("first_name", models.CharField(blank=True, max_length=100)),
                ("last_name", models.CharField(blank=True, max_length=100)),
                (
                    "relationship",
                    models.CharField(
                        choices=[
                            ("spouse", "Spouse"),
                            ("child", "Child"),
                            ("parent", "Parent"),
                            ("sibling", "Sibling"),
                            ("other", "Other"),
                        ],
                        max_length=20,
                    ),
                ),
                (
                    "account",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="beneficiaries",
                        to="savings.membersavingsaccount",
                    ),
                ),
                (
                    "member",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="savings_beneficiaries",
                        to="members.member",
                    ),
                ),
            ],
            options={
                "verbose_name": "Savings beneficiary",
                "verbose_name_plural": "Savings beneficiaries",
                "ordering": ["created_at"],
            },
        ),
    ]
