"""Generate the GenGlow Self-Checkout System user manual as a PDF."""

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.graphics.shapes import (
    Circle,
    Drawing,
    Group,
    Line,
    Polygon,
    Rect,
    String,
)
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    ListFlowable,
    ListItem,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

OUTPUT_PATH = "GenGlow_User_Manual.pdf"

BRAND_DARK = colors.HexColor("#0f172a")
BRAND_ORANGE = colors.HexColor("#ED1C24")
BRAND_GREEN = colors.HexColor("#ED1C24")  # alias kept for older call sites
BRAND_ACCENT = colors.HexColor("#E6C200")
BRAND_TEAL = colors.HexColor("#E6C200")
BG_LIGHT = colors.HexColor("#f1f5f9")
TEXT_MUTED = colors.HexColor("#475569")
BORDER = colors.HexColor("#cbd5e1")


def build_styles():
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="CoverTitle",
            fontName="Helvetica-Bold",
            fontSize=34,
            leading=40,
            textColor=colors.white,
            alignment=TA_CENTER,
            spaceAfter=18,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CoverSubtitle",
            fontName="Helvetica",
            fontSize=16,
            leading=22,
            textColor=colors.HexColor("#e2e8f0"),
            alignment=TA_CENTER,
            spaceAfter=10,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CoverFooter",
            fontName="Helvetica-Oblique",
            fontSize=11,
            textColor=colors.HexColor("#cbd5e1"),
            alignment=TA_CENTER,
        )
    )
    styles.add(
        ParagraphStyle(
            name="H1",
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=28,
            textColor=BRAND_ACCENT,
            spaceBefore=8,
            spaceAfter=14,
        )
    )
    styles.add(
        ParagraphStyle(
            name="H2",
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=20,
            textColor=BRAND_DARK,
            spaceBefore=12,
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="H3",
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=16,
            textColor=BRAND_GREEN,
            spaceBefore=8,
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Body",
            fontName="Helvetica",
            fontSize=10.5,
            leading=15,
            textColor=BRAND_DARK,
            alignment=TA_JUSTIFY,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="GGBullet",
            fontName="Helvetica",
            fontSize=10.5,
            leading=15,
            textColor=BRAND_DARK,
            leftIndent=14,
            bulletIndent=2,
            spaceAfter=2,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Tip",
            fontName="Helvetica-Oblique",
            fontSize=10,
            leading=14,
            textColor=TEXT_MUTED,
        )
    )
    styles.add(
        ParagraphStyle(
            name="TOCItem",
            fontName="Helvetica",
            fontSize=11.5,
            leading=20,
            textColor=BRAND_DARK,
            leftIndent=0,
        )
    )
    return styles


def cover_page_canvas(canv, doc):
    canv.saveState()
    width, height = A4
    canv.setFillColor(BRAND_DARK)
    canv.rect(0, 0, width, height, stroke=0, fill=1)
    canv.setFillColor(BRAND_GREEN)
    canv.rect(0, height - 6 * cm, width, 6 * cm, stroke=0, fill=1)
    canv.setFillColor(BRAND_TEAL)
    canv.rect(0, height - 6.6 * cm, width, 0.6 * cm, stroke=0, fill=1)
    canv.setFillColor(colors.HexColor("#94a3b8"))
    canv.setFont("Helvetica", 9)
    canv.drawCentredString(width / 2, 1.5 * cm, "Self-Checkout Cooperative Kiosk System")
    canv.restoreState()


def content_page_canvas(canv, doc):
    canv.saveState()
    width, height = A4
    canv.setFillColor(BRAND_GREEN)
    canv.rect(0, height - 1.2 * cm, width, 1.2 * cm, stroke=0, fill=1)
    canv.setFillColor(colors.white)
    canv.setFont("Helvetica-Bold", 10)
    canv.drawString(2 * cm, height - 0.78 * cm, "GenGlow  |  User Manual")
    canv.setFillColor(BRAND_TEAL)
    canv.rect(0, 1.0 * cm, width, 0.15 * cm, stroke=0, fill=1)
    canv.setFillColor(TEXT_MUTED)
    canv.setFont("Helvetica", 9)
    canv.drawCentredString(width / 2, 0.55 * cm, f"Page {doc.page}")
    canv.drawRightString(width - 2 * cm, 0.55 * cm, "v1.0")
    canv.restoreState()


def make_card_table(rows, col_widths=None):
    if col_widths is None:
        col_widths = [4.5 * cm, 12 * cm]
    tbl = Table(rows, colWidths=col_widths, hAlign="LEFT")
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), BG_LIGHT),
                ("TEXTCOLOR", (0, 0), (0, -1), BRAND_ACCENT),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, BORDER),
            ]
        )
    )
    return tbl


def make_steps(items, styles):
    flow = []
    for i, text in enumerate(items, 1):
        flow.append(
            Paragraph(
                f"<b><font color='#ED1C24'>Step {i}.</font></b> {text}",
                styles["Body"],
            )
        )
    return flow


def make_bullets(items, styles):
    return ListFlowable(
        [ListItem(Paragraph(t, styles["Body"]), leftIndent=10) for t in items],
        bulletType="bullet",
        start="circle",
        bulletColor=BRAND_GREEN,
        leftIndent=14,
    )


def info_box(text, styles):
    p = Paragraph(text, styles["Body"])
    tbl = Table([[p]], colWidths=[16.5 * cm])
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FEF7D5")),
                ("BOX", (0, 0), (-1, -1), 0.6, BRAND_GREEN),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    return tbl


def warning_box(text, styles):
    p = Paragraph(text, styles["Body"])
    tbl = Table([[p]], colWidths=[16.5 * cm])
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FEF7D5")),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#c2410c")),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    return tbl


def section_divider():
    tbl = Table([[""]], colWidths=[16.5 * cm], rowHeights=[3])
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), BRAND_GREEN),
            ]
        )
    )
    return tbl


# ---------------------------------------------------------------------------
# UI mockup illustrations — drawn with reportlab primitives, no external files
# ---------------------------------------------------------------------------

MOCK_W = 7.0 * cm
MOCK_H = 5.0 * cm
PHONE_W = 5.0 * cm
PHONE_H = 8.5 * cm

C_BG = colors.HexColor("#f8fafc")
C_PANEL = colors.white
C_PANEL_DARK = colors.HexColor("#0f172a")
C_LINE = colors.HexColor("#cbd5e1")
C_TEXT = colors.HexColor("#334155")
C_MUTED = colors.HexColor("#94a3b8")
C_BRAND = colors.HexColor("#ED1C24")
C_BRAND_LIGHT = colors.HexColor("#FEF7D5")
C_ACCENT = colors.HexColor("#E6C200")
C_DANGER = colors.HexColor("#dc2626")
C_GOLD = colors.HexColor("#f59e0b")


def _window_frame(d, w, h, title="", show_topbar=True):
    """Draw a generic app-window frame with rounded corners and top bar."""
    d.add(Rect(0, 0, w, h, fillColor=C_BG, strokeColor=C_LINE, strokeWidth=0.8, rx=6, ry=6))
    if show_topbar:
        d.add(Rect(0, h - 14, w, 14, fillColor=C_PANEL_DARK, strokeColor=None, rx=6, ry=6))
        d.add(Rect(0, h - 14, w, 7, fillColor=C_PANEL_DARK, strokeColor=None))
        d.add(Circle(8, h - 7, 2, fillColor=C_DANGER, strokeColor=None))
        d.add(Circle(16, h - 7, 2, fillColor=C_GOLD, strokeColor=None))
        d.add(Circle(24, h - 7, 2, fillColor=C_BRAND, strokeColor=None))
        if title:
            d.add(String(w / 2, h - 9, title, fontName="Helvetica-Bold", fontSize=6,
                         fillColor=colors.white, textAnchor="middle"))


def _label(d, x, y, text, size=6, color=C_TEXT, bold=False, anchor="start"):
    d.add(String(x, y, text, fontName="Helvetica-Bold" if bold else "Helvetica",
                 fontSize=size, fillColor=color, textAnchor=anchor))


def _button(d, x, y, w, h, label, fill=C_BRAND, text_color=colors.white, font_size=6):
    d.add(Rect(x, y, w, h, fillColor=fill, strokeColor=None, rx=3, ry=3))
    _label(d, x + w / 2, y + h / 2 - 2, label, size=font_size, color=text_color,
           bold=True, anchor="middle")


def _input(d, x, y, w, h, placeholder=""):
    d.add(Rect(x, y, w, h, fillColor=C_PANEL, strokeColor=C_LINE, strokeWidth=0.5, rx=2, ry=2))
    if placeholder:
        _label(d, x + 4, y + h / 2 - 2, placeholder, size=5, color=C_MUTED)


def _row(d, x, y, w, h, cells):
    """Draw a row with cells (list of (relative_width, text))."""
    d.add(Rect(x, y, w, h, fillColor=C_PANEL, strokeColor=C_LINE, strokeWidth=0.3))
    total = sum(c[0] for c in cells)
    cx = x
    for cw, text in cells:
        cell_w = w * (cw / total)
        _label(d, cx + 4, y + h / 2 - 2, text, size=5, color=C_TEXT)
        cx += cell_w


def mockup_login():
    d = Drawing(MOCK_W, MOCK_H)
    w, h = MOCK_W, MOCK_H
    _window_frame(d, w, h, "GenGlow Admin Panel")
    # centered card
    cx, cy, cw, ch = w * 0.18, h * 0.18, w * 0.64, h * 0.58
    d.add(Rect(cx, cy, cw, ch, fillColor=C_PANEL, strokeColor=C_LINE, rx=4, ry=4))
    _label(d, cx + cw / 2, cy + ch - 14, "Sign in", size=8, color=C_BRAND, bold=True, anchor="middle")
    _input(d, cx + 10, cy + ch - 32, cw - 20, 10, "username")
    _input(d, cx + 10, cy + ch - 48, cw - 20, 10, "password")
    _button(d, cx + 10, cy + ch - 65, cw - 20, 11, "Sign in")
    return d


def mockup_dashboard():
    d = Drawing(MOCK_W, MOCK_H)
    w, h = MOCK_W, MOCK_H
    _window_frame(d, w, h, "Dashboard")
    # nav pills
    for i, name in enumerate(["Dashboard", "Members", "Inventory", "Trans."]):
        bx = 8 + i * 38
        fill = C_BRAND if i == 0 else C_PANEL
        text = colors.white if i == 0 else C_TEXT
        d.add(Rect(bx, h - 28, 36, 9, fillColor=fill, strokeColor=C_LINE, rx=4, ry=4))
        _label(d, bx + 18, h - 25, name, size=5, color=text, bold=True, anchor="middle")
    # KPI cards
    for i, (label, value) in enumerate([("Sales", "₱12.4K"), ("Members", "248"), ("Stock", "Low: 3")]):
        bx = 8 + i * 64
        d.add(Rect(bx, h - 70, 60, 32, fillColor=C_PANEL, strokeColor=C_LINE, rx=3, ry=3))
        _label(d, bx + 4, h - 50, label, size=5, color=C_MUTED)
        _label(d, bx + 4, h - 62, value, size=9, color=C_BRAND, bold=True)
    # chart placeholder
    d.add(Rect(8, 10, w - 16, 50, fillColor=C_PANEL, strokeColor=C_LINE, rx=3, ry=3))
    # bars
    for i, height in enumerate([18, 28, 22, 36, 30, 42, 26]):
        d.add(Rect(16 + i * 24, 16, 16, height, fillColor=C_BRAND, strokeColor=None, rx=1, ry=1))
    return d


def mockup_members():
    d = Drawing(MOCK_W, MOCK_H)
    w, h = MOCK_W, MOCK_H
    _window_frame(d, w, h, "Members")
    _label(d, 8, h - 28, "Members", size=8, color=C_BRAND, bold=True)
    _button(d, w - 60, h - 30, 52, 11, "+ Add Member")
    # header row
    d.add(Rect(8, h - 50, w - 16, 12, fillColor=C_BRAND_LIGHT, strokeColor=C_LINE, strokeWidth=0.3))
    _label(d, 12, h - 46, "Name", size=5, color=C_BRAND, bold=True)
    _label(d, 90, h - 46, "ID", size=5, color=C_BRAND, bold=True)
    _label(d, 130, h - 46, "Balance", size=5, color=C_BRAND, bold=True)
    # rows
    for i, (n, mid, bal) in enumerate([("Maria Santos", "M-0012", "₱1,250"),
                                        ("Juan dela Cruz", "M-0013", "₱   480"),
                                        ("Ana Reyes", "M-0014", "₱2,310"),
                                        ("Pedro Garcia", "M-0015", "₱   95")]):
        y = h - 64 - i * 14
        d.add(Rect(8, y, w - 16, 12, fillColor=C_PANEL, strokeColor=C_LINE, strokeWidth=0.3))
        _label(d, 12, y + 4, n, size=5, color=C_TEXT)
        _label(d, 90, y + 4, mid, size=5, color=C_MUTED)
        _label(d, 130, y + 4, bal, size=5, color=C_BRAND, bold=True)
    return d


def mockup_refill():
    d = Drawing(MOCK_W, MOCK_H)
    w, h = MOCK_W, MOCK_H
    _window_frame(d, w, h, "Refill Balance")
    cx, cy, cw, ch = w * 0.15, h * 0.15, w * 0.7, h * 0.62
    d.add(Rect(cx, cy, cw, ch, fillColor=C_PANEL, strokeColor=C_LINE, rx=4, ry=4))
    _label(d, cx + cw / 2, cy + ch - 12, "Refill — Maria Santos", size=7, color=C_BRAND, bold=True, anchor="middle")
    _label(d, cx + 8, cy + ch - 26, "Current: ₱1,250", size=5, color=C_MUTED)
    _label(d, cx + 8, cy + ch - 40, "Amount", size=5, color=C_TEXT)
    _input(d, cx + 8, cy + ch - 54, cw - 16, 10, "0.00")
    _label(d, cx + 8, cy + ch - 68, "Method:  ● Cash    ○ Transfer", size=5, color=C_TEXT)
    _button(d, cx + cw - 60, cy + 8, 52, 12, "Confirm")
    return d


def mockup_inventory():
    d = Drawing(MOCK_W, MOCK_H)
    w, h = MOCK_W, MOCK_H
    _window_frame(d, w, h, "Inventory")
    _label(d, 8, h - 28, "Inventory", size=8, color=C_BRAND, bold=True)
    _button(d, w - 66, h - 30, 58, 11, "+ Add Product")
    # grid of product cards
    for i in range(6):
        col = i % 3
        row = i // 3
        x = 10 + col * 60
        y = h - 100 - row * 56
        d.add(Rect(x, y, 56, 50, fillColor=C_PANEL, strokeColor=C_LINE, rx=2, ry=2))
        d.add(Rect(x + 4, y + 22, 48, 22, fillColor=C_BG, strokeColor=None, rx=2, ry=2))
        _label(d, x + 28, y + 30, "[ image ]", size=4, color=C_MUTED, anchor="middle")
        _label(d, x + 4, y + 14, "Soap 100g", size=5, color=C_TEXT, bold=True)
        _label(d, x + 4, y + 6, "₱25 · 42 left", size=4, color=C_BRAND)
    return d


def mockup_transactions():
    d = Drawing(MOCK_W, MOCK_H)
    w, h = MOCK_W, MOCK_H
    _window_frame(d, w, h, "Transactions")
    _label(d, 8, h - 28, "Transactions", size=8, color=C_BRAND, bold=True)
    # filters
    _input(d, 8, h - 42, 60, 9, "from date")
    _input(d, 72, h - 42, 60, 9, "to date")
    _button(d, 138, h - 42, 30, 9, "Filter", font_size=5)
    # rows
    for i, (date, member, amount, status) in enumerate([
        ("06-13  09:14", "Maria S.", "₱   85.00", "Paid"),
        ("06-13  09:42", "Juan C.", "₱  230.50", "Paid"),
        ("06-13  10:05", "Ana R.", "₱   45.00", "Refund"),
        ("06-13  10:30", "Pedro G.", "₱  112.00", "Paid"),
    ]):
        y = h - 60 - i * 14
        d.add(Rect(8, y, w - 16, 12, fillColor=C_PANEL, strokeColor=C_LINE, strokeWidth=0.3))
        _label(d, 12, y + 4, date, size=5, color=C_TEXT)
        _label(d, 70, y + 4, member, size=5, color=C_TEXT)
        _label(d, 115, y + 4, amount, size=5, color=C_BRAND, bold=True)
        col = C_BRAND if status == "Paid" else C_DANGER
        _label(d, 165, y + 4, status, size=5, color=col, bold=True)
    return d


def mockup_refund():
    d = Drawing(MOCK_W, MOCK_H)
    w, h = MOCK_W, MOCK_H
    _window_frame(d, w, h, "Refund")
    cx, cy, cw, ch = 10, 10, w - 20, h - 30
    d.add(Rect(cx, cy, cw, ch, fillColor=C_PANEL, strokeColor=C_LINE, rx=3, ry=3))
    _label(d, cx + 6, cy + ch - 12, "Refund — TXN #1042", size=7, color=C_BRAND, bold=True)
    for i, (item, qty, price, sel) in enumerate([
        ("Soap 100g", "2", "₱50", True),
        ("Rice 1kg", "1", "₱65", False),
        ("Milk 250ml", "1", "₱45", True),
    ]):
        y = cy + ch - 28 - i * 14
        d.add(Rect(cx + 6, y, cw - 12, 12, fillColor=C_BG if sel else C_PANEL,
                   strokeColor=C_LINE, strokeWidth=0.3))
        mark = "[x]" if sel else "[ ]"
        _label(d, cx + 10, y + 4, mark, size=6, color=C_BRAND if sel else C_MUTED, bold=True)
        _label(d, cx + 28, y + 4, item, size=5, color=C_TEXT)
        _label(d, cx + 90, y + 4, "qty " + qty, size=5, color=C_MUTED)
        _label(d, cx + 130, y + 4, price, size=5, color=C_BRAND, bold=True)
    _button(d, cx + cw - 58, cy + 8, 50, 12, "Refund")
    return d


def mockup_report():
    d = Drawing(MOCK_W, MOCK_H)
    w, h = MOCK_W, MOCK_H
    _window_frame(d, w, h, "Generate Report")
    cx, cy, cw, ch = w * 0.12, h * 0.15, w * 0.76, h * 0.62
    d.add(Rect(cx, cy, cw, ch, fillColor=C_PANEL, strokeColor=C_LINE, rx=4, ry=4))
    _label(d, cx + cw / 2, cy + ch - 12, "Generate Report", size=7, color=C_BRAND, bold=True, anchor="middle")
    _label(d, cx + 8, cy + ch - 26, "Type:   ● Daily   ○ Weekly   ○ Monthly", size=5, color=C_TEXT)
    _label(d, cx + 8, cy + ch - 40, "From", size=5, color=C_MUTED)
    _input(d, cx + 30, cy + ch - 44, cw - 40, 9, "06-01")
    _label(d, cx + 8, cy + ch - 54, "To", size=5, color=C_MUTED)
    _input(d, cx + 30, cy + ch - 58, cw - 40, 9, "06-13")
    _label(d, cx + 8, cy + ch - 70, "Output:  ● PDF   ○ Screen   ○ Email", size=5, color=C_TEXT)
    _button(d, cx + cw - 60, cy + 8, 52, 12, "Generate")
    return d


def mockup_kiosk_home():
    d = Drawing(MOCK_W, MOCK_H)
    w, h = MOCK_W, MOCK_H
    d.add(Rect(0, 0, w, h, fillColor=C_PANEL_DARK, strokeColor=C_LINE, rx=6, ry=6))
    _label(d, w / 2, h - 25, "Welcome to GenGlow", size=11, color=colors.white, bold=True, anchor="middle")
    _label(d, w / 2, h - 40, "Self-Checkout Kiosk", size=7, color=C_MUTED, anchor="middle")
    # Start button
    d.add(Rect(w / 2 - 50, h / 2 - 22, 100, 28, fillColor=C_BRAND, strokeColor=None, rx=14, ry=14))
    _label(d, w / 2, h / 2 - 8, "TAP TO START", size=9, color=colors.white, bold=True, anchor="middle")
    _label(d, w / 2, 20, "Scan card · Enter ID · Use PIN", size=5, color=C_MUTED, anchor="middle")
    return d


def mockup_kiosk_shop():
    d = Drawing(MOCK_W, MOCK_H)
    w, h = MOCK_W, MOCK_H
    _window_frame(d, w, h, "Shop")
    # search bar
    _input(d, 8, h - 28, w - 60, 10, "search products...")
    _button(d, w - 48, h - 28, 40, 10, "Cart (3)", font_size=5)
    # product grid
    for i in range(6):
        col = i % 3
        row = i // 3
        x = 10 + col * 60
        y = h - 100 - row * 56
        d.add(Rect(x, y, 56, 50, fillColor=C_PANEL, strokeColor=C_LINE, rx=2, ry=2))
        d.add(Rect(x + 4, y + 24, 48, 22, fillColor=C_BG, strokeColor=None, rx=2, ry=2))
        _label(d, x + 28, y + 32, "[ image ]", size=4, color=C_MUTED, anchor="middle")
        _label(d, x + 4, y + 14, f"Product {i+1}", size=5, color=C_TEXT, bold=True)
        _label(d, x + 4, y + 6, "₱25.00", size=4, color=C_BRAND, bold=True)
        # plus button
        d.add(Circle(x + 50, y + 12, 4, fillColor=C_BRAND, strokeColor=None))
        _label(d, x + 50, y + 10, "+", size=6, color=colors.white, bold=True, anchor="middle")
    return d


def mockup_kiosk_checkout():
    d = Drawing(MOCK_W, MOCK_H)
    w, h = MOCK_W, MOCK_H
    _window_frame(d, w, h, "Checkout")
    _label(d, 8, h - 28, "Your Cart", size=8, color=C_BRAND, bold=True)
    for i, (item, qty, price) in enumerate([
        ("Soap 100g", "x2", "₱  50.00"),
        ("Rice 1kg",  "x1", "₱  65.00"),
        ("Milk 250ml","x1", "₱  45.00"),
    ]):
        y = h - 46 - i * 14
        d.add(Rect(8, y, w - 16, 12, fillColor=C_PANEL, strokeColor=C_LINE, strokeWidth=0.3))
        _label(d, 12, y + 4, item, size=5, color=C_TEXT)
        _label(d, 80, y + 4, qty, size=5, color=C_MUTED)
        _label(d, 110, y + 4, price, size=5, color=C_BRAND, bold=True)
    # total
    d.add(Rect(8, h - 102, w - 16, 16, fillColor=C_BRAND_LIGHT, strokeColor=C_BRAND, strokeWidth=0.5, rx=2, ry=2))
    _label(d, 12, h - 96, "TOTAL", size=6, color=C_BRAND, bold=True)
    _label(d, w - 18, h - 96, "₱160.00", size=8, color=C_BRAND, bold=True, anchor="end")
    _button(d, 8, 12, (w - 24) / 2, 14, "Cancel", fill=colors.HexColor("#e2e8f0"), text_color=C_TEXT)
    _button(d, w / 2 + 4, 12, (w - 24) / 2, 14, "Confirm & Pay")
    return d


def _phone_frame(d, w, h, title=""):
    """Mobile phone frame."""
    d.add(Rect(0, 0, w, h, fillColor=C_PANEL_DARK, strokeColor=C_PANEL_DARK, rx=10, ry=10))
    d.add(Rect(6, 12, w - 12, h - 30, fillColor=C_BG, strokeColor=None, rx=6, ry=6))
    # notch
    d.add(Rect(w / 2 - 18, h - 12, 36, 5, fillColor=C_PANEL_DARK, strokeColor=None, rx=2, ry=2))
    # home indicator
    d.add(Rect(w / 2 - 18, 6, 36, 2, fillColor=C_MUTED, strokeColor=None, rx=1, ry=1))
    # top status bar inside screen
    d.add(Rect(6, h - 28, w - 12, 12, fillColor=C_BRAND, strokeColor=None))
    if title:
        _label(d, w / 2, h - 25, title, size=6, color=colors.white, bold=True, anchor="middle")


def mockup_mobile_login():
    d = Drawing(PHONE_W, PHONE_H)
    w, h = PHONE_W, PHONE_H
    _phone_frame(d, w, h, "GenGlow")
    # logo placeholder
    d.add(Circle(w / 2, h - 80, 18, fillColor=C_BRAND, strokeColor=None))
    _label(d, w / 2, h - 82, "GG", size=10, color=colors.white, bold=True, anchor="middle")
    _label(d, w / 2, h - 110, "Welcome back", size=8, color=C_TEXT, bold=True, anchor="middle")
    _input(d, 18, h - 140, w - 36, 14, "username")
    _input(d, 18, h - 162, w - 36, 14, "password")
    _button(d, 18, h - 188, w - 36, 16, "Sign in")
    _label(d, w / 2, h - 210, "Forgot password?", size=5, color=C_BRAND, anchor="middle")
    return d


def mockup_mobile_home():
    d = Drawing(PHONE_W, PHONE_H)
    w, h = PHONE_W, PHONE_H
    _phone_frame(d, w, h, "Home")
    # balance card
    d.add(Rect(12, h - 90, w - 24, 50, fillColor=C_BRAND, strokeColor=None, rx=6, ry=6))
    _label(d, 22, h - 56, "Available balance", size=5, color=colors.HexColor("#a7f3d0"))
    _label(d, 22, h - 78, "₱ 1,250.00", size=14, color=colors.white, bold=True)
    # quick actions
    for i, (label, _) in enumerate([("Products", "P"), ("Transfer", "T"), ("History", "H")]):
        x = 16 + i * ((w - 32) / 3)
        bw = (w - 40) / 3
        d.add(Rect(x, h - 130, bw, 28, fillColor=C_PANEL, strokeColor=C_LINE, rx=4, ry=4))
        d.add(Circle(x + bw / 2, h - 112, 5, fillColor=C_BRAND_LIGHT, strokeColor=C_BRAND, strokeWidth=0.6))
        _label(d, x + bw / 2, h - 122, label, size=4, color=C_TEXT, bold=True, anchor="middle")
    # recent list header
    _label(d, 14, h - 150, "Recent activity", size=6, color=C_BRAND, bold=True)
    for i, (date, label, amt) in enumerate([("06-13", "Purchase", "-₱85"),
                                              ("06-12", "Refill",   "+₱500"),
                                              ("06-12", "Transfer", "-₱100")]):
        y = h - 168 - i * 16
        d.add(Rect(12, y, w - 24, 14, fillColor=C_PANEL, strokeColor=C_LINE, strokeWidth=0.3, rx=2, ry=2))
        _label(d, 16, y + 4, date, size=4, color=C_MUTED)
        _label(d, 38, y + 4, label, size=5, color=C_TEXT)
        col = C_BRAND if amt.startswith("+") else C_DANGER
        _label(d, w - 16, y + 4, amt, size=5, color=col, bold=True, anchor="end")
    # tab bar
    d.add(Rect(6, 14, w - 12, 18, fillColor=C_PANEL, strokeColor=C_LINE, strokeWidth=0.3))
    for i, name in enumerate(["Home", "Products", "Transfer", "More"]):
        x = 6 + i * ((w - 12) / 4)
        bw = (w - 12) / 4
        col = C_BRAND if i == 0 else C_MUTED
        _label(d, x + bw / 2, 22, name, size=4, color=col, bold=(i == 0), anchor="middle")
    return d


def mockup_mobile_products():
    d = Drawing(PHONE_W, PHONE_H)
    w, h = PHONE_W, PHONE_H
    _phone_frame(d, w, h, "Products")
    _input(d, 12, h - 50, w - 24, 12, "search products...")
    # category pills
    for i, name in enumerate(["All", "Food", "Drinks", "Soap"]):
        x = 12 + i * 32
        fill = C_BRAND if i == 0 else C_PANEL
        text_col = colors.white if i == 0 else C_TEXT
        d.add(Rect(x, h - 70, 30, 10, fillColor=fill, strokeColor=C_LINE, rx=5, ry=5))
        _label(d, x + 15, h - 67, name, size=4, color=text_col, bold=True, anchor="middle")
    # product list
    for i in range(4):
        y = h - 92 - i * 32
        d.add(Rect(12, y, w - 24, 28, fillColor=C_PANEL, strokeColor=C_LINE, strokeWidth=0.3, rx=3, ry=3))
        d.add(Rect(16, y + 4, 20, 20, fillColor=C_BG, strokeColor=None, rx=2, ry=2))
        _label(d, 26, y + 12, "img", size=4, color=C_MUTED, anchor="middle")
        _label(d, 42, y + 18, f"Product {i+1}", size=6, color=C_TEXT, bold=True)
        _label(d, 42, y + 8, "₱25.00 · in stock", size=5, color=C_BRAND)
        d.add(Circle(w - 22, y + 14, 6, fillColor=C_BRAND, strokeColor=None))
        _label(d, w - 22, y + 11, "+", size=8, color=colors.white, bold=True, anchor="middle")
    return d


def mockup_mobile_transfer():
    d = Drawing(PHONE_W, PHONE_H)
    w, h = PHONE_W, PHONE_H
    _phone_frame(d, w, h, "Fund Transfer")
    _label(d, w / 2, h - 50, "Send funds", size=8, color=C_TEXT, bold=True, anchor="middle")
    _label(d, 16, h - 72, "From", size=5, color=C_MUTED)
    _label(d, 16, h - 82, "You · ₱1,250.00", size=6, color=C_TEXT, bold=True)
    _label(d, 16, h - 102, "Recipient member ID", size=5, color=C_MUTED)
    _input(d, 16, h - 118, w - 32, 14, "M-0013")
    _label(d, 16, h - 138, "Amount", size=5, color=C_MUTED)
    _input(d, 16, h - 154, w - 32, 14, "₱ 100.00")
    _label(d, 16, h - 174, "Note (optional)", size=5, color=C_MUTED)
    _input(d, 16, h - 190, w - 32, 14, "share for snacks")
    _button(d, 16, h - 220, w - 32, 18, "Send")
    return d


def mockup_mobile_transactions():
    d = Drawing(PHONE_W, PHONE_H)
    w, h = PHONE_W, PHONE_H
    _phone_frame(d, w, h, "Transactions")
    # filter
    _input(d, 12, h - 50, w - 70, 12, "this month")
    _button(d, w - 54, h - 50, 42, 12, "Filter", font_size=5)
    for i, (date, label, amt) in enumerate([
        ("Jun 13", "Purchase · Kiosk",  "-₱85.00"),
        ("Jun 12", "Refill from cash",  "+₱500.00"),
        ("Jun 12", "Transfer to M-0013","-₱100.00"),
        ("Jun 10", "Purchase · Kiosk",  "-₱45.00"),
        ("Jun 09", "Refund",            "+₱25.00"),
    ]):
        y = h - 76 - i * 24
        d.add(Rect(12, y, w - 24, 20, fillColor=C_PANEL, strokeColor=C_LINE, strokeWidth=0.3, rx=3, ry=3))
        _label(d, 16, y + 12, date, size=5, color=C_MUTED, bold=True)
        _label(d, 16, y + 4, label, size=5, color=C_TEXT)
        col = C_BRAND if amt.startswith("+") else C_DANGER
        _label(d, w - 16, y + 9, amt, size=6, color=col, bold=True, anchor="end")
    return d


def caption(text, styles):
    return Paragraph(
        f"<para align='center'><font color='#475569' size=8><i>{text}</i></font></para>",
        styles["Body"],
    )


def procedure_with_image(title, steps, drawing, styles, caption_text=""):
    """Render a procedure: title, then a side-by-side table of [steps | mockup]."""
    flow = []
    if title:
        flow.append(Paragraph(title, styles["H3"]))
    step_flow = []
    for i, text in enumerate(steps, 1):
        step_flow.append(
            Paragraph(
                f"<b><font color='#ED1C24'>{i}.</font></b> {text}",
                styles["Body"],
            )
        )
    img_cell = [drawing]
    if caption_text:
        img_cell.append(Spacer(1, 3))
        img_cell.append(caption(caption_text, styles))
    tbl = Table(
        [[step_flow, img_cell]],
        colWidths=[9.0 * cm, 7.5 * cm],
    )
    tbl.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    flow.append(tbl)
    flow.append(Spacer(1, 6))
    return flow


def build_cover(styles):
    story = []
    story.append(Spacer(1, 5.5 * cm))
    story.append(Paragraph("GenGlow", styles["CoverTitle"]))
    story.append(Paragraph("Self-Checkout System", styles["CoverSubtitle"]))
    story.append(Spacer(1, 0.8 * cm))
    story.append(Paragraph("User Manual", styles["CoverSubtitle"]))
    story.append(Spacer(1, 6 * cm))

    info_tbl = Table(
        [
            ["Document", "User Manual"],
            ["Version", "1.0"],
            ["Audience", "Admins, Cashiers, Members, Mobile App Users"],
            ["Modules", "Admin Panel, Kiosk, Mobile App"],
        ],
        colWidths=[4 * cm, 9 * cm],
        hAlign="CENTER",
    )
    info_tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#1e293b")),
                ("BACKGROUND", (1, 0), (1, -1), colors.HexColor("#334155")),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#475569")),
            ]
        )
    )
    story.append(info_tbl)
    story.append(PageBreak())
    return story


def build_toc(styles):
    story = []
    story.append(Paragraph("Table of Contents", styles["H1"]))
    story.append(section_divider())
    story.append(Spacer(1, 10))

    toc_items = [
        ("1.", "Introduction", "4"),
        ("2.", "System Overview", "5"),
        ("3.", "Getting Started", "6"),
        ("4.", "Admin Panel Guide", "7"),
        ("4.1", "Logging In", "7"),
        ("4.2", "Dashboard Overview", "8"),
        ("4.3", "Managing Members", "9"),
        ("4.4", "Managing Inventory", "10"),
        ("4.5", "Transactions & Refunds", "11"),
        ("4.6", "Reports & Receipts", "12"),
        ("5.", "Kiosk (Self-Checkout) Guide", "13"),
        ("6.", "Mobile App Guide", "14"),
        ("6.1", "Login & Registration", "14"),
        ("6.2", "Browsing Products", "15"),
        ("6.3", "Fund Transfer", "16"),
        ("6.4", "Viewing Transactions", "17"),
        ("7.", "Troubleshooting", "18"),
        ("8.", "FAQ", "19"),
        ("9.", "Support & Contact", "20"),
    ]

    rows = [[f"<font color='#ED1C24'><b>{n}</b></font>", t, f"<font color='#475569'>{p}</font>"] for n, t, p in toc_items]
    rows = [[Paragraph(c, styles["TOCItem"]) for c in row] for row in rows]
    tbl = Table(rows, colWidths=[1.5 * cm, 13 * cm, 2 * cm])
    tbl.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LINEBELOW", (0, 0), (-1, -1), 0.3, BORDER),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(tbl)
    story.append(PageBreak())
    return story


def build_intro(styles):
    story = []
    story.append(Paragraph("1. Introduction", styles["H1"]))
    story.append(section_divider())
    story.append(Spacer(1, 10))
    story.append(
        Paragraph(
            "Welcome to the <b>GenGlow Self-Checkout System</b> user manual. "
            "GenGlow is an integrated cooperative kiosk platform that lets members "
            "shop, pay, and manage their account without waiting in line. This guide "
            "walks every user — admin, cashier, member, or mobile app user — through "
            "the daily tasks they will perform in the system.",
            styles["Body"],
        )
    )
    story.append(Spacer(1, 6))
    story.append(Paragraph("Who should read this manual", styles["H2"]))
    story.append(
        make_bullets(
            [
                "<b>Administrators</b> — manage members, inventory, transactions, and reports from the Admin Panel.",
                "<b>Cashiers / Staff</b> — process refills, refunds, and assist members at the counter.",
                "<b>Members</b> — use the kiosk or mobile app to buy products and check their balance.",
                "<b>Mobile app users</b> — perform fund transfers and review history from their phone.",
            ],
            styles,
        )
    )
    story.append(Spacer(1, 10))
    story.append(Paragraph("How to use this manual", styles["H2"]))
    story.append(
        Paragraph(
            "Each chapter focuses on one part of the system. Use the table of contents "
            "to jump to your role. Step-by-step instructions are numbered, tips appear in "
            "green boxes, and important warnings appear in orange boxes.",
            styles["Body"],
        )
    )
    story.append(Spacer(1, 10))
    story.append(
        info_box(
            "<b>Tip:</b> Keep this manual close on your first day. After a week of use, "
            "most actions become second nature.",
            styles,
        )
    )
    story.append(PageBreak())
    return story


def build_overview(styles):
    story = []
    story.append(Paragraph("2. System Overview", styles["H1"]))
    story.append(section_divider())
    story.append(Spacer(1, 10))
    story.append(
        Paragraph(
            "GenGlow is made up of three coordinated parts that share one database. "
            "You can use any one of them on its own, but they work best together.",
            styles["Body"],
        )
    )
    story.append(Spacer(1, 8))

    components = [
        [
            "Admin Panel",
            "A web-based dashboard for staff. Manage members, inventory, transactions, refunds, "
            "and reports. Open in any modern browser.",
        ],
        [
            "Kiosk",
            "Touch-screen self-checkout terminal. Members scan or pick products, then pay from "
            "their cooperative balance.",
        ],
        [
            "Mobile App",
            "Android/iOS app for members. Browse products, view transaction history, transfer "
            "funds, and review balance from anywhere.",
        ],
    ]
    story.append(make_card_table(components))
    story.append(Spacer(1, 14))

    # Three-component diagram
    diagram = Drawing(16 * cm, 4.2 * cm)
    boxes = [
        (1.0 * cm, "Admin Panel", "Web browser", BRAND_GREEN),
        (6.0 * cm, "Kiosk", "Touch screen", BRAND_ACCENT),
        (11.0 * cm, "Mobile App", "Android / iOS", BRAND_TEAL),
    ]
    for x, t, sub, c in boxes:
        diagram.add(Rect(x, 0.8 * cm, 4 * cm, 2.5 * cm, fillColor=c, strokeColor=None, rx=8, ry=8))
        diagram.add(String(x + 2 * cm, 0.8 * cm + 1.7 * cm, t,
                           fontName="Helvetica-Bold", fontSize=12,
                           fillColor=colors.white, textAnchor="middle"))
        diagram.add(String(x + 2 * cm, 0.8 * cm + 1.0 * cm, sub,
                           fontName="Helvetica", fontSize=9,
                           fillColor=colors.HexColor("#e2e8f0"), textAnchor="middle"))
    diagram.add(Line(5 * cm, 2 * cm, 6 * cm, 2 * cm, strokeColor=BRAND_GREEN, strokeWidth=2))
    diagram.add(Line(10 * cm, 2 * cm, 11 * cm, 2 * cm, strokeColor=BRAND_GREEN, strokeWidth=2))
    diagram.add(String(8 * cm, 0.3 * cm, "All three share one database",
                       fontName="Helvetica-Oblique", fontSize=8,
                       fillColor=TEXT_MUTED, textAnchor="middle"))
    story.append(diagram)
    story.append(Spacer(1, 10))

    story.append(Paragraph("Roles and what they can do", styles["H2"]))
    role_rows = [
        ["Role", "Admin Panel", "Kiosk", "Mobile App"],
        ["Super Admin", "Full access", "View only", "Admin overview"],
        ["Cashier / Staff", "Refill, refund, reports", "Assist members", "—"],
        ["Member", "—", "Self-checkout", "Browse, transfer, history"],
    ]
    role_tbl = Table(role_rows, colWidths=[3.5 * cm, 4.5 * cm, 4 * cm, 4.5 * cm])
    role_tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), BRAND_GREEN),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BG_LIGHT]),
                ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(role_tbl)
    story.append(PageBreak())
    return story


def build_getting_started(styles):
    story = []
    story.append(Paragraph("3. Getting Started", styles["H1"]))
    story.append(section_divider())
    story.append(Spacer(1, 10))

    story.append(Paragraph("Before you begin", styles["H2"]))
    story.append(
        make_bullets(
            [
                "Make sure the server PC is on and connected to the network.",
                "Confirm the kiosk screen displays the GenGlow login screen.",
                "Have your username and password ready (issued by your administrator).",
                "Mobile app users need the latest version installed from the cooperative.",
            ],
            styles,
        )
    )
    story.append(Spacer(1, 10))

    story.append(Paragraph("First-time setup", styles["H2"]))
    story.extend(
        make_steps(
            [
                "Receive your account credentials from the cooperative admin.",
                "Open the Admin Panel in your browser at the URL given by the admin.",
                "Log in and change your password from the profile menu.",
                "If you are a member, ask the admin to refill your balance so you can start "
                "purchasing.",
                "Install the mobile app and log in with the same credentials.",
            ],
            styles,
        )
    )
    story.append(Spacer(1, 10))
    story.append(
        warning_box(
            "<b>Important:</b> Never share your password. Each action you take is logged "
            "against your account.",
            styles,
        )
    )
    story.append(PageBreak())
    return story


def build_admin_panel(styles):
    story = []
    story.append(Paragraph("4. Admin Panel Guide", styles["H1"]))
    story.append(section_divider())
    story.append(Spacer(1, 10))
    story.append(
        Paragraph(
            "The Admin Panel is the control center for staff. Everything from adding a new "
            "member to issuing a refund happens here.",
            styles["Body"],
        )
    )

    story.append(Spacer(1, 12))
    story.append(Paragraph("4.1 Logging In", styles["H2"]))
    story.extend(
        procedure_with_image(
            "",
            [
                "Open your browser and go to the Admin Panel URL.",
                "Enter your <b>username</b> and <b>password</b>.",
                "Click <b>Sign in</b>. You will land on either the Super Admin Console or a role-specific dashboard.",
            ],
            mockup_login(),
            styles,
            "Login screen layout",
        )
    )
    story.append(
        info_box(
            "<b>Tip:</b> If you forget your password, ask another admin to reset it from "
            "the user management page.",
            styles,
        )
    )

    story.append(PageBreak())
    story.append(Paragraph("4.2 Dashboard Overview", styles["H2"]))
    intro = Paragraph(
        "The dashboard summarises today's activity at a glance. You will typically see "
        "sales summaries, active member counts, top-selling products, low-stock alerts "
        "and a list of recent transactions.",
        styles["Body"],
    )
    bullets = make_bullets(
        [
            "<b>Sales summary</b> — today, this week, this month.",
            "<b>Active members</b> count and new registrations.",
            "<b>Top-selling products</b> chart.",
            "<b>Low-stock alerts</b> for items to reorder.",
            "<b>Recent transactions</b> with quick links.",
        ],
        styles,
    )
    img_cell = [mockup_dashboard(), Spacer(1, 3), caption("Dashboard layout", styles)]
    tbl = Table([[ [intro, Spacer(1,4), bullets], img_cell ]], colWidths=[9*cm, 7.5*cm])
    tbl.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),
                              ("LEFTPADDING",(0,0),(-1,-1),0),
                              ("RIGHTPADDING",(0,0),(-1,-1),0)]))
    story.append(tbl)
    story.append(Spacer(1, 10))
    story.append(Paragraph("Navigating the panel", styles["H3"]))
    story.append(
        Paragraph(
            "Use the top navigation pills to jump between Dashboard, Members, Inventory, "
            "Transactions, Refunds, and Reports. The current page is highlighted in green.",
            styles["Body"],
        )
    )

    story.append(PageBreak())
    story.append(Paragraph("4.3 Managing Members", styles["H2"]))
    story.extend(
        procedure_with_image(
            "Add a new member",
            [
                "Open <b>Members</b> from the top navigation.",
                "Click <b>+ Add Member</b>.",
                "Fill in name, contact number, email, and starting balance (optional).",
                "Click <b>Save</b>. The new member appears in the list and can use the kiosk immediately.",
            ],
            mockup_members(),
            styles,
            "Members page",
        )
    )
    story.extend(
        procedure_with_image(
            "Refill a member's balance",
            [
                "Find the member in the Members list and click their row.",
                "Click <b>Refill Balance</b>.",
                "Enter the amount received and choose the payment method.",
                "Click <b>Confirm</b>. A receipt is generated automatically.",
            ],
            mockup_refill(),
            styles,
            "Refill balance dialog",
        )
    )
    story.append(
        info_box(
            "<b>Tip:</b> Always print or email the refill receipt to the member as proof "
            "of payment.",
            styles,
        )
    )

    story.append(PageBreak())
    story.append(Paragraph("4.4 Managing Inventory", styles["H2"]))
    story.extend(
        procedure_with_image(
            "Add a product",
            [
                "Open <b>Inventory</b> from the top navigation.",
                "Click <b>+ Add Product</b>.",
                "Enter the name, category, barcode, price, and starting stock.",
                "Upload a product image so members recognise it on the kiosk.",
                "Click <b>Save</b>.",
            ],
            mockup_inventory(),
            styles,
            "Inventory product grid",
        )
    )
    story.append(Paragraph("Restock or edit a product", styles["H3"]))
    story.extend(
        make_steps(
            [
                "Find the product in the inventory list.",
                "Click <b>Edit</b> to change price or details, or <b>Restock</b> to add received stock.",
                "Enter the new quantity and click <b>Save</b>.",
            ],
            styles,
        )
    )
    story.append(Spacer(1, 8))
    story.append(
        warning_box(
            "<b>Warning:</b> Reducing stock manually does not generate a sale. Use "
            "<b>Adjust Stock</b> only for losses, damage, or stock-count corrections.",
            styles,
        )
    )

    story.append(PageBreak())
    story.append(Paragraph("4.5 Transactions & Refunds", styles["H2"]))
    story.extend(
        procedure_with_image(
            "Review transactions",
            [
                "Open the <b>Transactions</b> page from the navigation.",
                "Filter by date range, member, or status.",
                "Click any row to view the full receipt.",
            ],
            mockup_transactions(),
            styles,
            "Transactions list",
        )
    )
    story.extend(
        procedure_with_image(
            "Process a refund",
            [
                "Open the original transaction from the Transactions list.",
                "Click <b>Refund</b>.",
                "Tick the items to refund (full or partial).",
                "Choose whether the refund returns to balance or as cash.",
                "Confirm. A refund receipt is created and stock is returned automatically.",
            ],
            mockup_refund(),
            styles,
            "Refund item selection",
        )
    )

    story.append(PageBreak())
    story.append(Paragraph("4.6 Reports & Receipts", styles["H2"]))
    story.extend(
        procedure_with_image(
            "Generate a report",
            [
                "Open <b>Dashboard</b> and click <b>Generate Report</b>.",
                "Choose the report type and date range.",
                "Pick the output: PDF, screen, or email.",
                "Click <b>Generate</b>. Large reports may take a few seconds.",
            ],
            mockup_report(),
            styles,
            "Generate report dialog",
        )
    )
    story.append(Paragraph("Receipt types", styles["H3"]))
    story.append(
        make_bullets(
            [
                "<b>Cash receipt</b> — over-the-counter cash sales.",
                "<b>Debit / Credit receipt</b> — credit purchase or balance-paid sale.",
                "<b>Credit payment receipt</b> — when a member repays credit.",
                "<b>Refund receipt</b> — generated for every refund.",
            ],
            styles,
        )
    )
    story.append(PageBreak())
    return story


def build_kiosk(styles):
    story = []
    story.append(Paragraph("5. Kiosk (Self-Checkout) Guide", styles["H1"]))
    story.append(section_divider())
    story.append(Spacer(1, 10))
    story.append(
        Paragraph(
            "The kiosk is the touch-screen terminal where members shop on their own. "
            "Each procedure below shows the screen the member is on at that step.",
            styles["Body"],
        )
    )
    story.append(Spacer(1, 10))
    story.extend(
        procedure_with_image(
            "Step 1 — Welcome screen",
            [
                "Tap <b>Start</b> on the welcome screen.",
                "Identify yourself: scan your member card, tap your number, or enter your PIN.",
            ],
            mockup_kiosk_home(),
            styles,
            "Kiosk welcome screen",
        )
    )
    story.append(PageBreak())
    story.extend(
        procedure_with_image(
            "Step 2 — Shop products",
            [
                "Browse by category or type in the search bar.",
                "Tap any product to add it to your cart.",
                "Tap <b>+</b> to increase quantity, or <b>−</b> to reduce it.",
                "Tap <b>Cart</b> at the top right to review what you have added.",
            ],
            mockup_kiosk_shop(),
            styles,
            "Kiosk shopping screen",
        )
    )
    story.extend(
        procedure_with_image(
            "Step 3 — Checkout",
            [
                "Review the cart and the total amount.",
                "Tap <b>Confirm &amp; Pay</b>. The amount is deducted from your balance.",
                "Pick up your printed receipt and take your items.",
            ],
            mockup_kiosk_checkout(),
            styles,
            "Cart and confirmation",
        )
    )
    story.append(
        info_box(
            "<b>Tip:</b> If your balance is too low, the kiosk offers to top up first or pay "
            "the difference in cash at the counter.",
            styles,
        )
    )
    story.append(Spacer(1, 8))
    story.append(Paragraph("Cancelling a purchase", styles["H3"]))
    story.append(
        Paragraph(
            "Tap <b>Cancel</b> at any time before confirming checkout — the cart clears and "
            "no charges are made. After confirmation, ask a staff member to process a refund "
            "from the Admin Panel.",
            styles["Body"],
        )
    )
    story.append(PageBreak())
    return story


def build_mobile(styles):
    story = []
    story.append(Paragraph("6. Mobile App Guide", styles["H1"]))
    story.append(section_divider())
    story.append(Spacer(1, 10))
    story.append(
        Paragraph(
            "The GenGlow mobile app lets members manage their account on the go. "
            "Install it from the store link provided by your cooperative.",
            styles["Body"],
        )
    )

    story.append(Spacer(1, 12))
    story.append(Paragraph("6.1 Login & Registration", styles["H2"]))
    story.extend(
        procedure_with_image(
            "",
            [
                "Open the GenGlow app.",
                "Enter the username (or member number) and password issued to you.",
                "Tap <b>Sign in</b>.",
                "On first login, verify your email with the one-time code (OTP) sent to you.",
                "You land on the Home screen showing your current balance.",
            ],
            mockup_mobile_login(),
            styles,
            "Mobile sign-in screen",
        )
    )
    story.append(
        warning_box(
            "<b>Heads up:</b> Make sure the phone is connected to the same network as the "
            "kiosk server, or to the internet if the server uses a public address.",
            styles,
        )
    )

    story.append(PageBreak())
    story.append(Paragraph("Home screen", styles["H2"]))
    home_intro = Paragraph(
        "The Home screen is your starting point. The big green card shows your current "
        "balance, the three buttons jump straight to Products, Transfer, and History, and "
        "the list below shows recent activity.",
        styles["Body"],
    )
    img_cell = [mockup_mobile_home(), Spacer(1, 3), caption("Mobile Home screen", styles)]
    tbl = Table([[home_intro, img_cell]], colWidths=[9*cm, 7.5*cm])
    tbl.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),
                              ("LEFTPADDING",(0,0),(-1,-1),0),
                              ("RIGHTPADDING",(0,0),(-1,-1),0)]))
    story.append(tbl)

    story.append(PageBreak())
    story.append(Paragraph("6.2 Browsing Products", styles["H2"]))
    story.extend(
        procedure_with_image(
            "",
            [
                "Tap <b>Products</b> from the bottom navigation.",
                "Scroll the list or use the search bar to find an item.",
                "Tap any product to view details (price, stock, description).",
                "Use category pills to filter by type.",
            ],
            mockup_mobile_products(),
            styles,
            "Products list",
        )
    )
    story.append(
        info_box(
            "<b>Tip:</b> The product list mirrors the kiosk. Out-of-stock items are clearly "
            "marked so you know what to expect at the counter.",
            styles,
        )
    )

    story.append(PageBreak())
    story.append(Paragraph("6.3 Fund Transfer", styles["H2"]))
    story.extend(
        procedure_with_image(
            "",
            [
                "Tap <b>Fund Transfer</b> from the Home screen.",
                "Enter or scan the recipient's member ID.",
                "Enter the amount and an optional note.",
                "Review the summary and tap <b>Send</b>.",
                "Confirm with your PIN or fingerprint. Both you and the recipient get a notification.",
            ],
            mockup_mobile_transfer(),
            styles,
            "Fund transfer screen",
        )
    )
    story.append(
        warning_box(
            "<b>Important:</b> Transfers are final. Double-check the recipient ID before "
            "confirming. If you transferred to the wrong person, contact admin to reverse it.",
            styles,
        )
    )

    story.append(PageBreak())
    story.append(Paragraph("6.4 Viewing Transactions", styles["H2"]))
    story.extend(
        procedure_with_image(
            "",
            [
                "Tap <b>Transactions</b> at the bottom of the screen.",
                "Scroll through your purchases, refills, refunds, and transfers.",
                "Tap any item to view the full receipt.",
                "Use the filter to jump to a specific period.",
            ],
            mockup_mobile_transactions(),
            styles,
            "Transactions history",
        )
    )
    story.append(Paragraph("Settings & Profile", styles["H3"]))
    story.append(
        make_bullets(
            [
                "Update your email, phone number, or password.",
                "Toggle notifications for purchases and transfers.",
                "View the app version and connection status.",
                "Tap <b>Sign out</b> to log out of the device.",
            ],
            styles,
        )
    )
    story.append(PageBreak())
    return story


def build_troubleshooting(styles):
    story = []
    story.append(Paragraph("7. Troubleshooting", styles["H1"]))
    story.append(section_divider())
    story.append(Spacer(1, 10))

    issues = [
        [
            "I can't log in.",
            "Check the username and caps lock. If still locked out, ask another admin to "
            "reset your password from the Admin Panel.",
        ],
        [
            "The kiosk shows 'Server not reachable'.",
            "Confirm the server PC is on and on the same network. Restart the kiosk app. If "
            "the issue persists, run <i>fix_firewall.bat</i> on the server.",
        ],
        [
            "Mobile app stays on 'Connecting...'.",
            "Make sure the device is on Wi-Fi reaching the server. Check the API URL in app "
            "settings matches the one printed in the admin console.",
        ],
        [
            "Receipt printer is silent.",
            "Check paper and USB cable. Re-open the kiosk app. If still no output, print a "
            "test page from the Admin Panel printer settings.",
        ],
        [
            "Inventory count looks wrong.",
            "Open the product in Inventory, then click <b>Stock History</b> to see every "
            "change. Use <b>Adjust Stock</b> to correct the count and log the reason.",
        ],
        [
            "Member's balance looks wrong.",
            "Open the member, click <b>Transaction History</b>, then locate the missing "
            "entry. Use <b>Refill</b> or <b>Refund</b> to make a corrective adjustment — "
            "never edit the balance directly.",
        ],
    ]
    rows = [[Paragraph(f"<b>{q}</b>", styles["Body"]), Paragraph(a, styles["Body"])] for q, a in issues]
    tbl = Table(rows, colWidths=[5.5 * cm, 11 * cm])
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), BG_LIGHT),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, BORDER),
            ]
        )
    )
    story.append(tbl)
    story.append(PageBreak())
    return story


def build_faq(styles):
    story = []
    story.append(Paragraph("8. Frequently Asked Questions", styles["H1"]))
    story.append(section_divider())
    story.append(Spacer(1, 10))

    qa = [
        (
            "Can two cashiers use the Admin Panel at the same time?",
            "Yes. Each user signs in with their own account, and the system tracks who did "
            "what.",
        ),
        (
            "How do I back up the database?",
            "The system writes daily backups into the <i>backups</i> folder. Copy the latest "
            "<i>db.sqlite3</i> to external storage at the end of each business day.",
        ),
        (
            "Does the kiosk work without internet?",
            "Yes. The kiosk only needs to reach the local server. Internet is only required "
            "if you use the mobile app from outside the cooperative or send email "
            "notifications.",
        ),
        (
            "Can I undo a sale?",
            "Use <b>Refund</b> from the Transactions page. Direct deletion is disabled to "
            "keep the audit trail intact.",
        ),
        (
            "What if a member loses their card?",
            "Issue a new card from the Members page and link it to the same member record. "
            "The old card is automatically deactivated.",
        ),
        (
            "Where do the daily report emails go?",
            "To the email address set in the Admin Panel's report settings. Check "
            "<i>DAILY_REPORT_SETUP.md</i> for configuration help.",
        ),
    ]
    for q, a in qa:
        story.append(Paragraph(f"Q. {q}", styles["H3"]))
        story.append(Paragraph(f"A. {a}", styles["Body"]))
        story.append(Spacer(1, 4))
    story.append(PageBreak())
    return story


def build_support(styles):
    story = []
    story.append(Paragraph("9. Support & Contact", styles["H1"]))
    story.append(section_divider())
    story.append(Spacer(1, 12))
    story.append(
        Paragraph(
            "If you cannot resolve an issue using this manual, please contact your "
            "cooperative's GenGlow administrator first. For technical issues that an admin "
            "cannot solve, escalate to the GenGlow support team.",
            styles["Body"],
        )
    )
    story.append(Spacer(1, 14))

    support = [
        ["Cooperative Admin", "On-site, refer to your local contact list"],
        ["Technical Support", "Provided by the GenGlow development team"],
        ["Documentation", "This manual and project README files"],
        ["Working Hours", "Monday – Saturday, business hours"],
    ]
    story.append(make_card_table(support))
    story.append(Spacer(1, 18))
    story.append(
        info_box(
            "<b>Before contacting support:</b> note the screen you were on, the action you "
            "took, and the exact error message. Screenshots help a lot.",
            styles,
        )
    )
    story.append(Spacer(1, 24))
    story.append(
        Paragraph(
            "<para align='center'><b>Thank you for using GenGlow.</b><br/>"
            "We hope this manual makes the system simple and rewarding to use every day.</para>",
            styles["Body"],
        )
    )
    return story


def build_document():
    doc = BaseDocTemplate(
        OUTPUT_PATH,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=1.8 * cm,
        bottomMargin=1.6 * cm,
        title="GenGlow Self-Checkout System User Manual",
        author="GenGlow",
    )
    frame_cover = Frame(0, 0, A4[0], A4[1], id="cover", showBoundary=0)
    frame_content = Frame(
        2 * cm, 1.6 * cm, A4[0] - 4 * cm, A4[1] - 3 * cm, id="content", showBoundary=0
    )
    doc.addPageTemplates(
        [
            PageTemplate(id="Cover", frames=[frame_cover], onPage=cover_page_canvas),
            PageTemplate(id="Content", frames=[frame_content], onPage=content_page_canvas),
        ]
    )

    from reportlab.platypus.doctemplate import NextPageTemplate

    styles = build_styles()
    story = []
    story.extend(build_cover(styles))
    story.append(NextPageTemplate("Content"))
    story.extend(build_toc(styles))
    story.extend(build_intro(styles))
    story.extend(build_overview(styles))
    story.extend(build_getting_started(styles))
    story.extend(build_admin_panel(styles))
    story.extend(build_kiosk(styles))
    story.extend(build_mobile(styles))
    story.extend(build_troubleshooting(styles))
    story.extend(build_faq(styles))
    story.extend(build_support(styles))

    doc.build(story)
    print(f"Generated: {OUTPUT_PATH}")


if __name__ == "__main__":
    build_document()
