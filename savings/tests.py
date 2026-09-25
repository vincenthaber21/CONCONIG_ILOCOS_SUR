from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from savings import forms, models
from savings.policy import (
    ANNUAL_INTEREST_RATE,
    BASE_INTEREST_RATE,
    LOYALTY_INTEREST_RATE,
    add_calendar_years,
    earns_savings_interest,
    format_rate,
    interest_amount,
    next_interest_credit_on,
    time_deposit_interest_amount,
)
from savings import services


class SavingsInterestPolicyTests(SimpleTestCase):
    def test_format_rate(self):
        self.assertEqual(format_rate(ANNUAL_INTEREST_RATE), "5%")
        self.assertEqual(format_rate(BASE_INTEREST_RATE), "5%")
        self.assertEqual(format_rate(LOYALTY_INTEREST_RATE), "5%")

    def test_interest_amount_is_savings_times_rate_times_months_over_year(self):
        # 2000 × 0.07 × 3 ÷ 12 = 35.00
        self.assertEqual(
            interest_amount(Decimal("2000.00"), Decimal("0.07"), months=3),
            Decimal("35.00"),
        )
        # 2000 × 0.07 × 12 ÷ 12 = 140.00
        self.assertEqual(
            interest_amount(Decimal("2000.00"), Decimal("0.07"), periods_per_year=1),
            Decimal("140.00"),
        )

    def test_deposit_inside_the_period_stays_out_of_the_interest_base(self):
        # January opening 2,000. February deposit 1,000 inside the 3-month period.
        # Interest still uses 2,000. Balance is still 2,000 + 1,000.
        opening = Decimal("2000.00")
        deposit = Decimal("1000.00")
        self.assertEqual(
            interest_amount(opening, Decimal("0.07"), months=3),
            Decimal("35.00"),
        )
        self.assertEqual(opening + deposit, Decimal("3000.00"))
        first_interest = interest_amount(opening, Decimal("0.07"), months=3)
        new_balance = opening + deposit + first_interest
        self.assertEqual(new_balance, Decimal("3035.00"))
        self.assertEqual(
            interest_amount(new_balance, Decimal("0.07"), months=3),
            Decimal("53.11"),
        )

    def test_add_calendar_years(self):
        now = timezone.now()
        later = add_calendar_years(now, 1)
        self.assertEqual(later.year, now.year + 1)
        self.assertEqual(later.month, now.month)
        self.assertEqual(later.day, now.day)

    def test_next_interest_is_one_month_after_opening(self):
        opened = timezone.make_aware(datetime(2026, 8, 19, 12, 51, 7))
        nxt = next_interest_credit_on(opened)
        self.assertEqual(timezone.localtime(nxt).date(), date(2026, 9, 19))

    def test_next_interest_is_one_month_after_credit(self):
        credited = timezone.make_aware(datetime(2026, 9, 19, 0, 0, 0))
        nxt = next_interest_credit_on(credited)
        self.assertEqual(timezone.localtime(nxt).date(), date(2026, 10, 19))

    def test_next_interest_clamps_end_of_month(self):
        opened = timezone.make_aware(datetime(2026, 1, 31, 10, 0, 0))
        nxt = next_interest_credit_on(opened)
        self.assertEqual(timezone.localtime(nxt).date(), date(2026, 2, 28))

    def test_flat_rate_after_one_year_without_withdrawal(self):
        opened = timezone.now() - timedelta(days=400)
        account = SimpleNamespace(pk=1, opened_at=opened)
        with patch.object(services, "last_withdrawal_at", return_value=None):
            self.assertEqual(
                services.effective_interest_rate(account),
                ANNUAL_INTEREST_RATE,
            )

    def test_flat_rate_when_withdrawn_within_a_year(self):
        opened = timezone.now() - timedelta(days=400)
        withdrawn = timezone.now() - timedelta(days=30)
        account = SimpleNamespace(pk=1, opened_at=opened)
        with patch.object(services, "last_withdrawal_at", return_value=withdrawn):
            self.assertEqual(
                services.effective_interest_rate(account),
                ANNUAL_INTEREST_RATE,
            )

    def test_flat_rate_for_new_account(self):
        account = SimpleNamespace(pk=1, opened_at=timezone.now())
        with patch.object(services, "last_withdrawal_at", return_value=None):
            self.assertEqual(
                services.effective_interest_rate(account),
                ANNUAL_INTEREST_RATE,
            )

    def test_uses_product_interest_rate(self):
        product = SimpleNamespace(interest_rate=Decimal("0.070"), compounding="annually")
        account = SimpleNamespace(pk=1, opened_at=timezone.now(), product=product)
        self.assertEqual(
            services.effective_interest_rate(account),
            Decimal("0.070"),
        )
        step_months, periods, phrase = services.interest_schedule(account)
        self.assertEqual(step_months, 12)
        self.assertEqual(periods, 1)
        self.assertIn("annually", phrase)

    def test_annual_product_is_due_after_one_year(self):
        opened = timezone.make_aware(datetime(2025, 9, 25, 9, 0, 0))
        product = SimpleNamespace(interest_rate=Decimal("0.070"), compounding="annually")
        account = SimpleNamespace(pk=1, opened_at=opened, product=product)
        before = timezone.make_aware(datetime(2026, 9, 24, 12, 0, 0))
        on_anniversary = timezone.make_aware(datetime(2026, 9, 25, 12, 0, 0))
        with (
            patch.object(services, "last_interest_at", return_value=None),
            patch.object(services, "last_withdrawal_at", return_value=None),
        ):
            self.assertEqual(services.months_of_interest_due(account, as_of=before), 0)
            self.assertEqual(
                services.months_of_interest_due(account, as_of=on_anniversary),
                1,
            )
            self.assertEqual(
                interest_amount(Decimal("2000.00"), Decimal("0.070"), periods_per_year=1),
                Decimal("140.00"),
            )

    def test_apply_months_sets_the_credit_interval(self):
        opened = timezone.make_aware(datetime(2026, 1, 25, 9, 0, 0))
        product = SimpleNamespace(
            interest_rate=Decimal("0.070"),
            compounding="annually",
            interest_apply_months=6,
        )
        account = SimpleNamespace(pk=1, opened_at=opened, product=product)
        step, periods, phrase = services.interest_schedule(account)
        self.assertEqual(step, 6)
        self.assertEqual(periods, Decimal("2"))
        self.assertIn("every 6 months", phrase)
        before = timezone.make_aware(datetime(2026, 7, 24, 12, 0, 0))
        on_date = timezone.make_aware(datetime(2026, 7, 25, 12, 0, 0))
        with (
            patch.object(services, "last_interest_at", return_value=None),
            patch.object(services, "last_withdrawal_at", return_value=None),
        ):
            self.assertEqual(services.months_of_interest_due(account, as_of=before), 0)
            self.assertEqual(services.months_of_interest_due(account, as_of=on_date), 1)
        self.assertEqual(
            interest_amount(Decimal("2000.00"), Decimal("0.070"), periods_per_year=periods),
            Decimal("70.00"),
        )

    def test_months_due_counts_anniversaries_after_opening(self):
        opened = timezone.make_aware(datetime(2026, 1, 19, 12, 0, 0))
        account = SimpleNamespace(pk=1, opened_at=opened, can_transact=True, balance=Decimal("5000"))
        as_of = timezone.make_aware(datetime(2026, 8, 26, 12, 0, 0))
        with (
            patch.object(services, "last_interest_at", return_value=None),
            patch.object(services, "last_withdrawal_at", return_value=None),
        ):
            # Feb 19 .. Aug 19 2026 = 7 months
            self.assertEqual(services.months_of_interest_due(account, as_of=as_of), 7)
        as_of_feb = timezone.make_aware(datetime(2026, 2, 10, 12, 0, 0))
        with (
            patch.object(services, "last_interest_at", return_value=None),
            patch.object(services, "last_withdrawal_at", return_value=None),
        ):
            self.assertEqual(services.months_of_interest_due(account, as_of=as_of_feb), 0)

    def test_withdrawal_resets_the_interest_period(self):
        opened = timezone.make_aware(datetime(2026, 1, 15, 9, 0, 0))
        withdrawn = timezone.make_aware(datetime(2026, 3, 15, 9, 0, 0))
        product = SimpleNamespace(interest_rate=Decimal("0.07"), interest_apply_months=3)
        account = SimpleNamespace(pk=1, opened_at=opened, product=product)
        original_due = timezone.make_aware(datetime(2026, 4, 15, 12, 0, 0))
        reset_due = timezone.make_aware(datetime(2026, 6, 15, 12, 0, 0))
        before_reset_due = timezone.make_aware(datetime(2026, 6, 14, 12, 0, 0))
        with (
            patch.object(services, "last_interest_at", return_value=None),
            patch.object(services, "last_withdrawal_at", return_value=withdrawn),
        ):
            self.assertEqual(services.interest_period_started_at(account), withdrawn)
            self.assertEqual(services.months_of_interest_due(account, as_of=original_due), 0)
            self.assertEqual(services.months_of_interest_due(account, as_of=before_reset_due), 0)
            self.assertEqual(services.months_of_interest_due(account, as_of=reset_due), 1)
            nxt = services.next_unpaid_interest_on(account)
            self.assertEqual(timezone.localtime(nxt).date(), date(2026, 6, 15))
        self.assertEqual(
            interest_amount(Decimal("4000.00"), Decimal("0.07"), months=3),
            Decimal("70.00"),
        )
        self.assertFalse(earns_savings_interest(Decimal("1000.00")))
        self.assertFalse(earns_savings_interest(Decimal("500.00")))
        self.assertTrue(earns_savings_interest(Decimal("1000.01")))

    def test_time_deposit_year_interest_is_savings_times_rate(self):
        # 50,000 × 0.02 = 1,000.00 for the year (not × months ÷ 12)
        self.assertEqual(
            time_deposit_interest_amount(Decimal("50000.00"), Decimal("0.02")),
            Decimal("1000.00"),
        )

    def test_time_deposit_interest_only_from_5000_below_1000000(self):
        rate = Decimal("0.02")
        self.assertEqual(time_deposit_interest_amount(Decimal("4999.99"), rate), Decimal("0.00"))
        self.assertEqual(time_deposit_interest_amount(Decimal("5000.00"), rate), Decimal("100.00"))
        self.assertEqual(
            time_deposit_interest_amount(Decimal("999999.99"), rate),
            Decimal("0.00"),
        )
        self.assertEqual(time_deposit_interest_amount(Decimal("1000000.00"), rate), Decimal("0.00"))
        self.assertEqual(
            time_deposit_interest_amount(Decimal("10000000.00"), rate, term_months=12),
            Decimal("300000.00"),
        )

    def test_time_deposit_100001_uses_the_selected_term_rate(self):
        self.assertEqual(
            time_deposit_interest_amount(Decimal("100000.00"), Decimal("0.02")),
            Decimal("2000.00"),
        )
        self.assertEqual(
            time_deposit_interest_amount(Decimal("100001.00"), Decimal("0.02"), term_months=3),
            Decimal("250.00"),
        )
        self.assertEqual(
            time_deposit_interest_amount(Decimal("100001.00"), Decimal("0.02"), term_months=6),
            Decimal("500.01"),
        )
        self.assertEqual(
            time_deposit_interest_amount(Decimal("100001.00"), Decimal("0.02"), term_months=12),
            Decimal("3000.03"),
        )
        self.assertEqual(
            time_deposit_interest_amount(Decimal("100001.00"), Decimal("0.02")),
            Decimal("0.00"),
        )

    def test_product_min_and_max_amount_set_the_interest_band(self):
        product = SimpleNamespace(
            min_amount=Decimal("8000.00"),
            max_amount=Decimal("50000.00"),
        )
        rate = Decimal("0.02")
        self.assertEqual(
            time_deposit_interest_amount(Decimal("7999.99"), rate, product=product),
            Decimal("0.00"),
        )
        self.assertEqual(
            time_deposit_interest_amount(Decimal("8000.00"), rate, product=product),
            Decimal("160.00"),
        )
        self.assertEqual(
            time_deposit_interest_amount(Decimal("50000.00"), rate, product=product),
            Decimal("1000.00"),
        )
        self.assertEqual(
            time_deposit_interest_amount(
                Decimal("50000.01"), rate, term_months=12, product=product
            ),
            Decimal("1500.00"),
        )


class ResolveOpenedAtTests(SimpleTestCase):
    def test_defaults_to_now(self):
        before = timezone.now()
        resolved = services.resolve_opened_at(None)
        after = timezone.now()
        self.assertGreaterEqual(resolved, before)
        self.assertLessEqual(resolved, after)

    def test_today_uses_current_time(self):
        resolved = services.resolve_opened_at(timezone.localdate())
        self.assertEqual(timezone.localtime(resolved).date(), timezone.localdate())

    def test_past_date_keeps_calendar_day(self):
        past = timezone.localdate() - timedelta(days=45)
        resolved = services.resolve_opened_at(past)
        self.assertEqual(timezone.localtime(resolved).date(), past)

    def test_rejects_future_date(self):
        future = timezone.localdate() + timedelta(days=1)
        with self.assertRaises(ValidationError):
            services.resolve_opened_at(future)

    def test_maturity_uses_opening_date(self):
        product = SimpleNamespace(term_months=12)
        opened = timezone.make_aware(datetime(2024, 3, 15, 10, 0, 0))
        self.assertEqual(
            services.compute_maturity_date(product, opened),
            date(2025, 3, 10),
        )


class SavingsProductTimeDepositFormTests(TestCase):
    def _base(self, **overrides):
        data = {
            "name": "Regular Savings",
            "code": "",
            "description": "Passbook",
            "interest_apply_months": "12",
            "is_active": "on",
            "is_time_deposit": "0",
            "interest_rate": "0.070",
            "term_months": "12",
            "min_opening_deposit": "5000.00",
            "max_balance": "0.00",
            "early_withdrawal_penalty_percent": "0",
            "compounding": "annually",
            "allows_withdrawal": "on",
        }
        data.update(overrides)
        return data

    def test_disabled_time_deposit_saves_regular_policy(self):
        form = forms.SavingsProductForm(
            data=self._base(
                name="Walk-in Savings",
                code="walk-in",
                min_opening_deposit="1500.00",
            )
        )
        self.assertTrue(form.is_valid(), form.errors)
        product = form.save()
        self.assertEqual(product.product_type, models.SavingsProduct.ProductType.REGULAR)
        self.assertEqual(product.term_months, 0)
        self.assertEqual(product.min_opening_deposit, Decimal("1500.00"))
        self.assertEqual(product.interest_apply_months, 12)

    def test_regular_save_uses_the_entered_interest_rate(self):
        product = models.SavingsProduct.objects.create(
            name="Regular Savings",
            code="regular-keep-rate",
            product_type=models.SavingsProduct.ProductType.REGULAR,
            interest_rate=Decimal("0.070"),
            interest_apply_months=3,
        )
        form = forms.SavingsProductForm(
            data=self._base(
                name="Regular Savings",
                code="regular-keep-rate",
                is_time_deposit="0",
                interest_rate="0.020",
                interest_apply_months="3",
            ),
            instance=product,
        )
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual(saved.interest_rate, Decimal("0.020"))
        self.assertEqual(saved.interest_apply_months, 3)

    def test_enabled_time_deposit_saves_rate_and_minimum(self):
        form = forms.SavingsProductForm(
            data=self._base(
                name="Time Deposit",
                code="td-12",
                is_time_deposit="1",
                interest_rate="0.020",
                min_opening_deposit="10000.00",
                allows_withdrawal="",
            )
        )
        self.assertTrue(form.is_valid(), form.errors)
        product = form.save()
        self.assertEqual(product.product_type, models.SavingsProduct.ProductType.TIME_DEPOSIT)
        self.assertEqual(product.term_months, 0)
        self.assertEqual(product.interest_rate, Decimal("0.020"))
        self.assertEqual(product.rate_3_months, Decimal("0.010"))
        self.assertEqual(product.rate_6_months, Decimal("0.010"))
        self.assertEqual(product.rate_1_year, Decimal("0.030"))
        self.assertEqual(product.min_opening_deposit, Decimal("10000.00"))
        self.assertEqual(product.max_balance, Decimal("1000000.00"))
        self.assertEqual(product.min_amount, Decimal("10000.00"))
        self.assertEqual(product.max_amount, Decimal("1000000.00"))
        self.assertEqual(product.interest_apply_months, 12)
        self.assertEqual(product.early_withdrawal_penalty_percent, Decimal("0.000"))
        self.assertEqual(product.compounding, models.SavingsProduct.Compounding.ANNUALLY)
        self.assertFalse(product.allows_withdrawal)

    def test_time_deposit_saves_min_and_max_amount(self):
        form = forms.SavingsProductForm(
            data=self._base(
                name="Time Deposit",
                code="td-range",
                is_time_deposit="1",
                min_opening_deposit="8000.00",
                max_balance="250000.00",
            )
        )
        self.assertTrue(form.is_valid(), form.errors)
        product = form.save()
        self.assertEqual(product.min_opening_deposit, Decimal("8000.00"))
        self.assertEqual(product.max_balance, Decimal("250000.00"))
        self.assertEqual(product.min_amount, Decimal("8000.00"))
        self.assertEqual(product.max_amount, Decimal("250000.00"))

    def test_time_deposit_max_amount_must_reach_the_minimum(self):
        form = forms.SavingsProductForm(
            data=self._base(
                name="Time Deposit",
                code="td-range-bad",
                is_time_deposit="1",
                min_opening_deposit="20000.00",
                max_balance="8000.00",
            )
        )
        self.assertFalse(form.is_valid())
        self.assertIn("max_balance", form.errors)

    def test_time_deposit_minimum_is_5000(self):
        form = forms.SavingsProductForm(
            data=self._base(
                name="Time Deposit",
                code="td-min",
                is_time_deposit="1",
                min_opening_deposit="1000.00",
            )
        )
        self.assertFalse(form.is_valid())
        self.assertIn("min_opening_deposit", form.errors)

    def test_disabling_time_deposit_returns_to_regular_policy(self):
        created = forms.SavingsProductForm(
            data=self._base(
                name="Time Deposit",
                code="td-toggle",
                is_time_deposit="1",
                term_months="6",
                interest_rate="0.080",
            )
        )
        self.assertTrue(created.is_valid(), created.errors)
        product = created.save()
        updated = forms.SavingsProductForm(
            data=self._base(name="Time Deposit", code="td-toggle", is_time_deposit="0"),
            instance=product,
        )
        self.assertTrue(updated.is_valid(), updated.errors)
        product = updated.save()
        self.assertEqual(product.product_type, models.SavingsProduct.ProductType.REGULAR)
        self.assertEqual(product.term_months, 0)
        self.assertEqual(product.min_opening_deposit, Decimal("5000.00"))


class DatedMovementTests(TestCase):
    def setUp(self):
        self.product = models.SavingsProduct.objects.create(
            name="Dated Passbook",
            code="dated-move",
            min_opening_deposit=Decimal("100.00"),
            min_maintaining_balance=Decimal("50.00"),
            max_balance=Decimal("10000.00"),
            allows_withdrawal=True,
        )
        self.opened = timezone.localdate() - timedelta(days=60)
        self.account = services.open_account(
            product=self.product,
            opening_amount=Decimal("1000.00"),
            opening_date=self.opened,
            walk_in={"first_name": "Ana", "last_name": "Cruz"},
        )

    def test_backdated_deposit_updates_later_balances(self):
        services.deposit(account=self.account, amount=Decimal("500.00"))
        past = timezone.localdate() - timedelta(days=30)
        services.deposit(
            account=self.account,
            amount=Decimal("200.00"),
            posted_on=past,
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("1700.00"))
        rows = list(
            self.account.transactions.order_by("created_at", "id").values_list(
                "balance_after", flat=True
            )
        )
        self.assertEqual(
            rows,
            [Decimal("1000.00"), Decimal("1200.00"), Decimal("1700.00")],
        )
        end_of_past = timezone.make_aware(
            datetime.combine(past, datetime.max.time().replace(microsecond=0))
        )
        self.assertEqual(services.balance_at(self.account, end_of_past), Decimal("1200.00"))

    def test_backdated_withdrawal_that_overdraws_history_is_rejected(self):
        services.deposit(account=self.account, amount=Decimal("800.00"))
        past = timezone.localdate() - timedelta(days=20)
        with self.assertRaises(ValidationError):
            services.withdraw(
                account=self.account,
                amount=Decimal("1200.00"),
                posted_on=past,
            )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("1800.00"))
        self.assertEqual(self.account.transactions.count(), 2)

    def test_valid_backdated_withdrawal_shifts_later_rows(self):
        services.deposit(account=self.account, amount=Decimal("500.00"))
        past = timezone.localdate() - timedelta(days=15)
        services.withdraw(
            account=self.account,
            amount=Decimal("100.00"),
            posted_on=past,
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("1400.00"))
        rows = list(
            self.account.transactions.order_by("created_at", "id").values_list(
                "transaction_type", "balance_after"
            )
        )
        self.assertEqual(
            rows,
            [
                ("opening", Decimal("1000.00")),
                ("withdrawal", Decimal("900.00")),
                ("deposit", Decimal("1400.00")),
            ],
        )

    def test_form_allows_past_dates_and_rejects_the_future(self):
        future = forms.SavingsMovementForm(
            data={
                "amount": "100.00",
                "transaction_date": (timezone.localdate() + timedelta(days=1)).isoformat(),
            },
            account=self.account,
        )
        self.assertFalse(future.is_valid())
        self.assertIn("transaction_date", future.errors)

        early = forms.SavingsMovementForm(
            data={
                "amount": "100.00",
                "transaction_date": (self.opened - timedelta(days=30)).isoformat(),
            },
            account=self.account,
        )
        self.assertFalse(early.is_valid())
        self.assertIn("transaction_date", early.errors)
        html = str(forms.SavingsMovementForm(account=self.account)["transaction_date"])
        self.assertIn('min="%s"' % self.opened.isoformat(), html)
        self.assertIn('max="%s"' % timezone.localdate().isoformat(), html)

        enrolled = forms.SavingsMovementForm(
            data={
                "amount": "100.00",
                "transaction_date": self.opened.isoformat(),
            },
            account=self.account,
        )
        self.assertTrue(enrolled.is_valid(), enrolled.errors)

        today = forms.SavingsMovementForm(
            data={
                "amount": "100.00",
                "transaction_date": timezone.localdate().isoformat(),
            },
            account=self.account,
        )
        self.assertTrue(today.is_valid(), today.errors)

    def test_deposit_before_enrollment_is_rejected(self):
        past = self.opened - timedelta(days=20)
        with self.assertRaises(ValidationError):
            services.deposit(
                account=self.account,
                amount=Decimal("250.00"),
                posted_on=past,
            )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("1000.00"))

    def test_deposit_on_enrollment_date_stays_on_that_date(self):
        late = timezone.make_aware(datetime.combine(self.opened, datetime.min.time().replace(hour=18)))
        self.account.opened_at = late
        self.account.save(update_fields=["opened_at"])
        opening = self.account.transactions.get(transaction_type="opening")
        opening.created_at = late
        opening.save(update_fields=["created_at"])
        txn = services.deposit(
            account=self.account,
            amount=Decimal("250.00"),
            posted_on=self.opened,
        )
        self.assertEqual(timezone.localtime(txn.created_at).date(), self.opened)
        self.assertGreater(txn.created_at, late)
