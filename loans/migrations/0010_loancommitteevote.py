import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("loans", "0009_committeereview_staff_signature"),
    ]

    operations = [
        migrations.CreateModel(
            name="LoanCommitteeVote",
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
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "vote",
                    models.CharField(
                        choices=[("APPROVE", "Approve"), ("REJECT", "Reject")],
                        max_length=10,
                    ),
                ),
                ("remarks", models.TextField(blank=True)),
                (
                    "application",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="committee_votes",
                        to="loans.loanapplication",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="loan_committee_votes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["created_at"],
                "unique_together": {("application", "user")},
            },
        ),
    ]
