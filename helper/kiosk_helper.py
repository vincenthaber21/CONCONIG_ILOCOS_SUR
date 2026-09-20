"""
kiosk_helper.py
===============
Helper utilities for the Cooperative Kiosk system.

Covers:
  - Transaction number generation
  - Product fee / debit transfer fee processing
  - Stock validation helpers
  - Session management helpers
  - Member authentication helpers
  - Receipt text/HTML formatting
  - Local printer utilities
  - Change / totals calculation

Usage (inside kiosk/views.py or any app):
    from helper.kiosk_helper import (
        generate_transaction_number,
        validate_cart_items,
        authenticate_member_for_debit,
        build_member_summary,
        calculate_change,
        format_receipt_text,
        send_to_local_printer,
        set_kiosk_session,
        clear_kiosk_session,
        persist_member_session,
    )
"""

from __future__ import annotations

import logging
import random
import string
import threading
import time
from decimal import Decimal, ROUND_HALF_UP
from typing import TYPE_CHECKING, Optional

from django.conf import settings
from django.utils import timezone

if TYPE_CHECKING:
    # Avoid circular imports at runtime; these are only used for type hints.
    from django.http import HttpRequest
    from inventory.models import Product
    from members.models import Member
    from transactions.models import Transaction

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CENTS: Decimal = Decimal("0.01")
MAX_QUANTITY: int = 1_000_000_000


# ---------------------------------------------------------------------------
# Transaction number
# ---------------------------------------------------------------------------


def generate_transaction_number() -> str:
    """Return a unique transaction number: ``TXN<YYYYMMDDHHmmSS><4 random digits>``."""
    timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
    random_suffix = "".join(random.choices(string.digits, k=4))
    return f"TXN{timestamp}{random_suffix}"


# ---------------------------------------------------------------------------
# Money helpers
# ---------------------------------------------------------------------------


def to_decimal(value) -> Decimal:
    """Safely coerce *value* to a ``Decimal`` rounded to 2 decimal places."""
    return Decimal(str(value)).quantize(CENTS, rounding=ROUND_HALF_UP)


def calculate_change(total_amount: Decimal, amount_paid: Decimal) -> Decimal:
    """Return the change due (≥ 0).  Returns ``0.00`` if *amount_paid* < *total_amount*."""
    change = amount_paid - total_amount
    return max(to_decimal(change), Decimal("0.00"))


# ---------------------------------------------------------------------------
# Cart / stock validation
# ---------------------------------------------------------------------------


def validate_cart_items(items: list[dict]) -> tuple[bool, str, list[dict]]:
    """
    Validate raw cart item dicts from the request body.

    Each item must have ``product_id`` and ``quantity`` (positive number ≤ MAX_QUANTITY).
    Optional: ``sale_unit_id``, ``units_per_package``, ``barcode``.

    Returns
    -------
    (is_valid, error_message, cleaned_items)
        *cleaned_items* has ``quantity`` coerced to ``Decimal``.
    """
    if not items:
        return False, "No items in cart", []

    cleaned: list[dict] = []
    for item in items:
        if "product_id" not in item or "quantity" not in item:
            return False, "Invalid item data: missing product_id or quantity", []
        try:
            qty = Decimal(str(item["quantity"]))
        except (ValueError, TypeError, Exception):
            return False, "Invalid quantity value", []
        if qty <= 0:
            return False, "Quantity must be a positive number", []
        if qty > MAX_QUANTITY:
            return False, f"Quantity exceeds maximum allowed ({MAX_QUANTITY})", []
        row = {**item, "quantity": qty}
        if item.get("sale_unit_id") not in (None, ""):
            try:
                row["sale_unit_id"] = int(item["sale_unit_id"])
            except (ValueError, TypeError):
                return False, "Invalid sale_unit_id", []
        if item.get("units_per_package") not in (None, ""):
            try:
                row["units_per_package"] = max(1, int(item["units_per_package"]))
            except (ValueError, TypeError):
                return False, "Invalid units_per_package", []
        cleaned.append(row)

    return True, "", cleaned


def check_stock_availability(
    product_map: dict[int, "Product"],
    items: list[dict],
) -> tuple[bool, str]:
    """
    Verify that every item in *items* has sufficient stock in *product_map*.

    Stock is tracked in base pieces; wholesale lines consume quantity × units_per_package.
    """
    from inventory.sale_units import aggregate_cart_stock_pieces

    demand = aggregate_cart_stock_pieces(items)
    for pid, needed_pieces in demand.items():
        product = product_map.get(pid)
        if not product:
            return False, f"Product ID {pid} not found or inactive"
        if product.stock_quantity < needed_pieces:
            return False, f"Insufficient stock for {product.name}"
    return True, ""


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------


def set_kiosk_session(request: "HttpRequest", member: "Member") -> None:
    """Store the RFID-scanned member in the kiosk session keys."""
    request.session["kiosk_member_id"] = member.id
    request.session["kiosk_member_rfid"] = member.rfid_card_number


def clear_kiosk_session(request: "HttpRequest") -> None:
    """Remove temporary kiosk session keys after a transaction completes."""
    request.session.pop("kiosk_member_id", None)
    request.session.pop("kiosk_member_rfid", None)


def persist_member_session(request: "HttpRequest", member: "Member") -> None:
    """
    After a successful debit payment, persist a longer-lived member session
    so the receipt popup can validate access.
    """
    request.session["member_id"] = member.id
    request.session["member_rfid"] = member.rfid_card_number
    request.session["member_role"] = member.role


def get_kiosk_session_member_id(request: "HttpRequest") -> Optional[int]:
    """Return the ``kiosk_member_id`` stored in the session, or ``None``."""
    return request.session.get("kiosk_member_id")


def get_kiosk_session_member_rfid(request: "HttpRequest") -> Optional[str]:
    """Return the ``kiosk_member_rfid`` stored in the session, or ``None``."""
    return request.session.get("kiosk_member_rfid")


# ---------------------------------------------------------------------------
# Member authentication for debit payment
# ---------------------------------------------------------------------------


def authenticate_member_for_debit(
    request: "HttpRequest",
    member: "Member",
    pin: Optional[str],
) -> tuple[bool, str]:
    """
    Validate that *member* is authorised to make a debit payment.

    Authentication flow
    -------------------
    1. If a kiosk RFID session exists, verify it belongs to *member*.
       - Non-cashier / non-admin members also need a valid PIN.
       - If the session belongs to a privileged operator (admin/cashier/staff)
         and the customer being charged is a different member, fall through to
         PIN-only authentication for the customer.
    2. If no RFID session exists, fall back to PIN-only authentication.
       - Cashiers and admins may skip PIN.

    Returns ``(True, "")`` on success, or ``(False, <reason>)`` on failure.
    """
    from members.models import Member

    session_member_id = get_kiosk_session_member_id(request)
    session_member_rfid = get_kiosk_session_member_rfid(request)
    is_privileged = member.role in ("cashier", "admin", "staff")

    if session_member_id and session_member_rfid:
        # --- RFID path ---
        if session_member_id != member.id:
            session_member = (
                Member.objects.select_related("member_role")
                .only("id", "member_role_id")
                .filter(id=session_member_id, is_active=True)
                .first()
            )
            session_is_privileged = bool(
                session_member and session_member.role in ("admin", "cashier", "staff")
            )
            if not session_is_privileged:
                return (
                    False,
                    "RFID card does not match the member account. "
                    "Please scan the correct RFID card for this account.",
                )
            # Privileged operator paying for a different customer:
            # the customer's PIN authorises the debit.
            if not is_privileged:
                if not pin:
                    return (
                        False,
                        "PIN is required for member payments. "
                        "Please enter your PIN to proceed with debit payment.",
                    )
                if not member.check_pin(pin):
                    return False, "Invalid PIN"
            return True, ""
        if session_member_rfid != member.rfid_card_number:
            return (
                False,
                "RFID card does not belong to this member account. "
                "Debit payment declined.",
            )
        # RFID ok; non-privileged members also need PIN; admin/cashier/staff skip PIN
        if not is_privileged:
            if not pin:
                return False, "PIN is required for member payments"
            if not member.check_pin(pin):
                return False, "Invalid PIN"
    else:
        # --- PIN-only fallback ---
        if not is_privileged:
            if not pin:
                return (
                    False,
                    "PIN is required for member payments. "
                    "Please enter your PIN to proceed with debit payment.",
                )
            if not member.check_pin(pin):
                return False, "Invalid PIN"
        # Privileged roles (admin/cashier/staff) can proceed; record session for consistency
        set_kiosk_session(request, member)

    return True, ""


# ---------------------------------------------------------------------------
# Member summary dict
# ---------------------------------------------------------------------------


def get_member_credit_outstanding(member: "Member") -> Decimal:
    """Sum of unsettled line items on completed credit (utang) sales."""
    from helper.credit_settlement_helper import member_credit_outstanding_amount

    return to_decimal(member_credit_outstanding_amount(member))


CREDIT_LIMIT_FEATURE_ENABLED = False


def get_member_max_credit_limit() -> Decimal:
    """Store-wide cap on outstanding credit per member (0 = unlimited)."""
    if not CREDIT_LIMIT_FEATURE_ENABLED:
        return Decimal("0.00")
    from admin_panel.models import KioskConfig

    return to_decimal(KioskConfig.get().member_max_credit)


def get_member_credit_available(member: "Member") -> Decimal | None:
    """
    Remaining credit room before hitting the kiosk limit.
    Returns None when member_max_credit is 0 (unlimited).
    """
    limit = get_member_max_credit_limit()
    if limit <= 0:
        return None
    outstanding = get_member_credit_outstanding(member)
    remaining = limit - outstanding
    return remaining if remaining > 0 else Decimal("0.00")


def member_credit_limit_exceeded(member: "Member", additional_amount: Decimal) -> tuple[bool, str]:
    """
    True when *additional_amount* would push outstanding credit over the kiosk limit.
    """
    limit = get_member_max_credit_limit()
    if limit <= 0:
        return False, ""
    outstanding = get_member_credit_outstanding(member)
    additional_amount = to_decimal(additional_amount)
    if outstanding + additional_amount <= limit:
        return False, ""
    available = get_member_credit_available(member)
    return (
        True,
        (
            f"Credit limit exceeded. Maximum allowed: ₱{limit}, "
            f"current outstanding: ₱{outstanding}, "
            f"available for this purchase: ₱{available}"
        ),
    )


def member_credit_fields(member: "Member") -> dict:
    """JSON-serialisable credit limit fields for kiosk member payloads."""
    outstanding = get_member_credit_outstanding(member)
    limit = get_member_max_credit_limit()
    available = get_member_credit_available(member)
    payload = {
        "credit": str(outstanding),
        "credit_outstanding": str(outstanding),
        "member_max_credit": str(limit),
    }
    if available is None:
        payload["credit_available"] = None
        payload["credit_limit_enabled"] = False
    else:
        payload["credit_available"] = str(available)
        payload["credit_limit_enabled"] = True
    return payload


def build_member_summary(
    member: "Member",
    balance_before: Optional[Decimal] = None,
) -> dict:
    """
    Return a JSON-serialisable dict representing *member*'s post-transaction state.

    *balance_before* is included in the summary when supplied so the receipt
    can display the change in balance.
    """
    current_balance = to_decimal(member.balance)
    summary = {
        "id": member.id,
        "name": member.full_name,
        "balance": str(current_balance),
        "available_balance": str(getattr(member, "available_balance", current_balance)),
        "balance_before": str(balance_before) if balance_before is not None else str(current_balance),
        "balance_after": str(current_balance),
    }
    summary.update(member_credit_fields(member))
    return summary


# ---------------------------------------------------------------------------
# Receipt text formatter
# ---------------------------------------------------------------------------


def format_receipt_text(transaction: "Transaction", change_amount: Decimal = Decimal("0.00")) -> str:
    """
    Build a plain-text receipt string suitable for thermal / ESC-POS printers.

    The width is 42 characters (standard 80 mm roll).
    """
    WIDTH = 42
    SEP = "-" * WIDTH
    DOUBLE_SEP = "=" * WIDTH

    def centre(text: str) -> str:
        return text.center(WIDTH)

    def line_lr(left: str, right: str) -> str:
        gap = WIDTH - len(left) - len(right)
        return f"{left}{' ' * max(gap, 1)}{right}"

    now = timezone.now().strftime("%Y-%m-%d %H:%M:%S")

    lines: list[str] = [
        centre("*** RECEIPT ***"),
        centre(getattr(settings, "COOP_NAME", "Cooperative Kiosk")),
        centre(getattr(settings, "COOP_ADDRESS", "")),
        SEP,
        line_lr("Transaction #:", transaction.transaction_number),
        line_lr("Date/Time:", now),
        line_lr("Payment:", transaction.payment_method.upper()),
        SEP,
        "ITEMS",
        SEP,
    ]

    for item in transaction.items.all():
        lines.append(f"  {item.product_name}")
        lines.append(
            line_lr(
                f"    {item.quantity_display} x ₱{item.unit_price}",
                f"₱{item.total_price}",
            )
        )

    lines += [
        SEP,
        line_lr("Subtotal:", f"₱{transaction.subtotal}"),
        DOUBLE_SEP,
        line_lr("TOTAL:", f"₱{transaction.total_amount}"),
    ]

    if transaction.payment_method == "cash":
        lines.append(line_lr("Cash Received:", f"₱{transaction.amount_paid}"))
        lines.append(line_lr("Change:", f"₱{change_amount}"))
    elif transaction.payment_method == "credit":
        lines.append(line_lr("Credit Amount:", f"₱{transaction.total_amount}"))

    if transaction.member:
        m = transaction.member
        lines += [
            SEP,
            line_lr("Member:", m.full_name),
            line_lr("Balance After:", f"₱{m.balance}"),
        ]

    lines += [
        DOUBLE_SEP,
        centre("Thank you for your purchase!"),
        centre(getattr(settings, "COOP_FOOTER", "")),
        "",
        "",
    ]

    return "\r\n".join(lines)


# ---------------------------------------------------------------------------
# Local printer
# ---------------------------------------------------------------------------


def _cleanup_temp_file(path: str, delay: int = 5) -> None:
    """Delete *path* after *delay* seconds in a daemon thread."""

    def _rm():
        time.sleep(delay)
        import os

        try:
            os.unlink(path)
        except OSError:
            pass

    threading.Thread(target=_rm, daemon=True).start()


def send_to_local_printer(text: str = "", html: str = "") -> tuple[bool, str]:
    """
    Send a receipt to the local Windows default printer.

    Tries, in order:
    1. ``os.startfile(tmp_html, 'print')`` when *html* is supplied.
    2. Raw ``win32print`` with *text*.

    Returns ``(success, message)``.
    """
    # --- HTML path ---
    if html:
        try:
            import os
            import tempfile

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".html", delete=False, encoding="utf-8"
            ) as fh:
                fh.write(html)
                tmp_path = fh.name

            try:
                os.startfile(tmp_path, "print")
                _cleanup_temp_file(tmp_path)
                return True, "Receipt sent to printer using HTML template"
            except Exception as html_exc:
                logger.warning("os.startfile print failed: %s", html_exc)
                _cleanup_temp_file(tmp_path)
                # Fall through to raw text
        except Exception as exc:
            logger.warning("HTML printer path failed: %s", exc)

    # --- Raw text path ---
    if not text:
        return False, "No content available for printing"

    try:
        import win32print  # type: ignore[import]
    except ImportError:
        return (
            False,
            "Printing module not available. Install pywin32: pip install pywin32",
        )

    try:
        printer_name = win32print.GetDefaultPrinter()
    except Exception as exc:
        return False, f"No default printer found: {exc}"

    if not printer_name:
        return False, "No default printer configured in Windows."

    try:
        hPrinter = win32print.OpenPrinter(printer_name)
        try:
            job_id = win32print.StartDocPrinter(hPrinter, 1, ("KioskReceipt", None, "RAW"))
            try:
                win32print.StartPagePrinter(hPrinter)
                print_text = text if text.endswith("\r\n") else text + "\r\n\r\n"
                win32print.WritePrinter(hPrinter, print_text.encode("utf-8"))
                win32print.EndPagePrinter(hPrinter)
            except Exception:
                try:
                    win32print.AbortPrinter(hPrinter)
                except Exception:
                    pass
                raise
            finally:
                win32print.EndDocPrinter(hPrinter)
        finally:
            win32print.ClosePrinter(hPrinter)

        return True, f"Receipt sent to printer: {printer_name}"

    except Exception as exc:
        msg = str(exc)
        if "access" in msg.lower():
            return False, "Access denied to printer. Check permissions or run as administrator."
        if "not found" in msg.lower() and "printer" in msg.lower():
            return False, "Printer not found. Ensure it is connected and set as default."
        return False, f"Printing failed: {msg}"


# ---------------------------------------------------------------------------
# HTML → plain text extractor (mirrors the logic in print_receipt_local)
# ---------------------------------------------------------------------------


def extract_text_from_receipt_html(html: str) -> str:
    """
    Extract readable plain text from a receipt HTML string.

    Targets the ``receiptPaper`` element first; falls back to ``<body>``.
    Returns an empty string if extraction yields less than 50 characters.
    """
    import re
    from html.parser import HTMLParser

    # Try to isolate the receipt paper element
    receipt_html = html
    for pattern in (
        r'<div[^>]*(?:id|class)=["\'][^"\']*receiptPaper[^"\']*["\'][^>]*>(.*?)</div>\s*(?:</div>|</body>)',
        r'<body[^>]*>(.*?)</body>',
    ):
        m = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
        if m:
            receipt_html = m.group(1)
            break

    class _Extractor(HTMLParser):
        def __init__(self):
            super().__init__()
            self.lines: list[str] = []
            self._parts: list[str] = []

        def _flush(self):
            if self._parts:
                self.lines.append(" ".join(self._parts))
                self._parts = []

        def handle_data(self, data):
            d = data.strip()
            if d:
                self._parts.append(d)

        def handle_starttag(self, tag, attrs):
            attrs_dict = dict(attrs)
            cls = attrs_dict.get("class", "")
            if "rp-section-title" in cls or tag == "br":
                self._flush()

        def handle_endtag(self, tag):
            if tag in ("div", "li", "p", "ul"):
                self._flush()

        def get_text(self) -> str:
            self._flush()
            return "\r\n".join(ln.strip() for ln in self.lines if ln.strip())

    parser = _Extractor()
    parser.feed(receipt_html)
    result = parser.get_text()
    return result if len(result) >= 50 else ""


# ---------------------------------------------------------------------------
# Convenience: full post-transaction cleanup
# ---------------------------------------------------------------------------


def finalise_transaction(
    request: "HttpRequest",
    transaction: "Transaction",
    member: Optional["Member"],
    items: list[dict],
    payment_method: str,
) -> None:
    """
    Run all post-payment side-effects in the correct order:

    1. Update ``member.last_transaction`` timestamp.
    2. Persist / clear session keys.

    This does **not** save the transaction itself – the caller must call
    ``transaction.save()`` before invoking this helper.
    """
    if member:
        member.last_transaction = timezone.now()
        member.save()

    if payment_method == "debit":
        if member:
            persist_member_session(request, member)

    clear_kiosk_session(request)