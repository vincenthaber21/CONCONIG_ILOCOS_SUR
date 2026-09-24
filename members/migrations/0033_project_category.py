# Generated manually for ProjectCategory + Member.project_category

import django.db.models.deletion
from django.db import migrations, models


def seed_project_categories(apps, schema_editor):
    ProjectCategory = apps.get_model("members", "ProjectCategory")
    defaults = [
        ("rice", "Rice", "Rice / palay production", 10),
        ("corn", "Corn", "Corn production", 20),
        ("high-value-crops", "High Value Crops", "Vegetables, fruits, and other HVCs", 30),
        ("livestock", "Livestock", "Cattle, carabao, goat, swine, and related", 40),
        ("poultry", "Poultry", "Chicken, duck, and related poultry", 50),
        ("fisheries", "Fisheries / Aquaculture", "Capture fisheries and fishpond / aquaculture", 60),
        ("dairy", "Dairy", "Dairy production", 70),
        ("trading", "Trading / Retail", "Trading, retail, and related enterprises", 80),
        ("other", "Other", "Other livelihood / project category", 999),
    ]
    for slug, name, description, sort_order in defaults:
        ProjectCategory.objects.get_or_create(
            slug=slug,
            defaults={
                "name": name,
                "description": description,
                "sort_order": sort_order,
                "is_active": True,
            },
        )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("members", "0032_member_signature"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProjectCategory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("slug", models.SlugField(max_length=64, unique=True)),
                ("name", models.CharField(max_length=150)),
                ("description", models.TextField(blank=True, default="")),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
                (
                    "is_active",
                    models.BooleanField(
                        default=True,
                        help_text="Uncheck to hide this category from new member assignments.",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Project category",
                "verbose_name_plural": "Project categories",
                "ordering": ["sort_order", "name"],
            },
        ),
        migrations.AddField(
            model_name="member",
            name="project_category",
            field=models.ForeignKey(
                blank=True,
                help_text="Livelihood / project category assigned at registration (cashier or admin).",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="members",
                to="members.projectcategory",
                verbose_name="Project category",
            ),
        ),
        migrations.RunPython(seed_project_categories, noop_reverse),
    ]
