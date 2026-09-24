# Generated manually: Product.project_categories → inventory.Category

from django.db import migrations, models


def forwards_remap(apps, schema_editor):
    Product = apps.get_model("inventory", "Product")
    ProjectCategory = apps.get_model("members", "ProjectCategory")
    Category = apps.get_model("inventory", "Category")
    Through = Product.project_categories.through

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

    # Old through column is projectcategory_id (FK to members.ProjectCategory)
    forwards_remap.old_links = list(
        Through.objects.all().values_list("product_id", "projectcategory_id")
    )
    forwards_remap.pc_to_cat = pc_to_cat


def forwards_restore(apps, schema_editor):
    Product = apps.get_model("inventory", "Product")
    Through = Product.project_categories.through
    pc_to_cat = getattr(forwards_remap, "pc_to_cat", {})
    old_links = getattr(forwards_remap, "old_links", [])

    new_rows = []
    seen = set()
    for product_id, pc_id in old_links:
        cat_id = pc_to_cat.get(pc_id)
        if not cat_id:
            continue
        key = (product_id, cat_id)
        if key in seen:
            continue
        seen.add(key)
        # New through column for Category M2M with related_name project_products
        # Django names the FK column after the target model: category_id
        new_rows.append(Through(product_id=product_id, category_id=cat_id))

    if new_rows:
        Through.objects.bulk_create(new_rows, ignore_conflicts=True)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0026_product_project_categories"),
        ("members", "0035_member_project_categories_to_inventory_category"),
    ]

    operations = [
        migrations.RunPython(forwards_remap, noop_reverse),
        migrations.RemoveField(
            model_name="product",
            name="project_categories",
        ),
        migrations.AddField(
            model_name="product",
            name="project_categories",
            field=models.ManyToManyField(
                blank=True,
                help_text=(
                    "Assign one or more categories (same list as Inventory → Categories). "
                    "Cashiers only see products that match their assigned project categories."
                ),
                related_name="project_products",
                to="inventory.category",
                verbose_name="Project categories",
            ),
        ),
        migrations.RunPython(forwards_restore, noop_reverse),
    ]
