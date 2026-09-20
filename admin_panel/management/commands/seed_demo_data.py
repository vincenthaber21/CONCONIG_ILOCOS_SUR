"""Seed realistic demo catalog, members, and completed sales for local testing."""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction
from django.utils import timezone

from inventory.models import Category, Product, ProductSaleUnit
from members.models import Member, MemberType, Role
from transactions.models import Transaction, TransactionItem, WalkInCustomer

DEMO_NOTE = "[demo seed]"
BARCODE_PREFIX = "DEMO"


class Command(BaseCommand):
    help = (
        "Load demo categories, products, members, walk-ins, and completed sales "
        "so the dashboard and kiosk have realistic data (Jan–Sep 2026)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--sales",
            type=int,
            default=120,
            help="Number of completed sales to create (default: 120).",
        )
        parser.add_argument(
            "--members",
            type=int,
            default=25,
            help="Number of demo members to create (default: 25).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Delete previous demo-seeded rows (notes/barcodes) before creating.",
        )

    def handle(self, *args, **options):
        sales_n = max(10, int(options["sales"]))
        members_n = max(5, int(options["members"]))
        force = bool(options["force"])
        random.seed(20260920)

        if force:
            self._purge_demo()

        with db_transaction.atomic():
            categories, products = self._ensure_catalog()
            members = self._ensure_members(members_n)
            walk_ins = self._ensure_walk_ins()
            created_sales = self._create_sales(sales_n, products, members, walk_ins)
            self._create_queue_samples(products)
            self._create_refund_sample(products, members)

        self.stdout.write(
            self.style.SUCCESS(
                f"Demo data ready: {len(categories)} categories, {len(products)} products, "
                f"{len(members)} members, {created_sales} sales."
            )
        )
        self.stdout.write("Refresh /dashboard/ to see revenue, top products, and charts.")

    def _purge_demo(self):
        deleted_tx = Transaction.objects.filter(notes__startswith=DEMO_NOTE).delete()[0]
        deleted_prod = Product.objects.filter(barcode__startswith=BARCODE_PREFIX).delete()[0]
        deleted_mem = Member.objects.filter(username__startswith="demo_member_").delete()[0]
        WalkInCustomer.objects.filter(name_key__startswith="demo walk").delete()
        Category.objects.filter(name__startswith="Demo ").delete()
        self.stdout.write(
            f"Purged previous demo rows (tx≈{deleted_tx}, products≈{deleted_prod}, members≈{deleted_mem})."
        )

    def _ensure_catalog(self):
        catalog = {
            "Demo Beverages": [
                ("Coca Cola 1.5L", "55.00", 120),
                ("Sprite 1.5L", "55.00", 90),
                ("Mineral Water 500ml", "15.00", 200),
                ("Coffee 3in1 Pack", "45.00", 8),  # low stock
            ],
            "Demo Snacks": [
                ("Piattos Cheese", "25.00", 150),
                ("Nova Cheese", "20.00", 140),
                ("Chippy BBQ", "20.00", 5),  # low stock
                ("Bread Loaf", "45.00", 0),  # out of stock
            ],
            "Demo Groceries": [
                ("Rice 5kg", "250.00", 60),
                ("Sugar 1kg", "60.00", 80),
                ("Cooking Oil 1L", "120.00", 55),
                ("Instant Noodles", "12.00", 300),
                ("Canned Sardines", "35.00", 100),
                ("Milk Powder 300g", "180.00", 40),
            ],
        }
        categories = []
        products = []
        idx = 1
        for cat_name, items in catalog.items():
            cat, _ = Category.objects.get_or_create(
                name=cat_name,
                defaults={"description": "Demo category for local testing", "is_active": True},
            )
            categories.append(cat)
            for name, price, stock in items:
                barcode = f"{BARCODE_PREFIX}{idx:010d}"
                idx += 1
                product, created = Product.objects.get_or_create(
                    barcode=barcode,
                    defaults={
                        "name": name,
                        "description": f"{DEMO_NOTE} {name}",
                        "category": cat,
                        "price": Decimal(price),
                        "cost": (Decimal(price) * Decimal("0.70")).quantize(Decimal("0.01")),
                        "stock_quantity": Decimal(stock),
                        "low_stock_threshold": Decimal("10"),
                        "is_active": True,
                    },
                )
                if not created:
                    product.stock_quantity = Decimal(stock)
                    product.is_active = True
                    product.save(update_fields=["stock_quantity", "is_active", "updated_at"])
                ProductSaleUnit.objects.get_or_create(
                    product=product,
                    barcode=f"{barcode}-R",
                    defaults={
                        "sale_mode": ProductSaleUnit.SALE_MODE_RETAIL,
                        "unit_label": "Piece",
                        "price": product.price,
                        "units_per_package": 1,
                        "is_active": True,
                    },
                )
                products.append(product)
        return categories, products

    def _ensure_members(self, count):
        role, _ = Role.objects.get_or_create(
            slug="member",
            defaults={"name": "Member", "sort_order": 100, "is_active": True},
        )
        member_type, _ = MemberType.objects.get_or_create(
            name="Regular Member",
            defaults={"description": "Standard cooperative member", "is_active": True},
        )
        tz = timezone.get_current_timezone()
        first_names = [
            "Juan", "Maria", "Pedro", "Ana", "Luis", "Carmen", "Jose", "Rosa",
            "Carlos", "Elena", "Miguel", "Sofia", "Ramon", "Isabel", "Andres",
        ]
        last_names = [
            "Dela Cruz", "Santos", "Reyes", "Garcia", "Ramos", "Torres", "Flores",
            "Mendoza", "Cruz", "Bautista", "Navarro", "Lopez", "Aquino", "Villanueva",
        ]
        members = []
        for i in range(1, count + 1):
            username = f"demo_member_{i:03d}"
            joined = timezone.make_aware(
                datetime(2026, random.randint(1, 9), random.randint(1, 28), 10, 0, 0),
                tz,
            )
            member, created = Member.objects.get_or_create(
                username=username,
                defaults={
                    "rfid_card_number": f"DM{i:04d}{1000 + i}",
                    "first_name": first_names[(i - 1) % len(first_names)],
                    "last_name": last_names[(i - 1) % len(last_names)],
                    "email": f"{username}@example.com",
                    "phone": f"09{random.randint(100000000, 999999999)}",
                    "member_type": member_type,
                    "member_role": role,
                    "balance": Decimal(str(round(random.uniform(200, 5000), 2))),
                    "is_active": True,
                    "date_joined": joined,
                },
            )
            if created:
                member.set_pin(f"{i:04d}"[-4:])
            members.append(member)
        return members

    def _ensure_walk_ins(self):
        names = [
            "Demo Walk Ana",
            "Demo Walk Ben",
            "Demo Walk Carla",
            "Demo Walk Diego",
            "Demo Walk Eva",
        ]
        walk_ins = []
        for name in names:
            key = name.strip().lower()
            obj, _ = WalkInCustomer.objects.get_or_create(
                name_key=key,
                defaults={"display_name": name},
            )
            walk_ins.append(obj)
        return walk_ins

    def _create_sales(self, sales_n, products, members, walk_ins):
        existing = Transaction.objects.filter(notes__startswith=DEMO_NOTE, status="completed").count()
        if existing >= sales_n:
            self.stdout.write(f"Already have {existing} demo completed sales; skipping sale create.")
            return existing

        tz = timezone.get_current_timezone()
        start = timezone.make_aware(datetime(2026, 1, 1, 8, 0, 0), tz)
        end = timezone.make_aware(datetime(2026, 9, 20, 18, 0, 0), tz)
        span_seconds = int((end - start).total_seconds())
        to_create = sales_n - existing
        created = 0

        for n in range(to_create):
            when = start + timedelta(seconds=random.randint(0, span_seconds))
            use_member = random.random() < 0.62
            member = random.choice(members) if use_member else None
            walk_in = None
            guest_name = ""
            if member is None:
                walk_in = random.choice(walk_ins)
                guest_name = walk_in.display_name

            line_products = random.sample(products, k=random.randint(1, min(4, len(products))))
            lines = []
            subtotal = Decimal("0.00")
            for product in line_products:
                qty = Decimal(random.randint(1, 5))
                unit = product.price
                total = (unit * qty).quantize(Decimal("0.01"))
                lines.append((product, qty, unit, total))
                subtotal += total

            payment = "debit" if member and random.random() < 0.55 else random.choice(["cash", "cash", "credit"])
            if member is None and payment == "debit":
                payment = "cash"

            txn = Transaction(
                member=member,
                guest_customer_name=guest_name,
                walk_in_customer=walk_in,
                subtotal=subtotal,
                vatable_sale=subtotal,
                vat_amount=Decimal("0.00"),
                total_amount=subtotal,
                payment_method=payment,
                amount_paid=subtotal,
                amount_from_balance=subtotal if payment == "debit" else Decimal("0.00"),
                status="completed",
                notes=f"{DEMO_NOTE} completed sale",
                created_at=when,
            )
            txn.save()
            # Ensure created_at sticks (auto fields / signals).
            Transaction.objects.filter(pk=txn.pk).update(created_at=when)

            for product, qty, unit, total in lines:
                TransactionItem.objects.create(
                    transaction=txn,
                    product=product,
                    product_name=product.name,
                    product_barcode=product.barcode,
                    unit_price=unit,
                    quantity=qty,
                    total_price=total,
                    vat_amount=Decimal("0.00"),
                    vatable_sale=total,
                )
            created += 1

        return existing + created

    def _create_queue_samples(self, products):
        """A few live-queue style rows for pending / refund request / return window."""
        if Transaction.objects.filter(notes=f"{DEMO_NOTE} pending checkout").exists():
            return
        product = products[0]
        for status, note_suffix, total in [
            ("pending", "pending checkout", Decimal("95.00")),
            ("refund_requested", "refund request", Decimal("120.00")),
            ("return_window", "return window", Decimal("75.00")),
        ]:
            txn = Transaction.objects.create(
                guest_customer_name="Demo Queue Guest",
                subtotal=total,
                vatable_sale=total,
                vat_amount=Decimal("0.00"),
                total_amount=total,
                payment_method="cash",
                amount_paid=total,
                status=status,
                notes=f"{DEMO_NOTE} {note_suffix}",
            )
            TransactionItem.objects.create(
                transaction=txn,
                product=product,
                product_name=product.name,
                product_barcode=product.barcode,
                unit_price=total,
                quantity=Decimal("1"),
                total_price=total,
                vat_amount=Decimal("0.00"),
                vatable_sale=total,
            )

    def _create_refund_sample(self, products, members):
        if Transaction.objects.filter(notes=f"{DEMO_NOTE} refunded sale").exists():
            return
        tz = timezone.get_current_timezone()
        when = timezone.make_aware(datetime(2026, 8, 15, 14, 30, 0), tz)
        product = products[1]
        total = product.price * Decimal("2")
        member = members[0]
        txn = Transaction(
            member=member,
            subtotal=total,
            vatable_sale=total,
            vat_amount=Decimal("0.00"),
            total_amount=Decimal("0.00"),
            payment_method="cash",
            amount_paid=total,
            status="refunded",
            notes=f"{DEMO_NOTE} refunded sale",
            created_at=when,
        )
        txn.save()
        Transaction.objects.filter(pk=txn.pk).update(created_at=when)
        TransactionItem.objects.create(
            transaction=txn,
            product=product,
            product_name=product.name,
            product_barcode=product.barcode,
            unit_price=product.price,
            quantity=Decimal("2"),
            total_price=total,
            vat_amount=Decimal("0.00"),
            vatable_sale=total,
            refunded_at=when + timedelta(days=1),
        )
