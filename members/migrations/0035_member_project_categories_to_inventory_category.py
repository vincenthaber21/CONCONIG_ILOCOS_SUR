# Generated manually: Member.project_categories → inventory.Category

from django.db import migrations, models


def forwards_remap(apps, schema_editor):
    """
    Snapshot old Member↔ProjectCategory links, ensure matching inventory.Category
    rows exist, then after the field swap restore Member↔Category links.
    Stored on the migration module so the second RunPython can read them.
    """
    Member = apps.get_model("members", "Member")
    ProjectCategory = apps.get_model("members", "ProjectCategory")
    Category = apps.get_model("inventory", "Category")
    Through = Member.project_categories.through

    pc_to_cat = {}
    for pc in ProjectCategory.objects.all().iterator():
        cat = Category.objects.filter(name__iexact=pc.name).first()
        if not cat:
            cat = Category.objects.create(
                name=pc.name,
                description=getattr(pc, "description", "") or "",
                is_active=bool(getattr(pc, "is_active", True)),
            )
        pc_to_cat[pc.pk] = cat.pk

    forwards_remap.old_links = list(
        Through.objects.all().values_list("member_id", "projectcategory_id")
    )
    forwards_remap.pc_to_cat = pc_to_cat


def forwards_restore(apps, schema_editor):
    Member = apps.get_model("members", "Member")
    Through = Member.project_categories.through
    pc_to_cat = getattr(forwards_remap, "pc_to_cat", {})
    old_links = getattr(forwards_remap, "old_links", [])

    new_rows = []
    seen = set()
    for member_id, pc_id in old_links:
        cat_id = pc_to_cat.get(pc_id)
        if not cat_id:
            continue
        key = (member_id, cat_id)
        if key in seen:
            continue
        seen.add(key)
        new_rows.append(Through(member_id=member_id, category_id=cat_id))

    if new_rows:
        Through.objects.bulk_create(new_rows, ignore_conflicts=True)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("members", "0034_member_project_categories_m2m"),
        ("inventory", "0026_product_project_categories"),
    ]

    operations = [
        migrations.RunPython(forwards_remap, noop_reverse),
        migrations.RemoveField(
            model_name="member",
            name="project_categories",
        ),
        migrations.AddField(
            model_name="member",
            name="project_categories",
            field=models.ManyToManyField(
                blank=True,
                help_text=(
                    "Project categories assigned at registration (cashier or admin). "
                    "Select one or more. Managed under Inventory → Categories."
                ),
                related_name="members",
                to="inventory.category",
                verbose_name="Project categories",
            ),
        ),
        migrations.RunPython(forwards_restore, noop_reverse),
    ]
