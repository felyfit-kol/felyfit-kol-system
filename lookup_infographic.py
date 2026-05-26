"""Genera una infografía PNG con el resumen del lookup de Stalkear.
Branding FelyFit: cream + blush + burgundy + Bowlby One.
Output: bytes PNG listos para st.download_button.
"""
import io
import os
from datetime import datetime
from typing import Dict, Optional

from PIL import Image, ImageDraw, ImageFont

# ============================================================
# Colores FelyFit (RGB)
# ============================================================
CREAM = (251, 244, 242)
BLUSH = (245, 221, 224)
ROSE = (229, 135, 154)
BURGUNDY = (114, 47, 55)
BURGUNDY_DEEP = (90, 31, 38)
PLUM = (61, 43, 48)
SAGE = (142, 165, 140)
SAGE_LIGHT = (229, 239, 224)
TERRACOTTA = (165, 108, 84)
MUTED_PLUM = (142, 90, 101)
WHITE = (255, 255, 255)

# ============================================================
# Paths
# ============================================================
HERE = os.path.dirname(os.path.abspath(__file__))
FONT_BOWLBY = os.path.join(HERE, "assets", "fonts", "BowlbyOne-Regular.ttf")
FONT_QUICKSAND = os.path.join(HERE, "assets", "fonts", "Quicksand-Regular.ttf")
LOGO_PATH = os.path.join(HERE, "assets", "logo.png")

# Canvas — portrait 4:5 ratio (compartible en IG)
W, H = 1080, 1350


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    """Carga font con fallback al default si no existe."""
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def _text(draw: ImageDraw.ImageDraw, xy, text: str, *, font, fill, anchor="lt") -> None:
    """Wrapper de draw.text con anchor por default."""
    draw.text(xy, text, font=font, fill=fill, anchor=anchor)


def _circle_image(im: Image.Image, size: int) -> Image.Image:
    """Recorta image a círculo del tamaño dado."""
    im = im.convert("RGB").resize((size, size))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    out = Image.new("RGBA", (size, size))
    out.paste(im, (0, 0), mask)
    return out


def _eval_color(metric: str, value, tier: Optional[str] = None) -> tuple:
    """Color sage/terracotta/plum según calidad vs ideal FelyFit."""
    if metric == "followers":
        n = int(value or 0)
        if n >= 10_000 and n <= 500_000: return SAGE
        if n < 10_000: return TERRACOTTA
        return BURGUNDY  # mega
    if metric == "er":
        er = float(value or 0)
        thresholds = {"nano": 0.035, "micro": 0.02, "mid": 0.015,
                       "macro": 0.01, "mega": 0.007}
        thresh = thresholds.get(tier or "micro", 0.025)
        if er >= thresh * 1.5: return SAGE
        if er >= thresh: return MUTED_PLUM
        return TERRACOTTA
    if metric == "fit":
        f = float(value or 0)
        if f >= 70: return SAGE
        if f >= 50: return MUTED_PLUM
        return TERRACOTTA
    if metric == "country":
        return SAGE if value == "MX" else TERRACOTTA
    if metric == "gender":
        return SAGE if value == "female" else TERRACOTTA
    if metric == "account_type":
        return SAGE if value == "individual" else TERRACOTTA
    return PLUM


def _draw_metric_card(
    draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int,
    label: str, value: str, value_color=PLUM,
    font_label=None, font_value=None,
) -> None:
    """Card blanca con borde blush, label arriba + valor abajo."""
    # Background
    draw.rounded_rectangle((x, y, x + w, y + h), radius=18, fill=WHITE,
                            outline=BLUSH, width=2)
    # Label
    _text(draw, (x + w // 2, y + 20), label.upper(),
          font=font_label, fill=MUTED_PLUM, anchor="mt")
    # Value
    _text(draw, (x + w // 2, y + h - 22), value,
          font=font_value, fill=value_color, anchor="mb")


def _wrap_text(text: str, font, max_width: int, draw: ImageDraw.ImageDraw) -> list:
    """Word-wrap básico para textos largos."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = (current + " " + word).strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def generate(
    cand: Dict,
    pred: Dict,
    *,
    chosen_collab_type: Optional[str] = None,
    chosen_collab_label: Optional[str] = None,
    content_counts: Optional[Dict[str, int]] = None,
    content_multiplier: float = 1.0,
    adjusted_emv: Optional[float] = None,
    cogs: Optional[float] = None,
    shipping: Optional[float] = None,
    cash: Optional[float] = None,
    target_ratio: float = 3.0,
    local_pic_path: Optional[str] = None,
) -> bytes:
    """Genera PNG del resumen. Devuelve bytes listos para download."""
    img = Image.new("RGB", (W, H), CREAM)
    draw = ImageDraw.Draw(img)

    # Fonts
    f_title    = _font(FONT_BOWLBY, 56)
    f_h2       = _font(FONT_BOWLBY, 36)
    f_h3       = _font(FONT_BOWLBY, 28)
    f_metric_v = _font(FONT_BOWLBY, 30)
    f_metric_l = _font(FONT_QUICKSAND, 14)
    f_body     = _font(FONT_QUICKSAND, 22)
    f_body_s   = _font(FONT_QUICKSAND, 18)
    f_caption  = _font(FONT_QUICKSAND, 16)
    f_handle   = _font(FONT_BOWLBY, 42)

    # ============== HEADER ==============
    # Burgundy band top
    draw.rectangle((0, 0, W, 110), fill=BURGUNDY)
    # Logo (si existe) + texto
    try:
        logo = Image.open(LOGO_PATH).convert("RGBA")
        logo.thumbnail((90, 90))
        img.paste(logo, (40, 10), logo)
    except Exception:
        pass
    _text(draw, (150, 55), "f*kol stalker analysis",
          font=f_h2, fill=BLUSH, anchor="lm")
    _text(draw, (W - 40, 55),
          datetime.now().strftime("%Y-%m-%d %H:%M"),
          font=f_caption, fill=BLUSH, anchor="rm")

    # ============== HERO: foto + handle ==============
    y0 = 150
    # Foto circular
    pic_size = 180
    pic_x, pic_y = 60, y0
    try:
        if local_pic_path and os.path.exists(local_pic_path):
            pic = Image.open(local_pic_path)
            circ = _circle_image(pic, pic_size)
            img.paste(circ, (pic_x, pic_y), circ)
    except Exception:
        # placeholder
        draw.ellipse((pic_x, pic_y, pic_x + pic_size, pic_y + pic_size),
                      fill=BLUSH)

    # Handle + nombre
    text_x = pic_x + pic_size + 30
    _text(draw, (text_x, y0 + 20),
          f"@{cand.get('handle', '?')}",
          font=f_handle, fill=PLUM)
    if cand.get("full_name"):
        _text(draw, (text_x, y0 + 80),
              cand["full_name"][:35],
              font=f_body, fill=MUTED_PLUM)
    # País + género en una línea (sin emojis — fonts no los soportan)
    country = cand.get("country") or "?"
    gender = cand.get("gender") or "?"
    _text(draw, (text_x, y0 + 120),
          f"{country}  ·  {gender}",
          font=f_body_s, fill=PLUM)
    # Tier badge
    tier = cand.get("tier") or "?"
    _text(draw, (text_x, y0 + 150),
          f"Tier: {tier.upper()}",
          font=f_body_s, fill=BURGUNDY)

    # ============== MÉTRICAS GRID 4 ==============
    y_metrics = 360
    card_w = (W - 60 - 60 - 30 * 3) // 4   # 4 cards con padding
    card_h = 110
    cards = [
        ("Followers", f"{int(cand.get('followers') or 0):,}",
         _eval_color("followers", cand.get("followers"))),
        ("ER", f"{float(cand.get('engagement_rate') or 0) * 100:.2f}%",
         _eval_color("er", cand.get("engagement_rate"), tier)),
        ("Fit Score", f"{float(cand.get('fit_score') or 0):.1f}",
         _eval_color("fit", cand.get("fit_score"))),
        ("Tier", tier.upper(),
         BURGUNDY if tier in ("mid", "macro", "micro") else PLUM),
    ]
    for i, (label, val, color) in enumerate(cards):
        x = 60 + i * (card_w + 30)
        _draw_metric_card(draw, x, y_metrics, card_w, card_h, label, val,
                           value_color=color,
                           font_label=f_metric_l, font_value=f_metric_v)

    # ============== RECOMENDACIÓN DEL ALGORITMO ==============
    y_rec = y_metrics + card_h + 30
    # Banner blush con label arriba y título grande abajo
    rec_h = 110
    draw.rounded_rectangle((60, y_rec, W - 60, y_rec + rec_h),
                            radius=18, fill=BLUSH)
    _text(draw, (W // 2, y_rec + 18),
          "RECOMENDACIÓN DEL ALGORITMO",
          font=f_metric_l, fill=BURGUNDY, anchor="mt")
    rec_label_clean = (pred.get("label", "") or "").split(": ", 1)[-1]
    _text(draw, (W // 2, y_rec + 60),
          rec_label_clean,
          font=f_h3, fill=BURGUNDY_DEEP, anchor="mt")

    # Rationale (wrap)
    y_rat = y_rec + rec_h + 20
    rationale = (pred.get("rationale", "") or "").replace("**", "")
    rationale_lines = _wrap_text(rationale, f_body_s, W - 140, draw)[:3]
    for i, line in enumerate(rationale_lines):
        _text(draw, (60, y_rat + i * 28), line, font=f_body_s, fill=PLUM)

    # ============== ESCENARIO (si la usuaria ajustó) ==============
    y_sc = y_rat + len(rationale_lines) * 28 + 30
    if chosen_collab_label or content_counts:
        draw.rounded_rectangle((60, y_sc, W - 60, y_sc + 250),
                                radius=18, fill=WHITE, outline=ROSE, width=2)
        _text(draw, (80, y_sc + 20), "ESCENARIO PROPUESTO",
              font=f_metric_l, fill=ROSE)
        # Collab type
        collab_clean = (chosen_collab_label or "").split(": ", 1)[-1] or "—"
        _text(draw, (80, y_sc + 50), f"Tipo: {collab_clean}",
              font=f_body, fill=PLUM)
        # Contenido
        if content_counts:
            pieces = []
            labels = {"reel": "Reel", "carousel": "Carousel", "post": "Post",
                       "live": "Live", "story": "Story"}
            for ct, n in content_counts.items():
                if n > 0:
                    pieces.append(f"{n}× {labels.get(ct, ct)}")
            if pieces:
                content_str = "Contenido: " + " + ".join(pieces)
            else:
                content_str = "Contenido: (ninguno seleccionado)"
            content_lines = _wrap_text(content_str, f_body_s, W - 200, draw)
            for i, line in enumerate(content_lines[:2]):
                _text(draw, (80, y_sc + 90 + i * 28), line,
                      font=f_body_s, fill=PLUM)
        # Multiplier
        _text(draw, (80, y_sc + 150),
              f"Multiplier contenido: {content_multiplier:.2f}× base EMV",
              font=f_body_s, fill=MUTED_PLUM)
        y_sc_end = y_sc + 250
    else:
        y_sc_end = y_sc

    # ============== BREAKDOWN ==============
    y_bd = y_sc_end + 30
    # Inversión + EMV side by side
    cogs_v = float(cogs or 0)
    ship_v = float(shipping or 0)
    cash_v = float(cash or 0)
    total_invest = cogs_v + ship_v + cash_v
    emv = float(adjusted_emv or pred.get("expected_emv") or 0)
    total_denom = max(cogs_v + ship_v + cash_v, 1)
    total_ratio = emv / total_denom

    # Card inversión
    inv_w = (W - 60 - 60 - 30) // 2
    inv_h = 240
    draw.rounded_rectangle((60, y_bd, 60 + inv_w, y_bd + inv_h),
                            radius=18, fill=WHITE, outline=BLUSH, width=2)
    _text(draw, (80, y_bd + 20), "INVERSIÓN (MXN)",
          font=f_metric_l, fill=MUTED_PLUM)
    _text(draw, (80, y_bd + 60), f"COGS PR pack", font=f_body_s, fill=PLUM)
    _text(draw, (60 + inv_w - 20, y_bd + 60), f"${cogs_v:,.0f}",
          font=f_body_s, fill=PLUM, anchor="rt")
    _text(draw, (80, y_bd + 100), f"Shipping", font=f_body_s, fill=PLUM)
    _text(draw, (60 + inv_w - 20, y_bd + 100), f"${ship_v:,.0f}",
          font=f_body_s, fill=PLUM, anchor="rt")
    _text(draw, (80, y_bd + 140), f"Cash fee", font=f_body_s, fill=PLUM)
    _text(draw, (60 + inv_w - 20, y_bd + 140), f"${cash_v:,.0f}",
          font=f_body_s, fill=PLUM, anchor="rt")
    # divider
    draw.line((80, y_bd + 180, 60 + inv_w - 20, y_bd + 180),
              fill=BLUSH, width=1)
    _text(draw, (80, y_bd + 200), "TOTAL", font=f_metric_l, fill=BURGUNDY)
    _text(draw, (60 + inv_w - 20, y_bd + 200),
          f"${total_invest:,.0f}",
          font=f_h3, fill=BURGUNDY_DEEP, anchor="rt")

    # Card EMV/ratios
    emv_x = 60 + inv_w + 30
    draw.rounded_rectangle((emv_x, y_bd, W - 60, y_bd + inv_h),
                            radius=18, fill=WHITE, outline=BLUSH, width=2)
    _text(draw, (emv_x + 20, y_bd + 20), "EMV + RATIOS",
          font=f_metric_l, fill=MUTED_PLUM)
    _text(draw, (emv_x + 20, y_bd + 50), "EMV proyectado",
          font=f_caption, fill=MUTED_PLUM)
    _text(draw, (emv_x + 20, y_bd + 75),
          f"${emv:,.0f}", font=f_h3, fill=BURGUNDY_DEEP)
    _text(draw, (emv_x + 20, y_bd + 125), "Total ratio",
          font=f_caption, fill=MUTED_PLUM)
    ratio_color = SAGE if total_ratio >= target_ratio else TERRACOTTA
    _text(draw, (emv_x + 20, y_bd + 150),
          f"{total_ratio:.2f}:1", font=f_h3, fill=ratio_color)
    # Verdict pill
    pill_y = y_bd + 195
    verdict_text = (f"CUMPLE TARGET {target_ratio:.0f}:1"
                     if total_ratio >= target_ratio
                     else f"DEBAJO DE {target_ratio:.0f}:1")
    fill_color = SAGE_LIGHT if total_ratio >= target_ratio else (252, 226, 220)
    text_color = SAGE if total_ratio >= target_ratio else TERRACOTTA
    draw.rounded_rectangle((emv_x + 20, pill_y, W - 80, pill_y + 32),
                            radius=16, fill=fill_color)
    _text(draw, (emv_x + 20 + (W - 80 - emv_x - 20) // 2, pill_y + 16),
          verdict_text, font=f_metric_l, fill=text_color, anchor="mm")

    # ============== FOOTER ==============
    footer_y = H - 50
    draw.rectangle((0, H - 60, W, H), fill=BURGUNDY)
    _text(draw, (40, footer_y), "felyfit · kol coordinator system",
          font=f_caption, fill=BLUSH, anchor="lm")
    _text(draw, (W - 40, footer_y),
          f"Auto-generated", font=f_caption, fill=BLUSH, anchor="rm")

    # Output
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
