from django.core.management.base import BaseCommand
from inventory.models import Category, Product
from decimal import Decimal
import random
import string


class Command(BaseCommand):
    help = 'Generate 10 products for each category (500 total products)'

    def generate_barcode(self):
        """Generate random 13-digit barcode"""
        return ''.join(random.choices(string.digits, k=13))

    def handle(self, *args, **kwargs):
        categories = Category.objects.filter(is_active=True)

        if not categories.exists():
            self.stdout.write(self.style.ERROR('No categories found! Please add categories first.'))
            return

        products_data = {
            "Electronics": [
                "Smart LED TV 55\"", "Wireless Noise Cancelling Headphones", "4K Action Camera",
                "Bluetooth Speaker", "Smart Watch Fitness Tracker", "Gaming Laptop",
                "Tablet 10.1\" Display", "Portable Power Bank 20000mAh", "USB-C Hub Adapter",
                "Digital Voice Recorder"
            ],
            "Clothing & Apparel": [
                "Men's Cotton T-Shirt", "Women's Denim Jeans", "Hooded Sweatshirt",
                "Formal Dress Shirt", "Summer Maxi Dress", "Leather Jacket",
                "Sports Leggings", "Wool Scarf", "Baseball Cap", "Pajama Set"
            ],
            "Books": [
                "The Great Gatsby", "Python Programming Guide", "Cooking Recipes Book",
                "Self Help: Morning Routine", "Children's Picture Book", "History of Art",
                "Business Management 101", "Science Fiction Novel", "Travel Guide Paris",
                "Yoga for Beginners"
            ],
            "Home & Kitchen": [
                "Non-Stick Frying Pan", "Electric Kettle 1.5L", "Ceramic Dinner Set",
                "Microfiber Mop", "Knife Block Set", "Insulated Water Bottle",
                "Food Storage Containers", "Bamboo Cutting Board", "Coffee Maker",
                "Kitchen Scale Digital"
            ],
            "Sports & Outdoors": [
                "Yoga Mat Premium", "Dumbbell Set 20kg", "Camping Tent 4-Person",
                "Fitness Tracker Watch", "Soccer Ball Size 5", "Hiking Backpack 40L",
                "Jump Rope", "Resistance Bands Set", "Basketball Official Size",
                "Sleeping Bag - Winter"
            ],
            "Beauty & Personal Care": [
                "Facial Cleanser Foam", "Moisturizing Cream", "Charcoal Face Mask",
                "Hair Dryer Ionic", "Electric Toothbrush", "Perfume Eau de Parfum",
                "Shampoo & Conditioner Set", "Makeup Brush Kit", "Nail Polish Set",
                "Sunscreen SPF 50"
            ],
            "Toys & Games": [
                "LEGO Building Blocks", "Remote Control Car", "Board Game Monopoly",
                "Stuffed Teddy Bear", "Puzzle 1000 Pieces", "Action Figure Marvel",
                "Doll House Furniture", "Water Coloring Book", "Slime Making Kit",
                "Drone with Camera"
            ],
            "Automotive": [
                "Car Jump Starter", "Windshield Sun Shade", "Floor Mats Set",
                "Dashboard Camera", "Tire Pressure Gauge", "Car Vacuum Cleaner",
                "Phone Car Mount", "Leather Steering Wheel Cover", "Emergency Road Kit",
                "Car Scratch Remover"
            ],
            "Pet Supplies": [
                "Dog Food 5kg", "Cat Scratching Post", "Pet Grooming Brush",
                "Dog Bed Large", "Cat Litter Box", "Pet Carrier Backpack",
                "Chew Toys Pack", "Fish Tank Filter", "Bird Cage Small",
                "Pet Nail Clippers"
            ],
            "Office Supplies": [
                "Desk Organizer Set", "Stapler Heavy Duty", "Whiteboard Magnetic",
                "Printer Paper A4", "Ballpoint Pens 50pk", "Sticky Notes 3x3",
                "Scissor Set", "Desk Lamp LED", "Filing Cabinet", "Calculator Solar"
            ],
            "Groceries": [
                "Basmati Rice 5kg", "Olive Oil 1L", "Organic Honey 500g",
                "Whole Wheat Bread", "Orange Juice 1L", "Canned Beans Pack",
                "Pasta Spaghetti 500g", "Tomato Ketchup", "Cereal Breakfast",
                "Mineral Water 12pk"
            ],
            "Furniture": [
                "Office Chair Ergonomic", "Coffee Table Wood", "Bookshelf 5-Tier",
                "Bed Frame Queen", "Dining Table Set", "Sofa L-Shape",
                "Nightstand Drawer", "Wardrobe Closet", "Desk Computer Table",
                "TV Stand Unit"
            ],
            "Jewelry & Watches": [
                "Men's Analog Watch", "Silver Necklace", "Diamond Earrings",
                "Leather Bracelet", "Gold Plated Ring", "Smart Watch Band",
                "Pearl Pendant", "Crystal Anklet", "Couple Watch Set",
                "Brooch Pin Vintage"
            ],
            "Baby Products": [
                "Baby Diapers Pack", "Baby Wipes 80ct", "Baby Bottle Set",
                "Stroller Lightweight", "Baby Carrier Sling", "Crib Bedding Set",
                "Baby Monitor Digital", "Teething Toys", "Baby Shampoo",
                "Feeding Spoon Set"
            ],
            "Health & Wellness": [
                "Digital Thermometer", "Blood Pressure Monitor", "First Aid Kit",
                "Neck Massager", "Pulse Oximeter", "Heating Pad",
                "Knee Brace Support", "Medicine Organizer", "Inhaler Spacer",
                "Vitamins Multivitamin"
            ],
            "Tools & Home Improvement": [
                "Cordless Drill", "Hammer 16oz", "Screwdriver Set 15pc",
                "Measuring Tape 5m", "Level Tool 24\"", "Pliers Set",
                "Wrench Set Metric", "Utility Knife", "Tool Box Organizer",
                "Paint Roller Kit"
            ],
            "Musical Instruments": [
                "Acoustic Guitar", "Electronic Keyboard", "Violin Full Size",
                "Drum Set 5-Piece", "Ukulele Soprano", "Microphone Dynamic",
                "Guitar Strings Pack", "Piano Bench", "Flute Student", "Tambourine"
            ],
            "Shoes": [
                "Running Shoes Men", "Casual Sneakers", "Formal Leather Shoes",
                "Sports Sandals", "Winter Boots", "Women's Heels",
                "Slip-On Loafers", "Hiking Boots", "Kids' Sneakers", "Water Shoes"
            ],
            "Bags & Luggage": [
                "Backpack Laptop 17\"", "Travel Suitcase 28\"", "Handbag Tote",
                "Crossbody Bag", "Duffel Bag Sports", "School Bag Kids",
                "Wallet Leather", "Laptop Sleeve", "Beach Bag", "Camera Backpack"
            ],
            "Gardening": [
                "Garden Pruner", "Watering Can 5L", "Gardening Gloves",
                "Plant Pot Set", "Shovel Trowel Set", "Garden Hose 50ft",
                "Weed Puller Tool", "Seed Starter Kit", "Compost Bin",
                "Rain Gauge"
            ],
            "Camping & Hiking": [
                "Headlamp Flashlight", "Camping Stove", "Hiking Poles Pair",
                "Portable Chair", "Sleeping Pad", "Water Filter Bottle",
                "Camping Lantern", "Multi-tool Knife", "Dry Bag 20L", "Compass"
            ],
            "Fitness Equipment": [
                "Adjustable Dumbbell", "Pull Up Bar", "Resistance Tube Set",
                "Ab Roller Wheel", "Foam Roller", "Skipping Rope",
                "Push Up Stands", "Yoga Block", "Weighted Vest 10kg", "Hand Gripper"
            ],
            "Computer Accessories": [
                "Wireless Mouse", "Mechanical Keyboard", "Monitor 24\" IPS",
                "Laptop Stand", "USB Flash Drive 64GB", "Webcam HD 1080p",
                "Mouse Pad Large", "External Hard Drive 1TB", "Laptop Cooling Pad",
                "HDMI Cable 6ft"
            ],
            "Mobile Phones & Accessories": [
                "Phone Case Silicone", "Tempered Glass Screen Protector", "Fast Charger 65W",
                "Wireless Charger Pad", "Phone Stand Desk", "Power Bank Magnetic",
                "PopSocket Grip", "Phone Ring Holder", "Car Charger 2 Port", "Selfie Stick"
            ],
            "TV & Home Theater": [
                "Soundbar 2.1", "4K Streaming Stick", "Wall Mount Bracket",
                "Universal Remote", "Blu-ray Player", "Subwoofer 8\"",
                "HDMI Splitter", "Antenna Digital", "Projector 1080p", "Screen 100\""
            ],
            "Video Games": [
                "Gaming Controller", "Headset Gaming", "Xbox Game Pass",
                "PlayStation Store Card", "Nintendo Switch Games", "Gaming Mouse",
                "RGB Keyboard", "Game Capture Card", "Charging Station", "Gaming Chair"
            ],
            "Movies & TV Shows": [
                "DVD Box Set", "Blu-ray Movie", "Digital Code HD", "4K Ultra HD Disc",
                "Movie Poster 24x36", "TV Series Complete", "Film Cell Art", "DVD Storage Case",
                "Limited Edition Box", "Classic Movie Collection"
            ],
            "Music & CDs": [
                "CD Album New Release", "Vinyl Record LP", "Cassette Tape", "Music Box Set",
                "Concert DVD", "Guitar Pick Pack", "Record Player", "Headphones Wired",
                "CD Storage Binder", "Band T-Shirt"
            ],
            "Art & Craft": [
                "Watercolor Paint Set", "Sketch Pad A4", "Acrylic Paint 24ct",
                "Paintbrush Set", "Colored Pencils 72pk", "Craft Glue Gun",
                "Origami Paper 100pc", "Canvas Board", "Sewing Kit", "Beads Set"
            ],
            "Party Supplies": [
                "Balloon Arch Kit", "Birthday Banner", "Party Hats 12pk",
                "Tablecloth Plastic", "Cupcake Toppers", "Confetti Cannon",
                "Party Blowers", "Photo Booth Props", "LED String Lights", "Pinata"
            ],
            "Gift Cards": [
                "$10 Gift Card", "$25 Gift Card", "$50 Gift Card",
                "$100 Gift Card", "Birthday Greeting Card", "Thank You Card Set",
                "Gift Card Holder", "Holiday Card Pack", "E-Gift Email", "Custom Amount Card"
            ],
            "School Supplies": [
                "Backpack Kids", "Notebook College Ruled", "Mechanical Pencils",
                "Eraser Pack", "Pencil Case", "Binder 3-Ring 2\"",
                "Highlighter Set", "Lunch Bag Insulated", "Water Bottle 500ml", "Ruler 12\""
            ],
            "Stationery": [
                "Fountain Pen", "Journal Notebook", "Washi Tape Set",
                "Sticker Pack", "Envelope Set 50ct", "Letter Paper",
                "Calligraphy Set", "Sharpener Metal", "Glue Stick", "White Out Pen"
            ],
            "Sewing & Fabric": [
                "Sewing Machine Portable", "Thread Set 24 Colors", "Fabric Scissors",
                "Needle Set", "Measuring Tape", "Pins Cushion",
                "Felt Fabric Sheets", "Embroidery Hoop", "Zipper Assortment", "Button Pack"
            ],
            "Lighting": [
                "LED Bulb 9W", "Floor Lamp Modern", "Desk Lamp Adjustable",
                "String Lights 20ft", "Pendant Light", "Wall Sconce",
                "Ceiling Light Fixture", "Night Light Auto", "Flood Light Outdoor", "Smart Bulb"
            ],
            "Bathroom Fixtures": [
                "Shower Head", "Toilet Brush Set", "Bath Mat Cotton",
                "Towel Set 4pc", "Soap Dispenser", "Shower Caddy",
                "Robes Hook", "Toilet Paper Holder", "Faucet Chrome", "Mirror LED"
            ],
            "Lawn & Patio": [
                "Lawn Mower Manual", "Patio Umbrella", "Grass Trimmer",
                "Hammock Double", "Outdoor Chair Set", "Fire Pit Bowl",
                "Bird Feeder", "Garden Hose Reel", "Solar Lights Path", "BBQ Grill"
            ],
            "Seasonal Decor": [
                "Christmas Tree 6ft", "Halloween Decoration", "Easter Bunny Set",
                "Thanksgiving Table Decor", "Valentine Heart Lights", "St Patrick Decor",
                "Fall Wreath", "Summer Bunting Flag", "New Year Balloons", "Spring Flower Wreath"
            ],
            "Smart Home": [
                "Smart Plug WiFi", "Smart Bulb Color", "Smart Speaker",
                "Smart Thermostat", "Door Sensor", "Smart Lock",
                "Security Camera Indoor", "Video Doorbell", "Smart Hub", "Smart Switch"
            ],
            "Cameras & Photography": [
                "DSLR Camera Bundle", "Tripod 50\"", "Camera Bag",
                "SD Card 128GB", "Lens Cleaning Kit", "Memory Card Case",
                "Action Camera Mount", "Ring Light 10\"", "Remote Shutter", "Battery Grip"
            ],
            "Drones & Accessories": [
                "Quadcopter Drone", "Drone Battery Extra", "Propeller Set",
                "Drone Backpack Case", "Remote Controller", "Charger Hub",
                "Landing Pad", "Drone Light Kit", "GPS Module", "Camera Gimbal"
            ],
            "Printers & Ink": [
                "All-in-One Printer", "Black Ink Cartridge", "Color Ink Pack",
                "Toner Cartridge", "Photo Paper Glossy", "Printer Cable USB",
                "Refill Kit", "Maintenance Box", "Label Printer", "Thermal Paper"
            ],
            "Networking Equipment": [
                "WiFi Router AC", "Network Switch 8 Port", "Ethernet Cable Cat6",
                "WiFi Extender", "Mesh System 3 Pack", "Powerline Adapter",
                "Network Card", "Patch Panel", "Cable Tester", "Rack Mount"
            ],
            "Software": [
                "Antivirus 1 Year", "Office Suite", "Photo Editor Pro",
                "PDF Editor", "Backup Software", "Video Editor",
                "Screen Recorder", "Password Manager", "System Cleaner", "VPN Service"
            ],
            "Medical Supplies": [
                "Face Mask 50ct", "Latex Gloves Box", "Bandage Assorted",
                "Alcohol Wipes 100ct", "Cotton Balls 200ct", "Gauze Pads",
                "Tape Medical", "Scissors Medical", "Tweezers Stainless", "Eye Patch"
            ],
            "Safety & Security": [
                "Smoke Detector", "Fire Extinguisher", "Security Camera Outdoor",
                "Motion Sensor Light", "Door Stop Alarm", "Window Lock",
                "Safe Box Digital", "Peephole Viewer", "Carbon Monoxide Detector", "CCTV Kit"
            ],
            "Cleaning Supplies": [
                "All Purpose Cleaner", "Microfiber Cloths 12pk", "Broom Dustpan Set",
                "Glass Cleaner Spray", "Disinfectant Wipes", "Sponge Scrubber 10pk",
                "Mop Refill", "Vacuum Bags", "Trash Bags 50ct", "Duster Extendable"
            ],
            "Laundry": [
                "Laundry Detergent", "Fabric Softener Liquid", "Dryer Sheets 100ct",
                "Stain Remover", "Wool Dryer Balls", "Washing Machine Cleaner",
                "Laundry Basket", "Iron Steam", "Ironing Board", "Drying Rack"
            ],
            "Food & Beverage": [
                "Potato Chips Pack", "Chocolate Bar", "Soda Can 12pk",
                "Bottled Water 24pk", "Cookie Assortment", "Energy Drink",
                "Nuts Mix Pack", "Granola Bar Box", "Gum Mint 3pk", "Crackers Snack"
            ],
            "Alcoholic Beverages": [
                "Red Wine 750ml", "White Wine Bottle", "Craft Beer 6pk",
                "Vodka 1L", "Whiskey 750ml", "Gin London",
                "Rum Aged", "Champagne Brut", "Tequila Silver", "Liqueur Set"
            ]
        }

        created_count = 0
        skipped_count = 0

        for category in categories:
            if category.name not in products_data:
                continue

            for product_name in products_data[category.name]:
                # Generate a unique barcode (retry if collision)
                for _ in range(10):
                    barcode = self.generate_barcode()
                    if not Product.objects.filter(barcode=barcode).exists():
                        break

                price = Decimal(random.uniform(9.99, 299.99)).quantize(Decimal('0.01'))
                cost = Decimal(float(price) * random.uniform(0.4, 0.7)).quantize(Decimal('0.01'))
                stock = random.randint(0, 500)
                threshold = random.randint(5, 50)

                obj, created = Product.objects.get_or_create(
                    name=product_name,
                    category=category,
                    defaults={
                        'barcode': barcode,
                        'description': (
                            f"High quality {product_name.lower()} perfect for your needs. "
                            "Brand new condition with warranty."
                        ),
                        'price': price,
                        'cost': cost,
                        'stock_quantity': stock,
                        'low_stock_threshold': threshold,
                        'is_active': True,
                    }
                )

                if created:
                    created_count += 1
                    self.stdout.write(f'  Created: {product_name} [{category.name}]')
                else:
                    skipped_count += 1

        self.stdout.write(self.style.SUCCESS(
            f'\nCompleted! Created: {created_count} products, Skipped: {skipped_count}'
        ))
        self.stdout.write(self.style.SUCCESS(
            f'Total products in database: {Product.objects.count()}'
        ))
