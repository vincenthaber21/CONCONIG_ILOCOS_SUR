from decimal import Decimal
import random
import uuid

from django.core.management.base import BaseCommand

from members.models import Member, MemberType, Role
from transactions.models import Transaction


class Command(BaseCommand):
    help = "Create dummy data for Top Members dashboard widget."

    def add_arguments(self, parser):
        parser.add_argument(
            "--count",
            type=int,
            default=50,
            help="Number of members to create (default: 50).",
        )

    def handle(self, *args, **options):
        count = max(1, int(options["count"]))
        random.seed()

        role, _ = Role.objects.get_or_create(
            slug="member",
            defaults={"name": "Member", "sort_order": 100, "is_active": True},
        )
        member_type, _ = MemberType.objects.get_or_create(
            name="Regular Member",
            defaults={"description": "Auto-generated test member type"},
        )

        created_members = 0
        created_transactions = 0

        for idx in range(1, count + 1):
            unique = uuid.uuid4().hex[:8]
            member = Member.objects.create(
                username=f"topmember_{idx}_{unique}",
                rfid_card_number=f"TM{idx:04d}{random.randint(1000, 9999)}",
                first_name=f"Top{idx}",
                last_name=f"Member{idx}",
                email=f"topmember{idx}_{unique}@example.com",
                phone=f"09{random.randint(10, 99)}{random.randint(1000000, 9999999)}",
                member_type=member_type,
                member_role=role,
                balance=Decimal(str(round(random.uniform(500, 10000), 2))),
            )
            member.set_pin(f"{random.randint(0, 9999):04d}")
            created_members += 1

            tx_count = random.randint(2, 8)
            for tx_index in range(tx_count):
                total_amount = Decimal(str(round(random.uniform(80, 2500), 2)))
                transaction_number = f"DUMMY-TOP-{idx:03d}-{tx_index:02d}-{uuid.uuid4().hex[:6].upper()}"
                Transaction.objects.create(
                    transaction_number=transaction_number,
                    member=member,
                    subtotal=total_amount,
                    vatable_sale=total_amount,
                    vat_amount=Decimal("0.00"),
                    total_amount=total_amount,
                    payment_method=random.choice(["debit", "cash"]),
                    amount_paid=total_amount,
                    amount_from_balance=total_amount if random.choice([True, False]) else Decimal("0.00"),
                    status="completed",
                    notes="Auto-generated top member dummy transaction",
                )
                created_transactions += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Created {created_members} members and {created_transactions} completed transactions."
            )
        )
