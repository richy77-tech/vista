"""Indicatori tecnici, calcolati su barre reali. Nessun numero inventato.

Riutilizza rsi/ma da marketdata (una sola implementazione, non due). Qui
stanno EMA, pendenza, ATR e lo stato del mercato. Uno stato e' una lettura di
cosa sta facendo adesso, non una previsione.
"""
from .marketdata import rsi, ma  # noqa: F401  (rsi e ma restano raggiungibili da qui)


def ema(vals, n):
    if not vals or len(vals) < n:
        return None
    k = 2.0 / (n + 1)
    e = sum(vals[:n]) / n
    for v in vals[n:]:
        e = v * k + e * (1 - k)
    return e


def ema_series(vals, n):
    if not vals or len(vals) < n:
        return []
    k = 2.0 / (n + 1)
    e = sum(vals[:n]) / n
    out = [e]
    for v in vals[n:]:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def slope(vals, n=5):
    """Pendenza normalizzata negli ultimi n passi. Segno = direzione, non livello."""
    if not vals or len(vals) < n + 1 or vals[-n - 1] == 0:
        return None
    return (vals[-1] - vals[-n - 1]) / abs(vals[-n - 1])


def atr(rows, n=14):
    if len(rows) < n + 1:
        return None
    trs = []
    for i in range(1, len(rows)):
        prev, r = rows[i - 1]["c"], rows[i]
        trs.append(max(r["h"] - r["l"], abs(r["h"] - prev), abs(r["l"] - prev)))
    w = trs[-n:]
    return sum(w) / len(w)


def atr_pct(rows, n=14):
    a = atr(rows, n)
    if not a or not rows[-1]["c"]:
        return None
    return a / rows[-1]["c"] * 100.0


def regime(closes, fast=50, slow=200, n=10):
    """Stato del mercato, dichiarato: su / giu' / piatto / n/d.

    su  = EMA veloce sopra EMA lenta e in salita.
    giu = EMA veloce sotto EMA lenta e in discesa.
    piatto = tutto il resto (medie incrociate o pendenza contraria).
    """
    ef, es = ema(closes, fast), ema(closes, slow)
    if ef is None or es is None:
        return {"state": "n/d", "ema_fast": ef, "ema_slow": es, "slope": None}
    sg = slope(ema_series(closes, fast), n)
    if ef > es and (sg is None or sg > 0):
        state = "su"
    elif ef < es and (sg is None or sg < 0):
        state = "giu"
    else:
        state = "piatto"
    return {"state": state, "ema_fast": ef, "ema_slow": es, "slope": sg}
