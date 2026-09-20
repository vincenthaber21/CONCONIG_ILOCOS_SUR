"""
Generate Genglo Printing Services logo assets for the mobile app.
Produces: icon.png, adaptive-icon.png, splash.png, favicon.png

Design language mirrors HomeScreen.js:
  • Red→gold gradient header (#ED1C24 → #E6C200) — Bagnos brand / accent
  • White raised heroCard with drop-shadow
  • Wallet icon + peso "₱" in brand red (wallet-outline from HomeScreen)
  • App name in bold white  •  subtitle in cream
"""
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import os

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "mobile_app", "assets")

# ─── Colour Palette (Bagnos logo: red + yellow) ────────────────────────────
C_BG1        = (237,  28,  36)  # colors.brand  #ED1C24
C_BG2        = (230, 194,   0)  # colors.accent #E6C200
C_GOLD       = (230, 194,   0)  # logo yellow
C_LIGHT_GOLD = (255, 242,   0)  # #FFF200 — star yellow
C_CREAM      = (254, 247, 213)  # #FEF7D5 — subtitle / accent ring
C_GREEN      = C_GOLD           # alias for older call sites
C_LIGHT_GRN  = C_LIGHT_GOLD
C_MINT       = C_CREAM
C_WHITE      = (255, 255, 255)
C_CARD       = (255, 255, 255)  # panel = #ffffff (heroCard)
C_CARD_TINT  = (254, 247, 213)  # cream off-white tint


# ─── Helpers ─────────────────────────────────────────────────────────────────
def gradient_image(w, h, c1, c2):
    """Vertical gradient from c1 (top) to c2 (bottom)."""
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(h - 1, 1)
        colour = tuple(int(c1[i] * (1 - t) + c2[i] * t) for i in range(3))
        draw.line([(0, y), (w, y)], fill=colour)
    return img


def try_font(size, bold=True):
    """Load a TrueType font with automatic fallback."""
    candidates = (
        ["C:/Windows/Fonts/arialbd.ttf",  "C:/Windows/Fonts/calibrib.ttf",
         "C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/verdanab.ttf"]
        if bold else
        ["C:/Windows/Fonts/arial.ttf",    "C:/Windows/Fonts/calibri.ttf",
         "C:/Windows/Fonts/segoeui.ttf",  "C:/Windows/Fonts/verdana.ttf"]
    )
    for p in candidates:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()


def centered_text(draw, text, y, font, fill, img_w, drop_shadow=True):
    """Draw horizontally centred text with optional drop-shadow."""
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    x  = (img_w - tw) // 2 - bbox[0]
    if drop_shadow:
        draw.text((x + 3, y + 3), text, font=font, fill=(0, 0, 0, 80))
    draw.text((x, y), text, font=font, fill=fill)


def glow_layer(canvas_size, cx, cy, base_radius, colour, steps=14):
    """Return an RGBA glow overlay centred at (cx, cy)."""
    layer = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for i in range(steps, 0, -1):
        alpha = int(38 * i / steps)
        r = base_radius + i * 18
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*colour, alpha))
    return layer


def rrect(draw, x0, y0, x1, y1, r, fill=None, outline=None, lw=1):
    """
    Draw a rounded rectangle using Pillow's built-in when available,
    with a pure-geometry fallback for older versions.
    """
    try:
        if fill:
            draw.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=fill)
        if outline:
            draw.rounded_rectangle([x0, y0, x1, y1], radius=r,
                                   outline=outline, width=lw)
        return
    except AttributeError:
        pass
    # Fallback
    if fill:
        draw.rectangle([x0 + r, y0, x1 - r, y1], fill=fill)
        draw.rectangle([x0, y0 + r, x1, y1 - r], fill=fill)
        for cx, cy in [(x0 + r, y0 + r), (x1 - r, y0 + r),
                       (x0 + r, y1 - r), (x1 - r, y1 - r)]:
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)


def card_shadow(base, x0, y0, x1, y1, r, blur=24, alpha=55):
    """Composite a blurred drop-shadow under a rounded card."""
    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    rrect(sd, x0 + 6, y0 + 10, x1 + 6, y1 + 10, r, fill=(0, 0, 0, alpha))
    shadow = shadow.filter(ImageFilter.GaussianBlur(blur))
    return Image.alpha_composite(base, shadow)


def draw_wallet(draw, cx, cy, w, h, body_col, pocket_col, coin_col, symbol_col):
    """
    Draw a simple wallet icon (mirrors HomeScreen wallet-outline).
    body_col   — wallet body fill
    pocket_col — right-side coin pocket fill
    coin_col   — coin circle fill
    symbol_col — ₱ text colour
    """
    r = w // 9
    x0, y0 = cx - w // 2, cy - h // 2
    x1, y1 = cx + w // 2, cy + h // 2

    # Main wallet body
    rrect(draw, x0, y0, x1, y1, r, fill=body_col)

    # Darker top-flap strip (mimics card flap)
    flap_h = h // 4
    rrect(draw, x0, y0, x1, y0 + flap_h + r, r, fill=pocket_col)
    draw.rectangle([x0, y0 + flap_h, x1, y0 + flap_h + r + 1], fill=pocket_col)

    # Right coin-pocket recess
    pw   = w // 3
    ph   = int(h * 0.52)
    pr   = ph // 3
    px0  = x1 - pw - w // 14
    py0  = cy - ph // 2
    px1  = x1 - w // 14
    py1  = cy + ph // 2
    rrect(draw, px0, py0, px1, py1, pr, fill=pocket_col)

    # Coin circle inside pocket
    ccx  = (px0 + px1) // 2
    ccy  = (py0 + py1) // 2
    cr   = int(min(pw, ph) * 0.28)
    draw.ellipse([ccx - cr, ccy - cr, ccx + cr, ccy + cr], fill=coin_col)

    # ₱  peso symbol on left half of wallet body
    font_p = try_font(int(h * 0.62), bold=True)
    bbox   = draw.textbbox((0, 0), "\u20b1", font=font_p)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    left_cx = (x0 + px0) // 2
    tx = left_cx - tw // 2 - bbox[0]
    ty = cy     - th // 2 - bbox[1]
    draw.text((tx + 3, ty + 3), "\u20b1", font=font_p, fill=(0, 0, 0, 60))
    draw.text((tx, ty),         "\u20b1", font=font_p, fill=symbol_col)


# ─── Icon  1024 × 1024 ───────────────────────────────────────────────────────
def create_icon(size=1024):
    img = gradient_image(size, size, C_BG1, C_BG2).convert("RGBA")
    cx  = size // 2

    # Subtle central glow (matches HomeScreen brand colour warmth)
    img = Image.alpha_composite(
        img, glow_layer((size, size), cx, size // 2 - 40, 240, C_MINT, steps=12))

    # ── White heroCard ──────────────────────────────────────────────────────
    card_w  = int(size * 0.74)
    card_h  = int(size * 0.44)
    card_r  = 52
    cx0 = cx - card_w // 2
    cy0 = size // 2 - card_h // 2 - 55
    cx1 = cx + card_w // 2
    cy1 = cy0 + card_h

    img = card_shadow(img, cx0, cy0, cx1, cy1, card_r, blur=28, alpha=60)
    draw = ImageDraw.Draw(img)
    rrect(draw, cx0, cy0, cx1, cy1, card_r, fill=C_CARD)

    # "Account Balance" micro-label inside card  (heroLabelRow in HomeScreen)
    font_lbl = try_font(34, bold=False)
    lbl_bbox = draw.textbbox((0, 0), "Account Balance", font=font_lbl)
    lbl_x    = cx0 + 38
    lbl_y    = cy0 + 30
    draw.text((lbl_x, lbl_y), "Account Balance", font=font_lbl,
              fill=(100, 140, 110))

    # Wallet icon filling most of the card
    ww = int(card_w * 0.62)
    wh = int(card_h * 0.62)
    draw_wallet(draw,
                cx, cy0 + card_h // 2 + 14,
                ww, wh,
                body_col   = C_GREEN,
                pocket_col = C_BG2,
                coin_col   = C_LIGHT_GRN,
                symbol_col = C_WHITE)

    # Thin mint border on heroCard  (borderLight aesthetic)
    rrect(draw, cx0, cy0, cx1, cy1, card_r,
          outline=(*C_MINT, 120), lw=4)

    # ── "GENGLO" text ─────────────────────────────────────────────────────
    font_name = try_font(94, bold=True)
    centered_text(draw, "GENGLO", cy1 + 44, font_name, C_WHITE, size)

    font_sub = try_font(48, bold=False)
    centered_text(draw, "Printing Services", cy1 + 152, font_sub, C_MINT, size)

    return img.convert("RGB")


# ─── Adaptive Icon (foreground, transparent bg)  1024 × 1024 ────────────────
def create_adaptive_icon(size=1024):
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx   = size // 2

    # Green rounded-square badge
    pad = size // 10
    rrect(draw, pad, pad, size - pad, size - pad, size // 6, fill=C_GREEN)

    # Wallet icon centred
    ww = int(size * 0.58)
    wh = int(size * 0.42)
    draw_wallet(draw, cx, cx,
                ww, wh,
                body_col   = C_WHITE,
                pocket_col = C_CARD_TINT,
                coin_col   = C_MINT,
                symbol_col = C_GREEN)
    return img


# ─── Splash Screen  1080 × 1920 ──────────────────────────────────────────────
def create_splash(w=1080, h=1920):
    # White base — matches HomeScreen panel background
    img = Image.new("RGBA", (w, h), (*C_WHITE, 255))
    cx, cy = w // 2, h // 2 - 100

    # Soft green glow
    img = Image.alpha_composite(
        img, glow_layer((w, h), cx, cy, 160, C_GREEN, steps=10))

    # Green header strip (top ~38 % — mirrors HomeScreen header height)
    header_h = int(h * 0.38)
    draw = ImageDraw.Draw(img)
    hdr = gradient_image(w, header_h, C_BG1, C_BG2).convert("RGBA")
    img.paste(hdr, (0, 0))
    draw = ImageDraw.Draw(img)

    # Floating white heroCard in the middle
    card_w = int(w * 0.72)
    card_h = int(h * 0.22)
    card_r = 40
    cx0 = cx - card_w // 2
    cy0 = header_h - card_h // 2
    cx1 = cx + card_w // 2
    cy1 = cy0 + card_h

    img = card_shadow(img, cx0, cy0, cx1, cy1, card_r, blur=22, alpha=50)
    draw = ImageDraw.Draw(img)
    rrect(draw, cx0, cy0, cx1, cy1, card_r, fill=C_CARD)
    rrect(draw, cx0, cy0, cx1, cy1, card_r, outline=(*C_MINT, 100), lw=3)

    # Wallet inside card
    ww = int(card_w * 0.55)
    wh = int(card_h * 0.60)
    draw_wallet(draw,
                cx, (cy0 + cy1) // 2,
                ww, wh,
                body_col   = C_GREEN,
                pocket_col = C_BG2,
                coin_col   = C_LIGHT_GRN,
                symbol_col = C_WHITE)

    # "Account Balance" label top of card
    font_lbl = try_font(28, bold=False)
    lb = draw.textbbox((0, 0), "Account Balance", font=font_lbl)
    draw.text((cx0 + 26, cy0 + 18), "Account Balance",
              font=font_lbl, fill=(100, 140, 110))

    # Brand name below card
    font_brand = try_font(100, bold=True)
    centered_text(draw, "GENGLO", cy1 + 56, font_brand, C_BG2, w)

    font_svc = try_font(54, bold=False)
    centered_text(draw, "Printing Services", cy1 + 174, font_svc, C_GREEN, w)

    font_tag = try_font(38, bold=False)
    centered_text(draw, "Self-Checkout Kiosk", cy1 + 248, font_tag,
                  (150, 150, 150), w, drop_shadow=False)

    return img.convert("RGB")


# ─── Favicon  196 × 196 ──────────────────────────────────────────────────────
def create_favicon(size=196):
    img  = gradient_image(size, size, C_BG1, C_BG2).convert("RGBA")
    draw = ImageDraw.Draw(img)
    cx = cy = size // 2
    r  = size // 2 - 6

    # Green circle
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=C_GREEN)
    draw.ellipse([cx - r + 10, cy - r + 10, cx + r - 10, cy + r - 10],
                 fill=C_LIGHT_GRN)

    # Small wallet icon
    ww = int(size * 0.52)
    wh = int(size * 0.38)
    draw_wallet(draw, cx, cy, ww, wh,
                body_col   = C_WHITE,
                pocket_col = C_CARD_TINT,
                coin_col   = C_MINT,
                symbol_col = C_GREEN)
    return img.convert("RGB")


# ─── Generate & Save ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    os.makedirs(ASSETS_DIR, exist_ok=True)

    tasks = [
        ("icon.png",          create_icon),
        ("adaptive-icon.png", create_adaptive_icon),
        ("splash.png",        create_splash),
        ("favicon.png",       create_favicon),
    ]

    for filename, fn in tasks:
        out_path = os.path.join(ASSETS_DIR, filename)
        result = fn()
        result.save(out_path)
        print(f"  saved  {out_path}")

    print("\nAll Genglo logo assets generated.")
