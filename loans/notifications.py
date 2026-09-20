"""Member email notifications for loan transparency.

Sends HTML + plain-text mail (async) whenever staff or the member takes an
important action: application received, eligibility, committee decision,
disbursement, repayment, overdue, and closure.
"""

from __future__ import annotations

import html
import logging
from decimal import Decimal

from django.utils import timezone

logger = logging.getLogger(__name__)

# Transient statuses that would double-notify when staff complete a step
# in one click (e.g. SUBMITTED → UNDER_VERIFICATION → UNDER_INVESTIGATION).
SKIP_STATUS_EMAILS = frozenset({"DRAFT", "UNDER_VERIFICATION", "DISBURSED"})


def _coop_name():
    try:
        from admin_panel.models import KioskConfig

        name = (KioskConfig.get().system_name or "").strip()
        if name:
            return name
    except Exception:
        pass
    return "BAGNOS MPC"


def _peso(amount):
    try:
        value = Decimal(amount or 0)
    except Exception:
        value = Decimal("0")
    return f"₱{value:,.2f}"


def _loan_ref(application):
    return str(application.id)[:8].upper()


def _display_name(application):
    from helper.login_helper import get_linked_member

    user = application.member
    member = get_linked_member(user) if user else None
    if member and getattr(member, "full_name", ""):
        return member.full_name
    getter = getattr(user, "get_full_name", None)
    if callable(getter):
        full = (getter() or "").strip()
        if full:
            return full
    return getattr(user, "username", None) or "Member"


def resolve_loan_recipient_email(application):
    """Prefer the Member profile email; fall back to the linked User email."""
    from helper.login_helper import get_linked_member

    user = getattr(application, "member", None)
    member = get_linked_member(user) if user else None
    for candidate in (
        getattr(member, "email", None),
        getattr(user, "email", None),
    ):
        email = (candidate or "").strip()
        if email:
            return email
    return ""


def _html_email(title, greeting_name, intro, rows, note, coop_name):
    row_html = []
    for label, value in rows:
        row_html.append(
            f"""
                <tr>
                  <td style="padding:8px 0;color:#64748b;font-size:14px;">{html.escape(str(label))}</td>
                  <td style="padding:8px 0;color:#0f172a;font-size:14px;font-weight:600;text-align:right;">{html.escape(str(value))}</td>
                </tr>
                <tr><td colspan="2"><hr style="border:none;border-top:1px solid #f1f5f9;margin:0;"/></td></tr>"""
        )
    rows_block = "".join(row_html)
    note_block = ""
    if note:
        note_block = f"""
          <tr>
            <td style="padding:20px 40px 0;">
              <table width="100%" cellpadding="0" cellspacing="0" style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:10px;">
                <tr>
                  <td style="padding:14px 18px;font-size:13px;color:#166534;line-height:1.7;">
                    {html.escape(note)}
                  </td>
                </tr>
              </table>
            </td>
          </tr>"""
    year = timezone.localdate().year
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>{html.escape(title)}</title>
</head>
<body style="margin:0;padding:0;background-color:#f1f5f9;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f1f5f9;padding:40px 0;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">
          <tr>
            <td style="background:linear-gradient(135deg,#C4121A 0%,#ED1C24 60%,#8B0E14 100%);padding:32px 40px;text-align:center;">
              <p style="margin:0;color:rgba(255,255,255,0.85);font-size:12px;letter-spacing:0.16em;text-transform:uppercase;">Loan update</p>
              <h1 style="margin:8px 0 0;color:#ffffff;font-size:22px;font-weight:700;">{html.escape(title)}</h1>
            </td>
          </tr>
          <tr>
            <td style="padding:32px 40px 0;">
              <p style="margin:0;font-size:15px;color:#475569;">Hello, <strong style="color:#0f172a;">{html.escape(greeting_name)}</strong>!</p>
              <p style="margin:10px 0 0;font-size:14px;color:#64748b;line-height:1.7;">{html.escape(intro)}</p>
            </td>
          </tr>
          <tr>
            <td style="padding:24px 40px 0;">
              <table width="100%" cellpadding="0" cellspacing="0" style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:8px 20px;">
                {rows_block}
              </table>
            </td>
          </tr>
          {note_block}
          <tr>
            <td style="padding:32px 40px;text-align:center;border-top:1px solid #f1f5f9;">
              <p style="margin:0;font-size:13px;color:#94a3b8;">This is an automated message from</p>
              <p style="margin:4px 0 0;font-size:14px;font-weight:700;color:#0f172a;">{html.escape(coop_name)}</p>
              <p style="margin:12px 0 0;font-size:12px;color:#94a3b8;">&copy; {year} {html.escape(coop_name)}. Keep this email for your records.</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _plain_email(title, greeting_name, intro, rows, note, coop_name):
    lines = [
        title,
        "=" * 50,
        "",
        f"Dear {greeting_name},",
        "",
        intro,
        "",
    ]
    for label, value in rows:
        lines.append(f"  {label}: {value}")
    if note:
        lines.extend(["", note])
    lines.extend(["", "Thank you,", coop_name])
    return "\n".join(lines)


def _product_name(application):
    product = getattr(application, "loan_product", None)
    return getattr(product, "name", None) or "Loan"


def _status_content(application, target, extra=None):
    extra = extra or {}
    ref = _loan_ref(application)
    product = _product_name(application)
    amount = _peso(application.amount_requested)
    status_label = application.get_status_display()
    base_rows = [
        ("Loan reference", f"#{ref}"),
        ("Product", product),
        ("Amount", amount),
        ("Term", f"{application.term_months} months"),
        ("Status", status_label),
    ]

    mapping = {
        "SUBMITTED": (
            f"We received your loan application #{ref}",
            "Your loan request was submitted. Staff will review your documents and eligibility.",
            "You will receive another email at each important step.",
        ),
        "UNDER_INVESTIGATION": (
            f"Eligibility verified — application #{ref}",
            "Your membership and documents passed verification. Credit investigation is now in progress.",
            "The credit officer will evaluate repayment capacity next.",
        ),
        "VERIFICATION_FAILED": (
            f"Loan application #{ref} did not pass verification",
            "Staff could not verify eligibility or the required documents. Please visit the cooperative office for details.",
            extra.get("remarks") or "You may submit a new request after the issues are resolved.",
        ),
        "PENDING_COMMITTEE_APPROVAL": (
            f"Your loan #{ref} is with the credit committee",
            "Credit investigation is complete. The credit committee will now vote on your application.",
            "You will be emailed as soon as a decision is recorded.",
        ),
        "APPROVED": (
            f"Your loan application #{ref} is approved",
            "The credit committee approved your loan. Staff will proceed with insurance (if required), documentation, and disbursement.",
            "Please be ready to sign the loan agreement.",
        ),
        "REJECTED": (
            f"Update on loan application #{ref}",
            "The credit committee did not approve this loan application.",
            extra.get("remarks") or "Please contact the cooperative office if you have questions.",
        ),
        "INSURANCE_ENROLLED": (
            f"Credit insurance enrolled for loan #{ref}",
            "Credit-life insurance (or the product’s required cover) has been enrolled for this loan.",
            "Documentation and signing is the next step.",
        ),
        "DOCUMENTATION_SIGNED": (
            f"Loan documents signed for #{ref}",
            "The loan agreement has been signed. Funds can now be released.",
            "You will receive another email when the loan is disbursed.",
        ),
        "ACTIVE": (
            f"Loan #{ref} has been disbursed and is now active",
            "Funds have been released. Your loan is now active. Repayment follows the monthly schedule for this loan term.",
            "Keep your official receipts. You will be emailed each time a payment is recorded.",
        ),
        "FULLY_PAID": (
            f"Loan #{ref} is fully paid",
            "All amounts due on this loan have been settled. Thank you for completing your repayment.",
            "Staff may issue a clearance certificate and close the account.",
        ),
        "CLOSED": (
            f"Loan #{ref} is closed",
            "Your loan account is closed. Collateral (if any) has been released and a clearance record has been issued.",
            "Keep this email as confirmation of settlement.",
        ),
    }
    title, intro, note = mapping.get(
        target,
        (
            f"Update on loan application #{ref}",
            f"Your loan application status is now: {status_label}.",
            "Please contact the cooperative office if you have questions.",
        ),
    )

    if target == "ACTIVE":
        disbursement = getattr(application, "disbursement", None)
        if disbursement:
            base_rows.extend(
                [
                    ("Loan principal", _peso(application.amount_requested)),
                    ("Net amount released", _peso(disbursement.amount_released)),
                ]
            )
            if disbursement.transaction_fee and disbursement.transaction_fee > 0:
                base_rows.append(
                    ("Transaction fee", _peso(disbursement.transaction_fee))
                )
            if (
                disbursement.other_deduction_amount
                and disbursement.other_deduction_amount > 0
            ):
                label = disbursement.other_deduction_label or "Other deduction"
                base_rows.append((label, _peso(disbursement.other_deduction_amount)))
            base_rows.append(
                (
                    "Disbursement method",
                    disbursement.get_disbursement_method_display(),
                )
            )
            if disbursement.reference_number:
                base_rows.append(("Reference", disbursement.reference_number))
    return title, intro, base_rows, note


def _event_content(application, event, extra=None):
    extra = extra or {}
    ref = _loan_ref(application)
    product = _product_name(application)

    if event == "payment":
        payment = extra.get("payment")
        outstanding = extra.get("outstanding")
        if outstanding is None:
            outstanding = application.total_outstanding_balance()
        amount = _peso(getattr(payment, "amount_paid", extra.get("amount")))
        or_number = getattr(payment, "or_number", "") or extra.get("or_number") or "—"
        method = ""
        if payment is not None:
            method = payment.get_payment_method_display()
        title = f"Payment received for loan #{ref}"
        intro = "A loan payment has been recorded on your account."
        rows = [
            ("Loan reference", f"#{ref}"),
            ("Product", product),
            ("Loan principal", _peso(application.amount_requested)),
            ("Amount paid", amount),
            ("Official receipt", or_number),
            ("Method", method or "—"),
        ]
        if payment is not None and payment.usable_from and payment.usable_to:
            days = payment.usable_days or (payment.usable_to - payment.usable_from).days
            rows.extend(
                [
                    (
                        "Interest period",
                        f"{payment.usable_from:%b %d, %Y} – {payment.usable_to:%b %d, %Y}",
                    ),
                    ("Usable days", str(days)),
                ]
            )
        if payment is not None and Decimal(str(payment.period_interest or 0)) > 0:
            rows.append(("Period interest", _peso(payment.period_interest)))
        rows.extend(
            [
                ("Outstanding balance", _peso(outstanding)),
                ("Loan status", application.get_status_display()),
            ]
        )
        note = (
            "View or print your official receipt at the cooperative office for full interest "
            "details (daily rate, balance before payment, and breakdown)."
        )
        return title, intro, rows, note

    if event == "payment_option":
        option_label = extra.get("option_label") or "Selected"
        title = f"Repayment plan set for loan #{ref}"
        intro = f"Staff selected your repayment plan: {option_label}."
        rows = [
            ("Loan reference", f"#{ref}"),
            ("Product", product),
            ("Repayment plan", option_label),
            ("Outstanding balance", _peso(application.total_outstanding_balance())),
        ]
        note = "Pay on or before each due date to avoid late-payment interest after the grace period."
        return title, intro, rows, note

    if event == "overdue":
        days = extra.get("days_overdue") or 0
        amount = extra.get("amount_overdue") or 0
        title = f"Overdue loan payment — #{ref}"
        intro = (
            f"Your loan has an overdue balance. Please settle as soon as you can "
            f"to limit late-payment interest."
        )
        rows = [
            ("Loan reference", f"#{ref}"),
            ("Product", product),
            ("Days overdue", str(days)),
            ("Amount overdue", _peso(amount)),
            ("Outstanding balance", _peso(application.total_outstanding_balance())),
        ]
        note = extra.get("note") or "Visit the cooperative office or authorized cashier to pay."
        return title, intro, rows, note

    if event == "payment_reminder":
        title = f"Payment reminder for loan #{ref}"
        intro = "This is a reminder that you have unpaid installments on your loan."
        rows = [
            ("Loan reference", f"#{ref}"),
            ("Product", product),
            ("Outstanding balance", _peso(application.total_outstanding_balance())),
            ("Status", application.get_status_display()),
        ]
        note = "Please pay on or before the due date to avoid late-payment interest."
        return title, intro, rows, note

    return _status_content(application, event, extra)


def notify_loan_member(application, event, extra=None, *, log_audit=True):
    """Send one member email for a loan event. Never raises to callers."""
    from .audit import record_loan_audit
    from .models import LoanApplicationAuditLog, NotificationLog

    extra = extra or {}
    try:
        recipient = resolve_loan_recipient_email(application)
        title, intro, rows, note = _event_content(application, event, extra)
        coop_name = _coop_name()
        name = _display_name(application)
        plain = _plain_email(title, name, intro, rows, note, coop_name)
        html_body = _html_email(title, name, intro, rows, note, coop_name)

        log = NotificationLog.objects.create(
            application=application,
            channel="EMAIL",
            message=plain,
        )

        if recipient:
            from mobile_api.email_utils import send_email_async

            send_email_async(title, plain, recipient, html_body=html_body)
        else:
            logger.info(
                "Loan email skipped (no member email) application=%s event=%s",
                application.pk,
                event,
            )

        if log_audit:
            record_loan_audit(
                application,
                LoanApplicationAuditLog.Action.NOTIFICATION_SENT,
                description=f"Member notified by email: {title}",
                metadata={
                    "event": event,
                    "recipient": recipient or "",
                    "sent": bool(recipient),
                },
            )
        return log
    except Exception:
        logger.exception(
            "Failed to send loan notification application=%s event=%s",
            getattr(application, "pk", "?"),
            event,
        )
        return None


def notify_loan_status_change(application, target_status, extra=None):
    if target_status in SKIP_STATUS_EMAILS:
        return None
    return notify_loan_member(application, target_status, extra=extra)
