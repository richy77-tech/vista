"""Trigger sulle notizie: apre un'operazione paper quando la notizia e' forte
E il prezzo si sta gia' muovendo nella stessa direzione.

Notizia senza movimento = rumore. Movimento senza notizia = rottura, gia'
coperta da paper.py. Le due cose insieme sono la sola cosa che questo modulo
tratta come segnale.

Regola dichiarata, non nascosta:
- news con impact HIGH o CRITICAL
- sentiment bullish o bearish (non neutro)
- asset mappato a un simbolo che seguiamo
- movimento di oggi nella stessa direzione >= SOGLIA_PCT
- stop 1.5xATR, target 3xATR (come paper.py), una posizione per simbolo
- una news resta "viva" RETIRE_H ore: se in quella finestra il movimento non
  arriva, va in pensione e non la rivediamo piu'. Mai forzata.
"""
import os
from datetime import datetime, timezone

from . import marketdata as md
from . import paper
from . import exec as ex

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

SOGLIA_PCT = 0.35
RETIRE_H = 6
MAX_SEEN = 600

ASSET_TO_SYM = {
    "BTC": "BTC-USD", "ETH": "ETH-USD",
    "GOLD": "GC=F", "SILVER": "SI=F", "OIL": "CL=F",
    "USD": "DX-Y.NYB", "EUR": "EURUSD=X", "JPY": "JPY=X", "GBP": "GBPUSD=X",
    "EQUITIES": "^GSPC", "VIX": "^VIX",
}


def candidates(news, symbols):
    """(simbolo, side, titolo, id) dalle news forti con sentiment direzionale."""
    out = []
    for n in news or []:
        if n.get("impact") not in ("HIGH", "CRITICAL"):
            continue
        lab = (n.get("sentiment") or {}).get("label")
        if lab not in ("bullish", "bearish"):
            continue
        side = "long" if lab == "bullish" else "short"
        for a in n.get("assets") or []:
            sym = ASSET_TO_SYM.get(a)
            if sym in symbols:
                out.append((sym, side, n.get("title", ""), n.get("id")))
    return out


def _age_h(ts):
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    except Exception:
        return 0.0


def run(symbols, news, dry=False):
    """Un giro del trigger. Ritorna (stato, eventi)."""
    s = paper.load()
    seen = s.get("seen_news") or []
    seen_set = set(seen)
    now = datetime.now(timezone.utc).isoformat(timespec="minutes")
    events = []

    for n in news or []:
        nid = n.get("id")
        if nid and nid not in seen_set and _age_h(n.get("ts", "")) > RETIRE_H:
            seen.append(nid)
            seen_set.add(nid)

    for sym, side, title, nid in candidates(news, symbols):
        if nid and nid in seen_set:
            continue
        if sym in s["open"]:
            continue
        try:
            q = md.yahoo(sym)
            ch = md.change_pct(q)
            rows = paper.ohlc(sym)
        except Exception as e:
            events.append(f"{sym}: fonte giu ({type(e).__name__})")
            continue
        a = paper.atr(rows) if rows else None
        if ch is None or not a or not rows or len(rows) < paper.ATR_N + 2 or not q.get("price"):
            continue
        if side == "long" and ch < SOGLIA_PCT:
            continue
        if side == "short" and ch > -SOGLIA_PCT:
            continue
        entry = q["price"]
        stop = entry - paper.STOP_ATR * a if side == "long" else entry + paper.STOP_ATR * a
        tgt = entry + paper.TARGET_ATR * a if side == "long" else entry - paper.TARGET_ATR * a
        s["open"][sym] = {
            "symbol": sym, "side": side, "entry": entry, "stop": stop,
            "target": tgt, "atr": a, "bars": 0, "entry_ts": now,
            "reason": "news+movimento", "news_id": nid, "headline": title[:120],
        }
        # l'intento passa dal tubo di esecuzione (oggi: adapter paper)
        try:
            s["open"][sym]["exec"] = ex.get().place(
                sym, side, qty=None, stop=stop, target=tgt,
                meta={"reason": "news+movimento", "news_id": nid})
        except Exception as e:
            s["open"][sym]["exec"] = {"rejected": str(e)}
        events.append(
            f"{sym}: aperta {side} @ {entry:.4f} ({ch:+.2f}% oggi) su notizia — {title[:70]}")

    s["seen_news"] = seen[-MAX_SEEN:]
    if not dry:
        paper.save(s)
    return s, events


if __name__ == "__main__":
    import json
    import sys
    cfg = json.load(open(os.path.join(ROOT, "private_cfg.json"), encoding="utf-8"))
    if "--sample" in sys.argv:
        news = [{"id": "test", "impact": "HIGH", "ts": datetime.now(timezone.utc).isoformat(),
                 "sentiment": {"label": "bullish"}, "assets": ["GOLD"],
                 "title": "sample: oro in rialzo"}]
        st, ev = run(cfg["symbols"], news, dry=True)
        for e in ev:
            print(e)
    else:
        from . import newsengine as ne
        news, err = ne.pipeline(per_source=8)
        st, ev = run(cfg["symbols"], news)
        for e in ev:
            print(e)
        print(f"news lette: {len(news)}, errori fonti: {len(err)}")
