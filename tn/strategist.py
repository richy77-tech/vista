"""Ruolo 4, lo stratega. E' quello che mancava.

Gli altri tre ruoli rispondono a "cosa e' successo" (news), "il grafico regge la
tesi" (grafico) e "apro o salto" (convalidatore). Nessuno dei tre decide DOVE
entrare, e con che distanza. Finora entry, stop e target erano 1.5 e 3 ATR
fissi, uguali per un pullback e per un breakout: due cose diverse con la stessa
distanza di stop.

Lo stratega invece sceglie il tipo di ingresso in base a dove sta il prezzo
dentro il range a 20 giorni, guarda il timeframe settimanale per sapere se il
verso della notizia va controcorrente, e restituisce un piano. Poi il risk
manager puo' ancora bocciarlo: lo stratega propone, non autorizza.

Costo: una chiamata Yahoo per simbolo in piu' (settimanale), dietro la cache
condivisa con TTL 6 ore. Senza cache il giro costerebbe il doppio.
"""
import os

from . import marketdata as md
from . import indicators as ind
from . import paper
from . import cache

TTL_DAY = 20 * 60
TTL_WEEK = 6 * 3600
MIN_RR = 1.5


def _weekly_regime(sym):
    d = cache.get(f"wk:{sym}", TTL_WEEK,
                  lambda: md.yahoo(sym, rng="2y", interval="1wk"))
    closes = (d or {}).get("closes") or []
    if len(closes) < 60:
        return None
    return ind.regime(closes).get("state")


def _pos(p, lo, hi):
    if lo is None or hi is None or hi <= lo:
        return None
    return (p - lo) / (hi - lo)


def plan(sym, side, snap):
    """Piano di ingresso da numeri reali. Ritorna dict, mai numeri inventati."""
    if not snap or snap.get("price") is None or not snap.get("rows"):
        return {"ok": False, "why": "dati insufficienti per lo stratega"}
    rows = snap["rows"]
    entry_ref = snap["price"]
    a = paper.atr(rows) if rows else None
    if not a:
        return {"ok": False, "why": "ATR non disponibile"}
    hi, lo = snap.get("hi20"), snap.get("lo20")
    pos = _pos(entry_ref, lo, hi)
    wk = _weekly_regime(sym)

    # controcorrente sul settimanale: la notizia spinge in su, il trend vero va giu'.
    # Succede spesso, e costa caro: si salta, e lo si scrive.
    want = "su" if side == "long" else "giu"
    if wk and wk != want:
        return {"ok": False, "why": f"stratega: settimanale {wk}, tesi {side} controcorrente", "tf": wk}

    if pos is None:
        kind = "atr"
    elif pos >= 0.65:
        kind = "breakout"
    elif pos <= 0.40:
        kind = "pullback"
    else:
        return {"ok": False, "why": f"stratega: prezzo a meta' range 20g ({pos:.0%}), nessun ingresso", "tf": wk}

    if kind == "breakout":
        # entrare solo oltre il massimo/minimo di ieri: il breakout non pagato in anticipo
        entry = snap.get("prev_h") if side == "long" else snap.get("prev_l")
        if entry is None or (side == "long" and entry <= entry_ref) or (side == "short" and entry >= entry_ref):
            kind = "atr"
    if kind == "pullback":
        m = md.ma(snap["closes"], 20)
        if m and ((side == "long" and m < entry_ref) or (side == "short" and m > entry_ref)):
            entry = m
        else:
            kind = "atr"
    if kind == "atr":
        entry = entry_ref

    sw = min(r["l"] for r in rows[-5:]) if len(rows) >= 5 else None
    sh = max(r["h"] for r in rows[-5:]) if len(rows) >= 5 else None
    # Nel breakout si compra il livello rotto: il target non puo' essere il
    # livello che si sta rompendo (era il bug: R/R 0.76 su un ingresso giusto).
    # Il target si misura dal prezzo di ingresso, in ATR. Nel pullback si torna
    # al bordo alto/basso del range, che li' e' davvero il traguardo.
    far = paper.TARGET_ATR * a
    # Lo stop non e' lo stesso oggetto nei due casi. Nel pullback e' la struttura
    # (l'ultimo minimo/massimo a 5 barre): se salta quella, la tesi e' sbagliata.
    # Nel breakout l'invalidazione e' il ritorno sotto il livello rotto, e tenere
    # la struttura larga significherebbe rischiare il doppio per lo stesso trade.
    if side == "long":
        struct = (sw - 0.2 * a) if sw else entry - paper.STOP_ATR * a
        stop = max(struct, entry - 1.5 * a) if kind == "breakout" else struct
        stop = min(stop, entry - 0.5 * a)
        target = (hi if (kind == "pullback" and hi and hi > entry + MIN_RR * abs(entry - stop))
                  else entry + far)
    else:
        struct = (sh + 0.2 * a) if sh else entry + paper.STOP_ATR * a
        stop = min(struct, entry + 1.5 * a) if kind == "breakout" else struct
        stop = max(stop, entry + 0.5 * a)
        target = (lo if (kind == "pullback" and lo and lo < entry - MIN_RR * abs(entry - stop))
                  else entry - far)

    rr = paper._r(entry, target, stop, side)
    if rr < MIN_RR:
        return {"ok": False, "why": f"stratega: R/R {rr:.2f} sotto {MIN_RR}", "kind": kind, "tf": wk}
    return {"ok": True, "kind": kind, "tf": wk, "entry": entry, "stop": stop,
            "target": target, "atr": a, "rr": rr,
            "why": f"stratega: {kind} con settimanale {wk or 'n/d'}, R/R {rr:.2f}"}