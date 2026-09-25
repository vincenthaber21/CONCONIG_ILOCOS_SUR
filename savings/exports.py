"""Excel / PDF exports for savings interest reports."""

from __future__ import annotations

import io
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from html import escape
from pathlib import Path

from django.db.models import Count, Prefetch, Q, Sum
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import models, services


ZERO = Decimal("0.00")


def parse_export_dates(request):
    """Return (date_from, date_to, range_start_aware, range_end_aware)."""
    today = timezone.localdate()
    raw_from = (request.GET.get("date_from") or "").strip()
    raw_to = (request.GET.get("date_to") or "").strip()
    try:
        date_from = date.fromisoformat(raw_from)
    except ValueError:
        date_from = date(today.year, today.month, 1)
    try:
        date_to = date.fromisoformat(raw_to)
    except ValueError:
        date_to = today
    if date_to < date_from:
        date_from, date_to = date_to, date_from

    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(date_from, time.min), tz)
    end = timezone.make_aware(datetime.combine(date_to + timedelta(days=1), time.min), tz)
    return date_from, date_to, start, end


def _store_name():
    try:
        from admin_panel.models import KioskConfig

        cfg = KioskConfig.get()
        if cfg and cfg.system_name:
            return cfg.system_name
    except Exception:
        pass
    return "Cooperative"


def build_interest_report_rows(*, date_from, date_to, range_start, range_end):
    """One row per savings account with interest totals for the selected period."""
    interest_qs = models.SavingsTransaction.objects.filter(
        transaction_type=models.SavingsTransaction.TxnType.INTEREST,
        created_at__gte=range_start,
        created_at__lt=range_end,
    ).order_by("created_at")

    accounts = (
        models.MemberSavingsAccount.objects.select_related("member", "product")
        .prefetch_related(Prefetch("transactions", queryset=interest_qs, to_attr="period_interest"))
        .annotate(
            period_interest_total=Coalesce(
                Sum(
                    "transactions__amount",
                    filter=Q(
                        transactions__transaction_type=models.SavingsTransaction.TxnType.INTEREST,
                        transactions__created_at__gte=range_start,
                        transactions__created_at__lt=range_end,
                    ),
                ),
                ZERO,
            ),
            period_interest_count=Count(
                "transactions",
                filter=Q(
                    transactions__transaction_type=models.SavingsTransaction.TxnType.INTEREST,
                    transactions__created_at__gte=range_start,
                    transactions__created_at__lt=range_end,
                ),
            ),
        )
        .order_by("member__last_name", "member__first_name", "account_number")
    )

    rows = []
    for account in accounts:
        snap = services.interest_snapshot(account)
        rate = snap["annual_rate"]
        rate_display = snap["annual_rate_display"]
        period_total = account.period_interest_total or ZERO
        estimated = snap["estimated_interest"] if account.can_transact else ZERO
        last_in_period = None
        if getattr(account, "period_interest", None):
            last_in_period = account.period_interest[-1].created_at
        rows.append(
            {
                "member": account.member.full_name if account.member_id else "—",
                "username": (
                    (account.member.username or account.member.email or "—")
                    if account.member_id
                    else "—"
                ),
                "account_number": account.account_number,
                "product": account.product.name if account.product_id else "—",
                "status": account.get_status_display(),
                "opened_at": account.opened_at,
                "balance": account.balance or ZERO,
                "annual_rate": rate,
                "annual_rate_display": rate_display,
                "period_interest": period_total,
                "period_interest_count": account.period_interest_count or 0,
                "estimated_monthly": estimated,
                "last_interest_at": snap.get("last_interest_at") or last_in_period,
                "next_credit_on": snap.get("next_credit_on"),
            }
        )
    return rows


def _excel_styles():
    header_fill = PatternFill("solid", fgColor="166534")
    header_font = Font(bold=True, color="FFFFFF")
    thin = Border(
        left=Side(style="thin", color="CBD5E1"),
        right=Side(style="thin", color="CBD5E1"),
        top=Side(style="thin", color="CBD5E1"),
        bottom=Side(style="thin", color="CBD5E1"),
    )
    return header_fill, header_font, thin


def render_interest_excel(*, rows, date_from, date_to, user_label):
    header_fill, header_font, thin = _excel_styles()
    wb = Workbook()
    ws = wb.active
    ws.title = "Interest report"

    store = _store_name()
    total_interest = sum((r["period_interest"] for r in rows), ZERO)
    total_balance = sum((r["balance"] for r in rows), ZERO)
    gen_at = timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M")

    ws["A1"] = f"Savings Interest Report — {store}"
    ws["A1"].font = Font(size=14, bold=True, color="166534")
    ws["A2"] = f"Period: {date_from.isoformat()} to {date_to.isoformat()}"
    ws["A3"] = f"Generated: {gen_at} — {user_label}"
    ws["A4"] = "Annual rate comes from each account's savings product (balance × rate ÷ periods per year)."
    ws["A5"] = (
        f"Accounts: {len(rows)} · "
        f"Total balances (PHP): {float(total_balance):,.2f} · "
        f"Interest credited in period (PHP): {float(total_interest):,.2f}"
    )

    hdr_row = 7
    headers = [
        "#",
        "Member",
        "Username / Email",
        "Account #",
        "Product",
        "Status",
        "Opened",
        "Balance (PHP)",
        "Annual rate",
        "Est. monthly interest (PHP)",
        "Interest credited (period)",
        "Credits (#)",
        "Last interest",
        "Next interest",
    ]
    for col, val in enumerate(headers, start=1):
        cell = ws.cell(row=hdr_row, column=col, value=val)
        cell.fill = header_fill
        cell.font = header_font
        cell.border = thin
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    money_cols = {8, 10, 11}
    for idx, row in enumerate(rows, start=1):
        values = [
            idx,
            row["member"],
            row["username"],
            row["account_number"],
            row["product"],
            row["status"],
            timezone.localtime(row["opened_at"]).strftime("%Y-%m-%d") if row["opened_at"] else "",
            float(row["balance"]),
            row["annual_rate_display"],
            float(row["estimated_monthly"]),
            float(row["period_interest"]),
            row["period_interest_count"],
            (
                timezone.localtime(row["last_interest_at"]).strftime("%Y-%m-%d")
                if row["last_interest_at"]
                else ""
            ),
            (
                timezone.localtime(row["next_credit_on"]).strftime("%Y-%m-%d")
                if row["next_credit_on"]
                else ""
            ),
        ]
        excel_row = hdr_row + idx
        for col, val in enumerate(values, start=1):
            cell = ws.cell(row=excel_row, column=col, value=val)
            cell.border = thin
            if col in money_cols:
                cell.number_format = "#,##0.00"
                cell.alignment = Alignment(horizontal="right")
            elif col in (1, 12):
                cell.alignment = Alignment(horizontal="center")

    total_row = hdr_row + len(rows) + 1
    ws.cell(row=total_row, column=2, value="TOTAL").font = Font(bold=True)
    bal_cell = ws.cell(row=total_row, column=8, value=float(total_balance))
    bal_cell.number_format = "#,##0.00"
    bal_cell.font = Font(bold=True)
    int_cell = ws.cell(row=total_row, column=11, value=float(total_interest))
    int_cell.number_format = "#,##0.00"
    int_cell.font = Font(bold=True)
    for col in range(1, 15):
        ws.cell(row=total_row, column=col).border = thin

    widths = [5, 26, 22, 16, 18, 12, 12, 14, 12, 16, 16, 10, 12, 12]
    for i, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width

    ws.row_dimensions[hdr_row].height = 36

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f"savings_interest_{date_from.isoformat()}_to_{date_to.isoformat()}.xlsx"
    resp = HttpResponse(
        buf.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


def render_interest_pdf(*, rows, date_from, date_to, user_label):
    store = _store_name()
    total_interest = sum((r["period_interest"] for r in rows), ZERO)
    total_balance = sum((r["balance"] for r in rows), ZERO)
    gen_at = timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M")

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "SavingsInterestTitle",
        parent=styles["Heading1"],
        fontSize=14,
        textColor=colors.HexColor("#166534"),
        spaceAfter=6,
        alignment=TA_CENTER,
        fontName="Helvetica-Bold",
    )
    meta_style = ParagraphStyle(
        "SavingsInterestMeta",
        parent=styles["Normal"],
        fontSize=8,
        leading=11,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#475569"),
    )
    cell_style = ParagraphStyle(
        "SavingsInterestCell",
        parent=styles["Normal"],
        fontSize=7,
        leading=9,
    )
    cell_right = ParagraphStyle(
        "SavingsInterestCellRight",
        parent=cell_style,
        alignment=TA_RIGHT,
    )
    cell_center = ParagraphStyle(
        "SavingsInterestCellCenter",
        parent=cell_style,
        alignment=TA_CENTER,
    )

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=28,
        rightMargin=28,
        topMargin=28,
        bottomMargin=28,
    )

    story = [
        Paragraph(f"Savings Interest Report — {store}", title_style),
        Paragraph(
            f"Period: {date_from.isoformat()} to {date_to.isoformat()} · "
            "Rate: each account's savings product · "
            f"Generated: {gen_at} — {user_label}",
            meta_style,
        ),
        Paragraph(
            f"Accounts: {len(rows)} · "
            f"Total balances: ₱{total_balance:,.2f} · "
            f"Interest credited in period: ₱{total_interest:,.2f}",
            meta_style,
        ),
        Spacer(1, 10),
    ]

    header = [
        Paragraph("<b>#</b>", cell_center),
        Paragraph("<b>Member</b>", cell_style),
        Paragraph("<b>Account</b>", cell_style),
        Paragraph("<b>Status</b>", cell_center),
        Paragraph("<b>Opened</b>", cell_center),
        Paragraph("<b>Balance</b>", cell_right),
        Paragraph("<b>Rate</b>", cell_center),
        Paragraph("<b>Est. monthly</b>", cell_right),
        Paragraph("<b>Interest (period)</b>", cell_right),
        Paragraph("<b>Next interest</b>", cell_center),
    ]
    data = [header]
    for idx, row in enumerate(rows, start=1):
        opened = (
            timezone.localtime(row["opened_at"]).strftime("%Y-%m-%d")
            if row["opened_at"]
            else "—"
        )
        next_on = (
            timezone.localtime(row["next_credit_on"]).strftime("%Y-%m-%d")
            if row["next_credit_on"]
            else "—"
        )
        data.append(
            [
                Paragraph(str(idx), cell_center),
                Paragraph(row["member"], cell_style),
                Paragraph(row["account_number"], cell_style),
                Paragraph(row["status"], cell_center),
                Paragraph(opened, cell_center),
                Paragraph(f"{row['balance']:,.2f}", cell_right),
                Paragraph(row["annual_rate_display"], cell_center),
                Paragraph(f"{row['estimated_monthly']:,.2f}", cell_right),
                Paragraph(f"{row['period_interest']:,.2f}", cell_right),
                Paragraph(next_on, cell_center),
            ]
        )

    data.append(
        [
            "",
            Paragraph("<b>TOTAL</b>", cell_style),
            "",
            "",
            "",
            Paragraph(f"<b>{total_balance:,.2f}</b>", cell_right),
            "",
            "",
            Paragraph(f"<b>{total_interest:,.2f}</b>", cell_right),
            "",
        ]
    )

    table = Table(
        data,
        colWidths=[28, 120, 85, 55, 62, 70, 42, 70, 78, 70],
        repeatRows=1,
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#166534")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F1F5F9")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(table)
    doc.build(story)
    buffer.seek(0)
    filename = f"savings_interest_{date_from.isoformat()}_to_{date_to.isoformat()}.pdf"
    resp = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


def _pdf_fonts():
    """Unicode fonts so the passbook can print the peso sign."""
    regular_name = "SavingsPdf"
    bold_name = "SavingsPdf-Bold"
    if regular_name in pdfmetrics.getRegisteredFontNames():
        registered = set(pdfmetrics.getRegisteredFontNames())
        bold = bold_name if bold_name in registered else regular_name
        return regular_name, bold

    candidates = [
        (Path(r"C:\Windows\Fonts\arial.ttf"), Path(r"C:\Windows\Fonts\arialbd.ttf")),
        (Path(r"C:\Windows\Fonts\calibri.ttf"), Path(r"C:\Windows\Fonts\calibrib.ttf")),
        (Path(r"C:\Windows\Fonts\segoeui.ttf"), Path(r"C:\Windows\Fonts\segoeuib.ttf")),
        (Path(r"C:\Windows\Fonts\tahoma.ttf"), Path(r"C:\Windows\Fonts\tahomabd.ttf")),
    ]
    for regular_path, bold_path in candidates:
        if not regular_path.exists():
            continue
        try:
            pdfmetrics.registerFont(TTFont(regular_name, str(regular_path)))
            if bold_path.exists():
                pdfmetrics.registerFont(TTFont(bold_name, str(bold_path)))
                pdfmetrics.registerFontFamily(
                    regular_name,
                    normal=regular_name,
                    bold=bold_name,
                    italic=regular_name,
                    boldItalic=bold_name,
                )
                return regular_name, bold_name
            pdfmetrics.registerFontFamily(
                regular_name,
                normal=regular_name,
                bold=regular_name,
                italic=regular_name,
                boldItalic=regular_name,
            )
            return regular_name, regular_name
        except Exception:
            continue
    return "Helvetica", "Helvetica-Bold"


def _money(amount):
    return f"₱{amount:,.2f}"


def _passbook_particulars(txn):
    lines = [f"<b>{escape(txn.get_transaction_type_display())}</b>"]
    if txn.reference:
        lines.append(escape(txn.reference))
    notes = (txn.notes or "").strip()
    if notes:
        lines.append(escape(notes))
    return "<br/>".join(lines)


def _passbook_teller(txn):
    user = txn.performed_by
    if not user:
        return "—"
    full = (user.get_full_name() or "").strip()
    parts = [part for part in full.split() if part]
    if len(parts) >= 2:
        return "".join(part[0] for part in parts[:3]).upper()
    return (user.username or "—")[:10]


def passbook_pdf_response(account, *, user_label=""):
    """Downloadable savings passbook: every ledger row, oldest first."""
    transactions = list(
        account.transactions.select_related("performed_by").order_by("created_at", "id")
    )
    return render_passbook_pdf(
        account=account,
        transactions=transactions,
        user_label=user_label,
    )


def render_passbook_pdf(*, account, transactions, user_label=""):
    font, font_bold = _pdf_fonts()
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "PassbookTitle",
        parent=styles["Heading1"],
        fontName=font_bold,
        fontSize=15,
        leading=18,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#14532d"),
        spaceAfter=1,
    )
    subtitle_style = ParagraphStyle(
        "PassbookSubtitle",
        parent=styles["Normal"],
        fontName=font,
        fontSize=9,
        leading=12,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#166534"),
    )
    meta_style = ParagraphStyle(
        "PassbookMeta",
        parent=styles["Normal"],
        fontName=font,
        fontSize=8,
        leading=11,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#475569"),
    )
    label_style = ParagraphStyle(
        "PassbookLabel",
        parent=styles["Normal"],
        fontName=font,
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#64748b"),
    )
    value_style = ParagraphStyle(
        "PassbookValue",
        parent=styles["Normal"],
        fontName=font_bold,
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#0f172a"),
    )
    head_style = ParagraphStyle(
        "PassbookHead",
        parent=styles["Normal"],
        fontName=font_bold,
        fontSize=8,
        leading=10,
        textColor=colors.white,
        alignment=TA_CENTER,
    )
    cell_style = ParagraphStyle(
        "PassbookCell",
        parent=styles["Normal"],
        fontName=font,
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#0f172a"),
    )
    cell_right = ParagraphStyle(
        "PassbookCellRight",
        parent=cell_style,
        alignment=TA_RIGHT,
    )
    cell_center = ParagraphStyle(
        "PassbookCellCenter",
        parent=cell_style,
        alignment=TA_CENTER,
    )
    foot_style = ParagraphStyle(
        "PassbookFoot",
        parent=styles["Normal"],
        fontName=font,
        fontSize=8,
        leading=11,
        alignment=TA_LEFT,
        textColor=colors.HexColor("#475569"),
    )

    profile = None
    try:
        from admin_panel.models import StoreProfile

        profile = StoreProfile.get()
    except Exception:
        profile = None
    shop = (getattr(profile, "store_name", None) or "").strip() or _store_name()
    address_parts = []
    if profile:
        for part in (
            profile.address_line1,
            profile.address_line2,
            profile.city,
            profile.province,
            profile.zip_code,
        ):
            text = (part or "").strip()
            if text:
                address_parts.append(text)
    branch = (getattr(profile, "branch_name", None) or "").strip()
    gen_at = timezone.localtime(timezone.now()).strftime("%b %d, %Y %I:%M %p")

    holder = account.holders_display() or account.primary_holder_name or "—"
    if account.walk_in_id:
        member_no = "Walk-in"
    elif account.member_id:
        member_no = (account.member.membership_number or "").strip() or "—"
    else:
        member_no = "—"
    product_name = account.product.name if account.product_id else "—"
    serial = (account.passbook_serial or "").strip() or "—"
    opened = "—"
    if account.opened_at:
        opened = timezone.localtime(account.opened_at).strftime("%b %d, %Y")

    info = [
        [
            Paragraph("Account holder", label_style),
            Paragraph(escape(holder), value_style),
            Paragraph("Account number", label_style),
            Paragraph(escape(account.account_number), value_style),
        ],
        [
            Paragraph("Membership no.", label_style),
            Paragraph(escape(member_no), value_style),
            Paragraph("Passbook serial", label_style),
            Paragraph(escape(serial), value_style),
        ],
        [
            Paragraph("Product", label_style),
            Paragraph(escape(product_name), value_style),
            Paragraph("Status", label_style),
            Paragraph(escape(account.get_status_display()), value_style),
        ],
        [
            Paragraph("Opened", label_style),
            Paragraph(escape(opened), value_style),
            Paragraph("Balance", label_style),
            Paragraph(escape(_money(account.balance or ZERO)), value_style),
        ],
    ]
    info_table = Table(info, colWidths=[90, 175, 90, 176])
    info_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#bbf7d0")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )

    deposits = ZERO
    withdrawals = ZERO
    header = [
        Paragraph("Date", head_style),
        Paragraph("Particulars", head_style),
        Paragraph("Withdrawal", head_style),
        Paragraph("Deposit", head_style),
        Paragraph("Balance", head_style),
        Paragraph("By", head_style),
    ]
    data = [header]
    for txn in transactions:
        when = timezone.localtime(txn.created_at).strftime("%b %d, %Y")
        amount = txn.amount or ZERO
        if txn.is_credit:
            deposits += amount
            debit = ""
            credit = _money(amount)
        else:
            withdrawals += amount
            debit = _money(amount)
            credit = ""
        data.append(
            [
                Paragraph(escape(when), cell_style),
                Paragraph(_passbook_particulars(txn), cell_style),
                Paragraph(escape(debit), cell_right),
                Paragraph(escape(credit), cell_right),
                Paragraph(escape(_money(txn.balance_after or ZERO)), cell_right),
                Paragraph(escape(_passbook_teller(txn)), cell_center),
            ]
        )
    if not transactions:
        data.append(
            [
                Paragraph("—", cell_center),
                Paragraph("No movements on this passbook yet.", cell_style),
                "",
                "",
                Paragraph(escape(_money(account.balance or ZERO)), cell_right),
                "",
            ]
        )

    data.append(
        [
            "",
            Paragraph("<b>TOTAL</b>", cell_style),
            Paragraph(f"<b>{escape(_money(withdrawals))}</b>", cell_right),
            Paragraph(f"<b>{escape(_money(deposits))}</b>", cell_right),
            Paragraph(f"<b>{escape(_money(account.balance or ZERO))}</b>", cell_right),
            "",
        ]
    )

    ledger = Table(
        data,
        colWidths=[72, 167, 78, 78, 86, 50],
        repeatRows=1,
    )
    ledger_style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#166534")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#ecfdf5")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    if len(data) > 2:
        ledger_style.append(
            ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f8fafc")])
        )
    ledger.setStyle(TableStyle(ledger_style))

    story = [
        Paragraph(escape(shop), title_style),
        Paragraph("SAVINGS PASSBOOK", subtitle_style),
        Paragraph("Transaction ledger", subtitle_style),
    ]
    if branch:
        story.append(Paragraph(escape(branch), meta_style))
    if address_parts:
        story.append(Paragraph(escape(", ".join(address_parts)), meta_style))
    story.extend(
        [
            Spacer(1, 8),
            info_table,
            Spacer(1, 10),
            ledger,
            Spacer(1, 10),
            Paragraph(
                "This is a printed copy of the member savings passbook. "
                "Deposits and withdrawals follow the official ledger, oldest first, "
                f"with the balance after each movement. Prepared {escape(gen_at)}"
                + (f" by {escape(user_label)}." if user_label else "."),
                foot_style,
            ),
        ]
    )

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=32,
        rightMargin=32,
        topMargin=28,
        bottomMargin=36,
        title=f"Savings passbook {account.account_number}",
    )

    def _page(canvas, doc_):
        canvas.saveState()
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(32, 18, "Savings passbook")
        canvas.drawRightString(A4[0] - 32, 18, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_page, onLaterPages=_page)
    buffer.seek(0)
    safe_number = "".join(
        ch if ch.isalnum() or ch in "-_" else "-" for ch in (account.account_number or "account")
    )
    filename = f"savings_passbook_{safe_number}.pdf"
    resp = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp
