"""Seed transaction-ledger rows for dummy savings accounts (load testing)."""

from datetime import timedelta
from decimal import Decimal
import random
import secrets
import uuid

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from savings.models import MemberSavingsAccount, SavingsTransaction


class Command(BaseCommand):
    help = (
        "Add dummy ledger movements to savings accounts so the "
        "'Latest movements' section can be load-tested."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--per-account",
            type=int,
            default=25,
            help="Target movements per account (default: 25).",
        )
        parser.add_argument(
            "--min-per-account",
            type=int,
            default=12,
            help="Minimum movements per account (default: 12).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Max accounts to seed (0 = all matching dummy accounts).",
        )
        parser.add_argument(
            "--prefix",
            type=str,
            default="SAVDUMMY",
            help="Account-number prefix for dummy accounts (default: SAVDUMMY).",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=2000,
            help="bulk_create batch size (default: 2000).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-seed accounts that already have ledger rows "
            "(deletes existing dummy ledger rows for those accounts first).",
        )

    def handle(self, *args, **options):
        per_account = max(5, int(options["per_account"]))
        min_per = max(3, min(int(options["min_per_account"]), per_account))
        limit = max(0, int(options["limit"]))
        prefix = (options["prefix"] or "SAVDUMMY").strip().upper()
        batch_size = max(200, int(options["batch_size"]))
        force = bool(options["force"])
        random.seed()

        qs = (
            MemberSavingsAccount.objects.filter(account_number__startswith=f"{prefix}-")
            .annotate(txn_count=Count("transactions"))
            .order_by("opened_at")
        )
        if not force:
            qs = qs.filter(txn_count=0)
        if limit:
            qs = qs[:limit]

        accounts = list(qs)
        if not accounts:
            self.stdout.write(
                self.style.WARNING(
                    "No matching dummy accounts to seed "
                    f"(prefix={prefix}-, force={force})."
                )
            )
            return

        if force:
            deleted, _ = SavingsTransaction.objects.filter(
                account_id__in=[a.pk for a in accounts],
                notes__startswith="[dummy ledger]",
            ).delete()
            self.stdout.write(f"Removed {deleted} existing dummy ledger rows.")

        now = timezone.now()
        txn_buffer = []
        created = 0
        account_updates = []
        used_refs = set(
            SavingsTransaction.objects.filter(
                reference__startswith="SVD"
            ).values_list("reference", flat=True)
        )

        def next_ref():
            for _ in range(20):
                candidate = f"SVD{secrets.token_hex(7).upper()}"
                if candidate not in used_refs:
                    used_refs.add(candidate)
                    return candidate
            return f"SVD{uuid.uuid4().hex[:14].upper()}"

        Txn = SavingsTransaction.TxnType

        for i, account in enumerate(accounts, start=1):
            n = random.randint(min_per, per_account)
            opened = account.opened_at or (now - timedelta(days=365))
            if timezone.is_naive(opened):
                opened = timezone.make_aware(opened)

            # Opening deposit
            opening = Decimal(str(round(random.uniform(1000, 8000), 2)))
            balance = Decimal("0.00")
            cursor = opened

            rows = []
            before = balance
            balance = before + opening
            rows.append(
                SavingsTransaction(
                    account_id=account.pk,
                    transaction_type=Txn.OPENING,
                    amount=opening,
                    balance_before=before,
                    balance_after=balance,
                    reference=next_ref(),
                    notes="[dummy ledger] Opening deposit",
                    created_at=cursor,
                    updated_at=cursor,
                )
            )

            for step in range(1, n):
                cursor = cursor + timedelta(
                    days=random.randint(1, 14),
                    hours=random.randint(0, 10),
                    minutes=random.randint(0, 59),
                )
                if cursor > now:
                    cursor = now - timedelta(minutes=random.randint(1, 120))

                roll = random.random()
                if roll < 0.55:
                    txn_type = Txn.DEPOSIT
                    amount = Decimal(str(round(random.uniform(200, 5000), 2)))
                    note = "[dummy ledger] Deposit"
                elif roll < 0.80 and balance > Decimal("500.00"):
                    txn_type = Txn.WITHDRAWAL
                    max_out = min(balance - Decimal("100.00"), Decimal("3000.00"))
                    if max_out <= Decimal("50.00"):
                        txn_type = Txn.DEPOSIT
                        amount = Decimal(str(round(random.uniform(200, 1500), 2)))
                        note = "[dummy ledger] Deposit"
                    else:
                        amount = Decimal(
                            str(round(random.uniform(50, float(max_out)), 2))
                        )
                        note = "[dummy ledger] Withdrawal"
                elif roll < 0.95:
                    txn_type = Txn.INTEREST
                    amount = Decimal(str(round(float(balance) * 0.05 / 12, 2)))
                    if amount < Decimal("0.01"):
                        amount = Decimal("1.00")
                    note = "[dummy ledger] Monthly interest"
                else:
                    txn_type = Txn.ADJUSTMENT
                    amount = Decimal(str(round(random.uniform(10, 200), 2)))
                    note = "[dummy ledger] Adjustment"

                before = balance
                if txn_type in (Txn.WITHDRAWAL, Txn.PENALTY):
                    after = before - amount
                else:
                    after = before + amount
                if after < Decimal("0.00"):
                    continue
                balance = after
                rows.append(
                    SavingsTransaction(
                        account_id=account.pk,
                        transaction_type=txn_type,
                        amount=amount,
                        balance_before=before,
                        balance_after=after,
                        reference=next_ref(),
                        notes=note,
                        created_at=cursor,
                        updated_at=cursor,
                    )
                )

            # Keep account balance in sync with last ledger row
            if account.status == MemberSavingsAccount.Status.CLOSED:
                balance = Decimal("0.00")
            account.balance = balance
            account_updates.append(account)
            txn_buffer.extend(rows)

            if len(txn_buffer) >= batch_size:
                with transaction.atomic():
                    SavingsTransaction.objects.bulk_create(
                        txn_buffer, batch_size=batch_size
                    )
                created += len(txn_buffer)
                txn_buffer.clear()
                self.stdout.write(
                    f"Posted {created} ledger rows "
                    f"({i}/{len(accounts)} accounts)…"
                )

        if txn_buffer:
            with transaction.atomic():
                SavingsTransaction.objects.bulk_create(
                    txn_buffer, batch_size=batch_size
                )
            created += len(txn_buffer)

        # Update balances in batches
        MemberSavingsAccount.objects.bulk_update(
            account_updates, ["balance", "updated_at"], batch_size=500
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {created} ledger movements across {len(accounts)} accounts "
                f"(~{created // max(len(accounts), 1)} per account)."
            )
        )
