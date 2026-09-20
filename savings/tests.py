from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from django.utils import timezone

from savings.policy import (
    ANNUAL_INTEREST_RATE,
    BASE_INTEREST_RATE,
    LOYALTY_INTEREST_RATE,
    add_calendar_years,
    format_rate,
    interest_amount,
    next_interest_credit_on,
)
from savings import services


class SavingsInterestPolicyTests(SimpleTestCase):
    def test_format_rate(self):
        self.assertEqual(format_rate(ANNUAL_INTEREST_RATE), "5%")
        self.assertEqual(format_rate(BASE_INTEREST_RATE), "5%")
        self.assertEqual(format_rate(LOYALTY_INTEREST_RATE), "5%")

    def test_interest_amount_is_monthly(self):
        # (5000 * 0.05) / 12 = 20.83
        self.assertEqual(
            interest_amount(Decimal("5000.00"), ANNUAL_INTEREST_RATE),
            Decimal("20.83"),
        )
        self.assertEqual(
            interest_amount(Decimal("10000.00"), ANNUAL_INTEREST_RATE),
            Decimal("41.67"),
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

    def test_months_due_counts_anniversaries_after_opening(self):
        opened = timezone.make_aware(datetime(2026, 1, 19, 12, 0, 0))
        account = SimpleNamespace(pk=1, opened_at=opened, can_transact=True, balance=Decimal("5000"))
        as_of = timezone.make_aware(datetime(2026, 8, 26, 12, 0, 0))
        with patch.object(services, "last_interest_at", return_value=None):
            # Feb 19 .. Aug 19 2026 = 7 months
            self.assertEqual(services.months_of_interest_due(account, as_of=as_of), 7)
        as_of_feb = timezone.make_aware(datetime(2026, 2, 10, 12, 0, 0))
        with patch.object(services, "last_interest_at", return_value=None):
            self.assertEqual(services.months_of_interest_due(account, as_of=as_of_feb), 0)


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
