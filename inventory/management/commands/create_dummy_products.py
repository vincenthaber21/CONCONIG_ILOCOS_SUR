from django.core.management.base import BaseCommand
from inventory.models import Category, Product
from decimal import Decimal
import random


class Command(BaseCommand):
    help = 'Create 200 dummy products for testing'

    def add_arguments(self, parser):
        parser.add_argument(
            '--count',
            type=int,
            default=200,
            help='Number of dummy products to create (default: 200)',
        )

    def handle(self, *args, **options):
        count = options['count']
        self.stdout.write(f'Creating {count} dummy products...')
        
        # Get or create categories
        categories = Category.objects.all()
        if not categories.exists():
            self.stdout.write('No categories found. Creating default categories...')
            categories = [
                Category.objects.create(name='Beverages', description='Drinks and beverages'),
                Category.objects.create(name='Snacks', description='Chips and snacks'),
                Category.objects.create(name='Groceries', description='General groceries'),
                Category.objects.create(name='Dairy', description='Dairy products'),
                Category.objects.create(name='Frozen', description='Frozen foods'),
                Category.objects.create(name='Personal Care', description='Personal care items'),
                Category.objects.create(name='Household', description='Household items'),
            ]
        else:
            categories = list(categories)
        
        # Product name templates
        product_templates = [
            'Product {num}',
            'Item {num}',
            'Good {num}',
            'Merchandise {num}',
            'Article {num}',
            'Commodity {num}',
            'Stock {num}',
            'Ware {num}',
        ]
        
        # Get existing barcodes to avoid duplicates
        existing_barcodes = set(Product.objects.values_list('barcode', flat=True))
        
        created_count = 0
        start_barcode = 1000000000000  # 13-digit barcode starting point
        
        for i in range(count):
            # Generate unique barcode
            barcode = str(start_barcode + i)
            while barcode in existing_barcodes:
                start_barcode += 1
                barcode = str(start_barcode + i)
            existing_barcodes.add(barcode)
            
            # Generate product name
            template = random.choice(product_templates)
            product_name = template.format(num=i + 1)
            
            # Random category (can be None)
            category = random.choice(categories + [None]) if random.random() > 0.1 else None
            
            # Random price between 10 and 500
            price = Decimal(str(round(random.uniform(10.0, 500.0), 2)))
            
            # Cost is 60-80% of price
            cost = Decimal(str(round(float(price) * random.uniform(0.6, 0.8), 2)))
            
            # Random stock quantity between 0 and 200
            stock_quantity = random.randint(0, 200)
            
            # Create product
            product = Product.objects.create(
                name=product_name,
                description=f'Dummy product #{i + 1} for testing purposes',
                barcode=barcode,
                category=category,
                price=price,
                cost=cost,
                stock_quantity=stock_quantity,
                is_active=random.choice([True, True, True, False])  # 75% active
            )
            
            created_count += 1
            if created_count % 50 == 0:
                self.stdout.write(f'Created {created_count} products...')
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Successfully created {created_count} dummy products!'
            )
        )

