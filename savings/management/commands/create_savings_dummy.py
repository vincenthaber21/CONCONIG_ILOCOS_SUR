"""Seed dummy member savings accounts for load / UI testing."""

from datetime import timedelta
from decimal import Decimal
import random
import uuid

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from members.models import Member, MemberType, Role
from savings import models


class Command(BaseCommand):
    help = "Create dummy savings accounts (default 2000) for testing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--count",
            type=int,
            default=2000,
            help="Number of savings accounts to create (default: 2000).",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="bulk_create batch size (default: 500).",
        )
        parser.add_argument(
            "--prefix",
            type=str,
            default="savdummy",
            help="Username / account prefix for dummy rows (default: savdummy).",
        )

    def handle(self, *args, **options):
        count = max(1, int(options["count"]))
        batch_size = max(50, int(options["batch_size"]))
        prefix = (options["prefix"] or "savdummy").strip().lower()
        random.seed()

        role, _ = Role.objects.get_or_create(
            slug="member",
            defaults={"name": "Member", "sort_order": 100, "is_active": True},
        )
        member_type, _ = MemberType.objects.get_or_create(
            name="Regular Member",
            defaults={"description": "Auto-generated test member type"},
        )
        product, _ = models.SavingsProduct.objects.get_or_create(
            code="regular-savings-dummy",
            defaults={
                "name": "Regular Savings",
                "product_type": models.SavingsProduct.ProductType.REGULAR,
                "interest_rate": Decimal("5.000"),
                "min_opening_deposit": Decimal("100.00"),
                "is_active": True,
            },
        )

        stamp = uuid.uuid4().hex[:8]
        existing_usernames = set(
            Member.objects.filter(username__startswith=f"{prefix}_").values_list(
                "username", flat=True
            )
        )
        existing_rfids = set(
            Member.objects.filter(rfid_card_number__startswith="SD").values_list(
                "rfid_card_number", flat=True
            )
        )
        existing_emails = set(
            Member.objects.filter(email__startswith=f"{prefix}_").values_list(
                "email", flat=True
            )
        )
        existing_accounts = set(
            models.MemberSavingsAccount.objects.filter(
                account_number__startswith=f"{prefix.upper()}-"
            ).values_list("account_number", flat=True)
        )

        now = timezone.now()
        status_pool = (
            [models.MemberSavingsAccount.Status.ACTIVE] * 9
            + [models.MemberSavingsAccount.Status.DORMANT]
            + [models.MemberSavingsAccount.Status.CLOSED]
        )

        members_to_create = []
        accounts_to_create = []
        created_members = 0
        created_accounts = 0

        for idx in range(1, count + 1):
            unique = f"{stamp}{idx:05d}"
            username = f"{prefix}_{unique}"
            while username in existing_usernames:
                unique = uuid.uuid4().hex[:10]
                username = f"{prefix}_{unique}"
            existing_usernames.add(username)

            rfid = f"SD{idx:06d}{random.randint(100, 999)}"
            while rfid in existing_rfids:
                rfid = f"SD{random.randint(100000, 999999)}{random.randint(100, 999)}"
            existing_rfids.add(rfid)

            email = f"{prefix}_{unique}@example.com"
            while email in existing_emails:
                email = f"{prefix}_{uuid.uuid4().hex[:10]}@example.com"
            existing_emails.add(email)

            members_to_create.append(
                Member(
                    username=username,
                    rfid_card_number=rfid,
                    first_name=f"Sav{idx}",
                    last_name=f"Dummy{stamp[:4].upper()}",
                    email=email,
                    phone=f"09{random.randint(10, 99)}{random.randint(1000000, 9999999)}",
                    member_type=member_type,
                    member_role=role,
                    balance=Decimal("0.00"),
                )
            )

            account_number = f"{prefix.upper()}-SAV-{idx:06d}-{stamp[:4].upper()}"
            while account_number in existing_accounts:
                account_number = (
                    f"{prefix.upper()}-SAV-{idx:06d}-{uuid.uuid4().hex[:4].upper()}"
                )
            existing_accounts.add(account_number)

            opened_at = now - timedelta(days=random.randint(30, 730))
            status = random.choice(status_pool)
            balance = Decimal(str(round(random.uniform(500, 50000), 2)))
            if status == models.MemberSavingsAccount.Status.CLOSED:
                balance = Decimal("0.00")

            accounts_to_create.append(
                {
                    "account_number": account_number,
                    "balance": balance,
                    "status": status,
                    "opened_at": opened_at,
                    "closed_at": now if status == models.MemberSavingsAccount.Status.CLOSED else None,
                    "notes": "Auto-generated dummy savings account",
                }
            )

        with transaction.atomic():
            for start in range(0, len(members_to_create), batch_size):
                batch = members_to_create[start : start + batch_size]
                Member.objects.bulk_create(batch, batch_size=batch_size)
                created_members += len(batch)
                self.stdout.write(f"Created {created_members}/{count} members…")

            usernames = [m.username for m in members_to_create]
            saved_members = {
                m.username: m
                for m in Member.objects.filter(username__in=usernames)
            }
            account_rows = []
            for member_obj, account_data in zip(members_to_create, accounts_to_create):
                member = saved_members.get(member_obj.username)
                if not member:
                    continue
                account_rows.append(
                    models.MemberSavingsAccount(
                        member=member,
                        product=product,
                        account_number=account_data["account_number"],
                        balance=account_data["balance"],
                        status=account_data["status"],
                        opened_at=account_data["opened_at"],
                        closed_at=account_data["closed_at"],
                        notes=account_data["notes"],
                    )
                )

            for start in range(0, len(account_rows), batch_size):
                batch = account_rows[start : start + batch_size]
                models.MemberSavingsAccount.objects.bulk_create(batch, batch_size=batch_size)
                created_accounts += len(batch)
                self.stdout.write(f"Created {created_accounts}/{count} savings accounts…")

        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {created_members} members and {created_accounts} savings accounts "
                f"(product: {product.name})."
            )
        )
