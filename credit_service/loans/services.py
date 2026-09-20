"""Business logic that doesn't belong on the models themselves.

Kept deliberately framework-light (plain functions) so it's easy to call
from views, management commands, Celery tasks and tests alike.
"""

from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.mail import send_mail
from django.utils import timezone
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

TWO_PLACES = Decimal("0.01")


def generate_amortization_schedule(application):
    """(Re)generate an equal-monthly-amortization schedule for an application.

    Uses the standard amortizing-loan formula:

        A = P * r / (1 - (1 + r) ** -n)

    where P is principal, r is the monthly interest rate, and n is the
    number of installments (term_months). Any existing schedule rows are
    replaced.
    """
    from .models import AmortizationSchedule

    principal = Decimal(application.amount_requested)
    annual_rate = Decimal(application.loan_product.interest_rate) / Decimal("100")
    monthly_rate = annual_rate / Decimal("12")
    n = application.term_months

    application.amortization_schedules.all().delete()

    if n <= 0:
        return []

    if monthly_rate == 0:
        level_payment = (principal / n).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    else:
        factor = (1 - (1 + monthly_rate) ** (-n))
        level_payment = (principal * monthly_rate / factor).quantize(
            TWO_PLACES, rounding=ROUND_HALF_UP
        )

    schedules = []
    balance = principal
    today = timezone.localdate()

    for i in range(1, n + 1):
        interest_due = (balance * monthly_rate).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        principal_due = level_payment - interest_due

        if i == n:
            # Absorb any rounding drift into the final installment.
            principal_due = balance
            total_due = principal_due + interest_due
        else:
            total_due = level_payment

        balance -= principal_due

        due_date = _add_months(today, i)
        schedule = AmortizationSchedule.objects.create(
            application=application,
            installment_number=i,
            due_date=due_date,
            principal_due=principal_due,
            interest_due=interest_due,
            fees_due=Decimal("0"),
            total_due=total_due,
        )
        schedules.append(schedule)

    return schedules


def _add_months(source_date, months):
    month_index = source_date.month - 1 + months
    year = source_date.year + month_index // 12
    month = month_index % 12 + 1
    day = min(source_date.day, _days_in_month(year, month))
    return source_date.replace(year=year, month=month, day=day)


def _days_in_month(year, month):
    if month == 12:
        next_month_first = timezone.datetime(year + 1, 1, 1)
    else:
        next_month_first = timezone.datetime(year, month + 1, 1)
    first_of_month = timezone.datetime(year, month, 1)
    return (next_month_first - first_of_month).days


def record_payment(
    application,
    amount,
    collected_by,
    payment_method,
    or_number="",
    remarks="",
    payment_date=None,
):
    """Record a payment against a loan application.

    Applies the payment to the earliest unpaid amortization installment (or
    marks the lump sum payoff as paid), and transitions the application to
    FULLY_PAID once no balance remains.
    """
    from .models import Payment

    amount = Decimal(amount)
    payment_date = payment_date or timezone.now()

    payment = Payment.objects.create(
        application=application,
        amount_paid=amount,
        payment_date=payment_date,
        collected_by=collected_by,
        payment_method=payment_method,
        or_number=or_number,
        remarks=remarks,
    )

    lump_sum = getattr(application, "lump_sum_payoff", None)
    if lump_sum is not None:
        if amount >= lump_sum.total_amount_due:
            lump_sum.is_paid = True
            lump_sum.save(update_fields=["is_paid"])
    else:
        remaining = amount
        installments = application.amortization_schedules.filter(
            is_paid=False
        ).order_by("installment_number")
        for installment in installments:
            if remaining <= 0:
                break
            if remaining >= installment.total_due:
                remaining -= installment.total_due
                installment.is_paid = True
                installment.save(update_fields=["is_paid"])
                if payment.applied_to_installment_id is None:
                    payment.applied_to_installment = installment
                    payment.save(update_fields=["applied_to_installment"])

    if _is_fully_settled(application):
        if application.status == application.Status.ACTIVE:
            application.mark_fully_paid()
            application.save(update_fields=["status"])

    return payment


def _is_fully_settled(application):
    lump_sum = getattr(application, "lump_sum_payoff", None)
    if lump_sum is not None:
        return lump_sum.is_paid
    return not application.amortization_schedules.filter(is_paid=False).exists() and (
        application.amortization_schedules.exists()
    )


def generate_clearance_certificate(application):
    """Render a simple clearance certificate PDF to MEDIA_ROOT and attach it.

    Returns the relative media path of the generated PDF.
    """
    from .models import LoanSettlement

    buffer_path = (
        Path(settings.MEDIA_ROOT) / "clearance_certificates" / f"{application.id}.pdf"
    )
    buffer_path.parent.mkdir(parents=True, exist_ok=True)

    pdf_canvas = canvas.Canvas(str(buffer_path), pagesize=letter)
    width, height = letter

    pdf_canvas.setFont("Helvetica-Bold", 18)
    pdf_canvas.drawCentredString(width / 2, height - 100, "CERTIFICATE OF LOAN CLEARANCE")

    pdf_canvas.setFont("Helvetica", 12)
    member_name = getattr(application.member, "get_full_name", lambda: str(application.member))()
    lines = [
        f"This certifies that {member_name or application.member} has fully settled",
        f"Loan Application #{application.id} ({application.loan_product.name}) in the",
        f"principal amount of {application.amount_requested}.",
        "",
        f"Date issued: {timezone.localdate().isoformat()}",
    ]
    y = height - 160
    for line in lines:
        pdf_canvas.drawCentredString(width / 2, y, line)
        y -= 24

    pdf_canvas.showPage()
    pdf_canvas.save()

    relative_path = f"clearance_certificates/{application.id}.pdf"

    settlement, _ = LoanSettlement.objects.get_or_create(
        application=application,
        defaults={"closure_date": timezone.now()},
    )
    with open(buffer_path, "rb") as fh:
        settlement.clearance_document.save(
            f"{application.id}.pdf", ContentFile(fh.read()), save=False
        )
    settlement.clearance_issued = True
    settlement.save(update_fields=["clearance_document", "clearance_issued"])

    return relative_path


def notify_applicant_of_disapproval(application):
    """Send an email notification to the applicant and log it.

    Named for the rejection use-case but reused generically as the
    application's notify_applicant() helper for other terminal states too.
    """
    from .models import NotificationLog

    member_email = getattr(application.member, "email", "") or ""
    subject = f"Update on your loan application #{str(application.id)[:8]}"
    message = (
        f"Dear {application.member},\n\n"
        f"Your loan application status is now: {application.get_status_display()}.\n\n"
        "Thank you for banking with your cooperative."
    )

    if member_email:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [member_email],
            fail_silently=True,
        )

    return NotificationLog.objects.create(
        application=application,
        channel="EMAIL",
        message=message,
    )
