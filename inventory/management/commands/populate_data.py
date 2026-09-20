from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from members.models import MemberType, Member, Role
from inventory.models import Category, Product
from decimal import Decimal


class Command(BaseCommand):
    help = 'Populate sample data for the kiosk system'

    def handle(self, *args, **kwargs):
        self.stdout.write('Creating sample data...')
        
        admin_user = User.objects.create_superuser('admin', 'admin@coop.com', 'admin123')
        self.stdout.write('Created admin user (username: admin, password: admin123)')
        
        member_type = MemberType.objects.create(
            name='Regular Member',
            description='Standard cooperative member'
        )
        self.stdout.write(f'Created member type: {member_type.name}')

        default_role = Role.objects.get(slug='member')
        
        members_data = [
            {'rfid': '1001', 'first_name': 'Juan', 'last_name': 'Dela Cruz', 'balance': 1000.00},
            {'rfid': '1002', 'first_name': 'Maria', 'last_name': 'Santos', 'balance': 500.00},
            {'rfid': '1003', 'first_name': 'Pedro', 'last_name': 'Reyes', 'balance': 2000.00},
        ]
        
        for data in members_data:
            member = Member.objects.create(
                rfid_card_number=data['rfid'],
                first_name=data['first_name'],
                last_name=data['last_name'],
                email=f"{data['first_name'].lower()}@email.com",
                member_type=member_type,
                member_role=default_role,
                balance=Decimal(str(data['balance']))
            )
            # set a sample 4-digit PIN for the member for demo/testing
            try:
                # generate a simple sample PIN based on rfid to keep it deterministic
                sample_pin = (str(data['rfid'])[-4:]).zfill(4)[:4]
                member.set_pin(sample_pin)
            except Exception:
                pass
            self.stdout.write(f'Created member: {member.full_name} (RFID: {member.rfid_card_number})')
        
        category1 = Category.objects.create(name='Beverages', description='Drinks and beverages')
        category2 = Category.objects.create(name='Snacks', description='Chips and snacks')
        category3 = Category.objects.create(name='Groceries', description='General groceries')
        self.stdout.write(f'Created categories')
        
        products_data = [
            {'barcode': '8888888888881', 'name': 'Coca Cola 1.5L', 'category': category1, 'price': 55.00, 'stock': 100},
            {'barcode': '8888888888882', 'name': 'Sprite 1.5L', 'category': category1, 'price': 55.00, 'stock': 100},
            {'barcode': '8888888888883', 'name': 'Royal 1.5L', 'category': category1, 'price': 50.00, 'stock': 100},
            {'barcode': '8888888888884', 'name': 'Mineral Water 500ml', 'category': category1, 'price': 15.00, 'stock': 200},
            {'barcode': '8888888888885', 'name': 'Piattos Cheese', 'category': category2, 'price': 25.00, 'stock': 150},
            {'barcode': '8888888888886', 'name': 'Nova Cheese', 'category': category2, 'price': 20.00, 'stock': 150},
            {'barcode': '8888888888887', 'name': 'Chippy BBQ', 'category': category2, 'price': 20.00, 'stock': 150},
            {'barcode': '8888888888888', 'name': 'Rice 5kg', 'category': category3, 'price': 250.00, 'stock': 50},
            {'barcode': '8888888888889', 'name': 'Sugar 1kg', 'category': category3, 'price': 60.00, 'stock': 80},
            {'barcode': '8888888888890', 'name': 'Cooking Oil 1L', 'category': category3, 'price': 120.00, 'stock': 60},
            {'barcode': '8888888888891', 'name': 'Instant Noodles', 'category': category3, 'price': 12.00, 'stock': 300},
            {'barcode': '8888888888892', 'name': 'Canned Sardines', 'category': category3, 'price': 35.00, 'stock': 100},
            {'barcode': '8888888888893', 'name': 'Coffee 3in1 Pack', 'category': category1, 'price': 45.00, 'stock': 100},
            {'barcode': '8888888888894', 'name': 'Milk Powder 300g', 'category': category1, 'price': 180.00, 'stock': 40},
            {'barcode': '8888888888895', 'name': 'Bread Loaf', 'category': category3, 'price': 45.00, 'stock': 80},
        ]
        
        for data in products_data:
            product = Product.objects.create(
                barcode=data['barcode'],
                name=data['name'],
                category=data['category'],
                price=Decimal(str(data['price'])),
                cost=Decimal(str(data['price'] * 0.7)),
                stock_quantity=data['stock']
            )
            self.stdout.write(f'Created product: {product.name} (Barcode: {product.barcode})')
        
        self.stdout.write(self.style.SUCCESS('Successfully populated sample data!'))
        self.stdout.write('=' * 60)
        self.stdout.write('QUICK START GUIDE:')
        self.stdout.write('1. Admin login: username=admin, password=admin123')
        self.stdout.write('2. Sample RFID cards: 1001, 1002, 1003')
        self.stdout.write('3. Sample barcodes: 8888888888881 to 8888888888895')
        self.stdout.write('=' * 60)
