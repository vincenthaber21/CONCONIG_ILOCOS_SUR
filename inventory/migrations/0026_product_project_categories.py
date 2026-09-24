# Generated manually: Product.project_categories M2M

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0025_product_kilo_unit_type"),
        ("members", "0034_member_project_categories_m2m"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="project_categories",
            field=models.ManyToManyField(
                blank=True,
                help_text=(
                    "Assign one or more livelihood / project categories. "
                    "Cashiers only see products that match their assigned project categories."
                ),
                related_name="products",
                to="members.projectcategory",
                verbose_name="Project categories",
            ),
        ),
    ]
