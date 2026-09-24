# Generated manually: FK project_category → M2M project_categories

import django.db.models.deletion
from django.db import migrations, models


def copy_fk_to_m2m(apps, schema_editor):
    Member = apps.get_model("members", "Member")
    Through = Member.project_categories.through
    rows = []
    for member in Member.objects.exclude(project_category_id=None).iterator():
        rows.append(
            Through(member_id=member.pk, projectcategory_id=member.project_category_id)
        )
    if rows:
        Through.objects.bulk_create(rows, ignore_conflicts=True)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("members", "0033_project_category"),
    ]

    operations = [
        # Drop FK related_name first so M2M can take related_name="members".
        migrations.AlterField(
            model_name="member",
            name="project_category",
            field=models.ForeignKey(
                blank=True,
                help_text="Livelihood / project category assigned at registration (cashier or admin).",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="members.projectcategory",
                verbose_name="Project category",
            ),
        ),
        migrations.AddField(
            model_name="member",
            name="project_categories",
            field=models.ManyToManyField(
                blank=True,
                help_text=(
                    "Livelihood / project categories assigned at registration "
                    "(cashier or admin). Select one or more."
                ),
                related_name="members",
                to="members.projectcategory",
                verbose_name="Project categories",
            ),
        ),
        migrations.RunPython(copy_fk_to_m2m, noop_reverse),
        migrations.RemoveField(
            model_name="member",
            name="project_category",
        ),
    ]
