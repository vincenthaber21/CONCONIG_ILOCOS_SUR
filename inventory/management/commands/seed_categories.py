from django.core.management.base import BaseCommand
from inventory.models import Category


CATEGORIES = [
    ("Electronics", "Electronic devices, gadgets, and accessories"),
    ("Clothing & Apparel", "Men's, women's, and children's clothing and fashion"),
    ("Home & Kitchen", "Household items, kitchenware, and home essentials"),
    ("Beauty & Personal Care", "Skincare, haircare, cosmetics, and grooming products"),
    ("Health & Wellness", "Vitamins, supplements, medical supplies, and wellness products"),
    ("Sports & Fitness", "Sporting goods, gym equipment, and activewear"),
    ("Automotive", "Car parts, accessories, and automotive supplies"),
    ("Toys & Games", "Children's toys, board games, and recreational items"),
    ("Books & Stationery", "Books, notebooks, pens, and office stationery"),
    ("Food & Beverages", "Packaged food, drinks, snacks, and consumables"),
    ("Furniture", "Indoor and outdoor furniture and furnishings"),
    ("Office Supplies", "Office equipment, supplies, and organizational tools"),
    ("Pet Supplies", "Pet food, accessories, and care products"),
    ("Baby Products", "Baby clothing, feeding, and care essentials"),
    ("Garden & Outdoor", "Gardening tools, outdoor furniture, and plants"),
    ("Tools & Hardware", "Hand tools, power tools, and hardware supplies"),
    ("Mobile Accessories", "Phone cases, chargers, cables, and mobile peripherals"),
    ("Footwear", "Shoes, sandals, boots, and other footwear"),
    ("Jewelry & Accessories", "Jewelry, watches, bags, and fashion accessories"),
    ("Grocery Items", "Everyday grocery staples and household consumables"),
]


class Command(BaseCommand):
    help = "Seed the database with 20 default product categories"

    def handle(self, *args, **options):
        created_count = 0
        skipped_count = 0

        for name, description in CATEGORIES:
            obj, created = Category.objects.get_or_create(
                name=name,
                defaults={"description": description, "is_active": True},
            )
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f"  Created: {name}"))
            else:
                skipped_count += 1
                self.stdout.write(self.style.WARNING(f"  Skipped (already exists): {name}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. {created_count} categories created, {skipped_count} already existed."
            )
        )
