"""Card immagine del brief privato: logo/etichetta + prezzo + variazione
+ mini-grafico + barra RSI. Stesso dato del testo, ma si guarda dal telefono.

Niente inventato: se un simbolo non ha chiusure, la riga lo dice.
"""
import io

from PIL import Image, ImageDraw, ImageFont

from . import marketdata as md

W = 900
PAD = 26
ROW_H = 62
BG = (13, 17, 23)
CARD = (22, 27, 34)
FG = (230, 237, 243)
MUT = (139, 148, 158)
UP = (63, 185, 80)
DOWN = (248, 81, 73)
FLAT = (139, 148, 158)
ACC = (88, 166, 255)


def _font(size, bold=False):
    path = ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    return ImageFont.truetype(path, size)


def _fmt(p):
    if p is None:
        return "n/d"
    if p >= 1000:
        return f"{p:,.0f}"
    if p >= 10:
        return f"{p:,.2f}"
    return f"{p:.4f}"


def _spark(dr, box, closes, color):
    x0, y0, x1, y1 = box
    pts = closes[-40:]
    if len(pts) < 2:
        return
    lo, hi = min(pts), max(pts)
    rng = (hi - lo) or 1
    n = len(pts)
    coords = []
    for i, c in enumerate(pts):
        x = x0 + (x1 - x0) * i / (n - 1)
        y = y1 - (y1 - y0) * (c - lo) / rng
        coords.append((x, y))
    dr.line(coords, fill=color, width=2, joint="curve")


def render(rows, title="BRIEF PRIVATO", subtitle="", footer=""):
    """rows: [{label, price, cur, chg, closes, rsi}] -> bytes PNG."""
    h = PAD + 54 + len(rows) * ROW_H + (34 if footer else 0) + PAD
    img = Image.new("RGB", (W, h), BG)
    dr = ImageDraw.Draw(img)

    dr.text((PAD, PAD), title, font=_font(26, True), fill=FG)
    if subtitle:
        wt = dr.textlength(title, font=_font(26, True))
        dr.text((PAD + wt + 14, PAD + 9), subtitle, font=_font(15), fill=MUT)

    y = PAD + 54
    f_lab = _font(19, True)
    f_px = _font(19, True)
    f_chg = _font(16, True)
    f_sub = _font(12)
    for r in rows:
        dr.rounded_rectangle((PAD - 6, y, W - PAD + 6, y + ROW_H - 10),
                             radius=10, fill=CARD)
        dr.text((PAD + 6, y + 8), r["label"], font=f_lab, fill=FG)
        chg = r.get("chg")
        color = FLAT if chg is None else (UP if chg > 0 else DOWN if chg < 0 else FLAT)
        _spark(dr, (PAD + 220, y + 12, PAD + 400, y + 42), r.get("closes") or [], color)

        # prezzo a destra
        px = f"{_fmt(r.get('price'))} {r.get('cur') or ''}".strip()
        wpx = dr.textlength(px, font=f_px)
        dr.text((W - PAD - 6 - wpx, y + 8), px, font=f_px, fill=FG)

        # variazione
        if chg is not None:
            arrow = "▲" if chg > 0 else ("▼" if chg < 0 else "=")
            ct = f"{arrow} {chg:+.2f}%"
            wct = dr.textlength(ct, font=f_chg)
            dr.text((W - PAD - 6 - wct, y + 34), ct, font=f_chg, fill=color)

        # barra RSI: colore per zona RSI (non per la variazione del giorno)
        rsi = r.get("rsi")
        if rsi is not None:
            rc = DOWN if rsi >= 70 else (UP if rsi <= 30 else ACC)
            bx0, bx1, by = PAD + 6, PAD + 200, y + 46
            dr.rectangle((bx0, by, bx1, by + 4), fill=(48, 54, 61))
            pen_x = bx0 + (bx1 - bx0) * min(max(rsi, 0), 100) / 100
            dr.rectangle((bx0, by, pen_x, by + 4), fill=rc)
            dr.text((bx0, by - 18), f"RSI {rsi:.0f}", font=f_sub, fill=MUT)
        y += ROW_H

    if footer:
        dr.text((PAD, h - PAD - 14), footer, font=_font(12), fill=MUT)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def brief_rows(symbols, labels):
    rows = []
    for s in symbols:
        try:
            q = md.yahoo(s)
        except Exception:
            rows.append({"label": labels.get(s, s), "price": None, "cur": None,
                         "chg": None, "closes": [], "rsi": None})
            continue
        rows.append({
            "label": labels.get(s, s),
            "price": q.get("price"),
            "cur": q.get("currency"),
            "chg": md.change_pct(q),
            "closes": q.get("closes") or [],
            "rsi": md.rsi(q.get("closes") or []),
        })
    return rows
