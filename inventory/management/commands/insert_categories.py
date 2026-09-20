from django.core.management.base import BaseCommand
from inventory.models import Category


class Command(BaseCommand):
    help = 'Insert 50 categories into the database'

    def handle(self, *args, **kwargs):
        categories_with_desc = [
            ("Electronics", "Devices, gadgets, and electronic equipment"),
            ("Clothing & Apparel", "Shirts, pants, dresses, and other clothing items"),
            ("Books", "Printed and digital books across all genres"),
            ("Home & Kitchen", "Kitchenware, appliances, and home decor"),
            ("Sports & Outdoors", "Sporting goods, camping gear, and outdoor equipment"),
            ("Beauty & Personal Care", "Cosmetics, skincare, and personal hygiene products"),
            ("Toys & Games", "Children toys, board games, and puzzles"),
            ("Automotive", "Car parts, accessories, and maintenance products"),
            ("Pet Supplies", "Food, toys, and accessories for pets"),
            ("Office Supplies", "Stationery, paper products, and office equipment"),
            ("Groceries", "Fresh and packaged food items"),
            ("Furniture", "Beds, sofas, tables, and other furniture"),
            ("Jewelry & Watches", "Necklaces, rings, bracelets, and timepieces"),
            ("Baby Products", "Diapers, baby food, strollers, and nursery items"),
            ("Health & Wellness", "Vitamins, supplements, and health monitors"),
            ("Tools & Home Improvement", "Power tools, hand tools, and hardware supplies"),
            ("Musical Instruments", "Guitars, pianos, drums, and accessories"),
            ("Shoes", "Footwear for men, women, and children"),
            ("Bags & Luggage", "Backpacks, suitcases, handbags, and travel bags"),
            ("Gardening", "Seeds, plants, tools, and outdoor garden supplies"),
            ("Camping & Hiking", "Tents, sleeping bags, backpacks, and hiking gear"),
            ("Fitness Equipment", "Exercise machines, weights, and yoga mats"),
            ("Computer Accessories", "Keyboards, mice, monitors, and computer peripherals"),
            ("Mobile Phones & Accessories", "Smartphones, cases, chargers, and screen protectors"),
            ("TV & Home Theater", "Televisions, soundbars, and home theater systems"),
            ("Video Games", "Game consoles, controllers, and video game software"),
            ("Movies & TV Shows", "DVDs, Blu-rays, and digital movie downloads"),
            ("Music & CDs", "Music albums, CDs, and vinyl records"),
            ("Art & Craft", "Paints, brushes, canvas, and craft supplies"),
            ("Party Supplies", "Balloons, decorations, and party favors"),
            ("Gift Cards", "Store credit and prepaid gift cards"),
            ("School Supplies", "Notebooks, backpacks, and educational materials"),
            ("Stationery", "Pens, pencils, paper, and envelopes"),
            ("Sewing & Fabric", "Fabrics, threads, sewing machines, and patterns"),
            ("Lighting", "Lamps, light bulbs, and lighting fixtures"),
            ("Bathroom Fixtures", "Showers, faucets, toilets, and bathroom accessories"),
            ("Lawn & Patio", "Lawn mowers, patio furniture, and outdoor decor"),
            ("Seasonal Decor", "Holiday decorations and seasonal ornaments"),
            ("Smart Home", "Smart speakers, thermostats, and home automation devices"),
            ("Cameras & Photography", "Digital cameras, lenses, tripods, and photo accessories"),
            ("Drones & Accessories", "Quadcopters, drone batteries, and propellers"),
            ("Printers & Ink", "Printers, ink cartridges, and toner"),
            ("Networking Equipment", "Routers, switches, and network cables"),
            ("Software", "Computer programs, operating systems, and apps"),
            ("Medical Supplies", "First aid kits, bandages, and medical equipment"),
            ("Safety & Security", "Smoke detectors, security cameras, and locks"),
            ("Cleaning Supplies", "Detergents, brooms, mops, and cleaning chemicals"),
            ("Laundry", "Laundry detergents, fabric softeners, and dryer sheets"),
            ("Food & Beverage", "Snacks, drinks, and packaged foods"),
            ("Alcoholic Beverages", "Beer, wine, spirits, and mixers")
        ]

        created_count = 0
        skipped_count = 0

        for name, description in categories_with_desc:
            obj, created = Category.objects.get_or_create(
                name=name,
                defaults={
                    'description': description,
                    'is_active': True
                }
            )
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f'✓ Created: {name}'))
            else:
                skipped_count += 1
                self.stdout.write(self.style.WARNING(f'⚠ Already exists: {name}'))

        self.stdout.write(self.style.SUCCESS(
            f'\n✅ Completed! Created: {created_count}, Skipped: {skipped_count}'
        ))
