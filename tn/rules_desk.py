"""Desk a sole regole di prezzo: la variante senza notizie, per un confronto onesto.

Perche' esiste: il desk a tre ruoli decide su una notizia piu' un breakout. Le due
cose non si possono separare all'indietro (l'archivio delle notizie non c'e'), e
infatti il suo numero resta una sensazione. Il prezzo invece si puo' rileggere
anni. Qui le regole sono dichiarate, non ottimizzate, e il registro e' separato:
stesso denaro finto, stesse candele, stesse uscite (stop/target/tempo da
paper.step). Dopo un centinaio di chiusure si confrontano due medie in R.

Regole, scritte prima di guardare il risultato:
  - trend non piatto, e dalla parte dell'operazione (EMA50/EMA200, pendenza)
  - movimento di oggi almeno nt.SOGLIA_PCT nella direzione
  - RSI non gia' in estremo (long sotto 70, short sopra 30)
  - entra il candidato con il movimento piu' forte, uno per giro
  - stop 1.5 ATR, target 3 ATR, R/R 1.5 minimo, poi il risk manager della suite
"""
import json
import os
from datetime import datetime, timezone

from . import indicators as ind
from . import newstrigger as nt
from . import paper
from . import risk

STATE = paper.STATE_RULES
LOG = os.path.join(paper.ROOT, "rules_log.jsonl")
MAX_OPEN = 2
MAX_PER_SYM_DAY = 2
RR_MIN = 1.5
RSI_LONG_MAX = 70
RSI_SHORT_MIN = 30


def _snap(sym):
    """Un solo scaricamento per asset (1y): prezzo, trend, RSI, ATR, movimento."""
    try:
        rows = paper.ohlc(sym, rng="1y")
    except Exception:
        return None
    if len(rows) < 60:
        return None
    closes = [r["c"] for r in rows]
    a = ind.atr(rows)
    if not a:
        return None
    last, prev = rows[-1], rows[-2]
    return {"sym": sym, "lab": paper.label(sym), "price": last["c"],
            "change": (last["c"] - prev["c"]) / prev["c"] * 100.0 if prev["c"] else None,
            "trend": ind.regime(closes).get("state"),
            "rsi": ind.rsi(closes, 14), "atr": a,
            "hi20": max(r["h"] for r in rows[-20:]),
            "lo20": min(r["l"] for r in rows[-20:])}


def _side(s):
    """Il lato che le regole consentono, o None. Nessuna scelta discrezionale."""
    ch = s.get("change")
    if ch is None or s.get("rsi") is None or abs(ch) < nt.SOGLIA_PCT:
        return None
    if s["trend"] == "su" and ch > 0 and s["rsi"] < RSI_LONG_MAX:
        return "long"
    if s["trend"] == "giu" and ch < 0 and s["rsi"] > RSI_SHORT_MIN:
        return "short"
    return None


def _today_count(st, sym):
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    n = 0
    for t in (st.get("closed") or [])[-400:]:
        if t.get("symbol") == sym and str(t.get("entry_ts", "")).startswith(day):
            n += 1
    for p in (st.get("open") or {}).values():
        if p.get("symbol") == sym and str(p.get("entry_ts", "")).startswith(day):
            n += 1
    return n


def run(symbols, dry=False):
    """Un giro: chiude prima (paper.step, apertura chiusa), poi sceglie al massimo
    una entrata con le regole. Ritorna (stato, eventi, traccia)."""
    st = paper.load(STATE)
    # solo la parte di uscita: le entrate le decide questo modulo, non il trigger.
    st, closed_ev = paper.step(symbols, s=st, path=STATE, open_new=False, dry=dry)
    trace = {"closed": closed_ev, "dry": bool(dry)}

    cands = []
    for sym in symbols:
        s = _snap(sym)
        if not s:
            continue
        side = _side(s)
        if side:
            cands.append((side, s))
    if not cands:
        trace["skip"] = "nessun asset con trend e movimento concordi"
        _record("skip", trace)
        return st, closed_ev, trace

    cands.sort(key=lambda c: abs(c[1]["change"]), reverse=True)
    side, s = cands[0]
    entry = s["price"]
    stop = entry - paper.STOP_ATR * s["atr"] if side == "long" else entry + paper.STOP_ATR * s["atr"]
    tgt = entry + paper.TARGET_ATR * s["atr"] if side == "long" else entry - paper.TARGET_ATR * s["atr"]
    rr = paper._r(entry, tgt, stop, side)
    trace["pick"] = {"sym": s["sym"], "side": side, "rr": round(rr, 2),
                     "change": round(s["change"], 2), "trend": s["trend"], "rsi": round(s["rsi"], 1)}

    if s["sym"] in (st.get("open") or {}):
        trace["skip"] = f"{s['sym']}: gia' aperta"
        _record("skip", trace)
        return st, closed_ev, trace
    if len(st.get("open") or {}) >= MAX_OPEN:
        trace["skip"] = f"{len(st['open'])} aperte (max {MAX_OPEN})"
        _record("skip", trace)
        return st, closed_ev, trace
    if _today_count(st, s["sym"]) >= MAX_PER_SYM_DAY:
        trace["skip"] = f"{s['sym']}: quota giornaliera esaurita"
        _record("skip", trace)
        return st, closed_ev, trace
    if rr < RR_MIN:
        trace["skip"] = f"R/R {rr:.2f} sotto {RR_MIN}"
        _record("skip", trace)
        return st, closed_ev, trace

    rv = risk.vet(st, {"sym": s["sym"], "side": side, "entry": entry, "stop": stop,
                       "target": tgt}, closes=[])
    trace["risk"] = rv
    if rv["action"] == "block":
        trace["skip"] = f"risk: {rv['why']}"
        _record("skip", trace)
        return st, closed_ev, trace

    now = datetime.now(timezone.utc).isoformat(timespec="minutes")
    st["open"][s["sym"]] = {
        "symbol": s["sym"], "side": side, "entry": entry, "stop": stop, "target": tgt,
        "atr": s["atr"], "bars": 0, "entry_ts": now,
        "reason": f"regole: trend {s['trend']}, movimento {s['change']:+.2f}%",
        "headline": "", "rules": True,
        "context": {"trend": s["trend"], "rsi": s["rsi"], "change": s["change"]},
    }
    if not dry:
        paper.save(st, STATE)
    ev = [f"{s['lab']}: aperta {side} @ {entry:,.2f} (regole, R/R {rr:.2f})"]
    trace["opened"] = True
    _record("open", trace)
    return st, closed_ev + ev, trace


def _record(kind, trace):
    if trace.get("dry"):
        return
    try:
        rec = {"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
               "kind": kind, "pick": trace.get("pick"),
               "skip": (trace.get("skip") or "")[:160],
               "risk": (trace.get("risk") or {}).get("why")}
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def stats(n=0):
    """Media in R del registro a sole regole, per il confronto nel desk.html."""
    st = paper.load(STATE)
    closed = st.get("closed") or []
    rows = [float(c.get("r") or 0) for c in (closed[-n:] if n else closed)]
    moved = [r for r in rows if r != 0]
    wins = sum(1 for r in moved if r > 0)
    return {"n": len(rows), "moved": len(moved),
            "avg": round(sum(moved) / len(moved), 3) if moved else 0,
            "total": round(sum(rows), 1),
            "wr": round(100.0 * wins / len(moved)) if moved else 0,
            "open": len(st.get("open") or {})}