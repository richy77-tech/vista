"""Metriche per asset, da dati reali. Quello che non ha una fonte gratuita lo
dichiara assente, non lo riempie a caso.

Copre, per ogni asset seguito:
- comunanza (correlazione col resto del paniere: il "trend intraday" condiviso)
- volume medio giornaliero (dove la fonte lo espone)
- volatilita' annualizzata e beta sul riferimento (S&P 500)
- supporti e resistenze (min/max a 20 e 60 barre + pivot di ieri)
- CCI e MACD (gli indicatori che non stavano da nessuna parte)
- split e dividendi (solo se la fonte li ha davvero)
- open interest su WTI/Brent: NON coperto, non esiste feed gratuito

Piu' due cose che erano chieste a parte: il piano di gestione del denaro
(% di rischio a operazione) e il backtest della regola in uso, in/out of sample.
"""
import json
import math
import os
from datetime import datetime, timezone

from .http import get_json
from . import indicators as ind
from . import marketdata as md
from . import tunables as T
from .paper import ohlc

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BENCH = "^GSPC"
UNCOVERED = ("open interest WTI/Brent: nessun feed gratuito pubblico, "
             "voce lasciata scoperta invece di inventarla")


# ---------------------------------------------------------------- matematica
def _rets(closes):
    return [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))
            if closes[i - 1]]


def _stdev(xs):
    n = len(xs)
    if n < 2:
        return None
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def _corr(a, b):
    n = min(len(a), len(b))
    if n < 10:
        return None
    a, b = a[-n:], b[-n:]
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((x - mb) ** 2 for x in b)
    if va <= 0 or vb <= 0:
        return None
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    return cov / math.sqrt(va * vb)


def beta(rs, brs):
    n = min(len(rs), len(brs))
    if n < 20:
        return None
    rs, brs = rs[-n:], brs[-n:]
    mr, mb = sum(rs) / n, sum(brs) / n
    var = sum((b - mb) ** 2 for b in brs)
    if var <= 0:
        return None
    cov = sum((rs[i] - mr) * (brs[i] - mb) for i in range(n))
    return cov / var


# ------------------------------------------------------------------- helper
def labels():
    out = {}
    for g in md.GROUPS.values():
        for sym, lab, _ in g:
            out[sym] = lab
    out["BTC-USD"] = "BITCOIN"
    out["ETH-USD"] = "ETHEREUM"
    return out


def _cfg():
    try:
        return json.load(open(os.path.join(ROOT, "private_cfg.json"), encoding="utf-8"))
    except Exception:
        return {"symbols": []}


def _avg(vols, n):
    w = [v for v in vols[-n:] if v]
    return sum(w) / len(w) if w else None


def _fmt_big(v):
    if v is None:
        return "n/d"
    if v >= 1e9:
        return f"{v/1e9:.2f}Mld"
    if v >= 1e6:
        return f"{v/1e6:.1f}Mln"
    if v >= 1e3:
        return f"{v/1e3:.0f}k"
    return f"{v:.0f}"


def _fmt_px(p):
    if p is None:
        return "n/d"
    if p >= 1000:
        return f"{p:,.0f}"
    if p >= 10:
        return f"{p:,.2f}"
    return f"{p:.4f}"


_BENCH = {}


def _bench_rets():
    if "r" not in _BENCH:
        try:
            _BENCH["r"] = _rets([r["c"] for r in ohlc(BENCH, rng="1y")])
        except Exception:
            _BENCH["r"] = []
    return _BENCH["r"]


# ------------------------------------------------------------------- pezzi
def levels(rows, n=20):
    if not rows:
        return None
    seg = rows[-n:] if len(rows) >= n else rows
    last = rows[-1]
    p = (last["h"] + last["l"] + last["c"]) / 3
    return {"hi": max(r["h"] for r in seg), "lo": min(r["l"] for r in seg),
            "pivot": p, "r1": 2 * p - last["l"], "s1": 2 * p - last["h"]}


def events(sym, rng="2y"):
    """Split e dividendi, se Yahoo li espone per quel simbolo."""
    try:
        d = get_json(f"https://query2.finance.yahoo.com/v8/finance/chart/{sym}"
                     f"?range={rng}&interval=1d&events=div%2Csplit", tries=2)
        ev = d["chart"]["result"][0].get("events") or {}
    except Exception:
        return {"dividends": [], "splits": []}
    divs = [v.get("amount") for v in (ev.get("dividends") or {}).values()]
    spls = [f"{v.get('numerator')}:{v.get('denominator')}"
            for v in (ev.get("splits") or {}).values()]
    return {"dividends": divs[-4:], "splits": spls[-3:]}


def comunanza(symbols=None, n=60, rets=None):
    """Per ogni asset, quanto si muove col resto del paniere.
    +1 = stessa direzione, 0 = indipendente, -1 = opposto."""
    if rets is None:
        rets = {}
        for s in symbols or []:
            try:
                rows = ohlc(s, rng="6mo")
            except Exception:
                continue
            c = [r["c"] for r in rows]
            if len(c) > 20:
                rets[s] = _rets(c)
    if len(rets) < 2:
        return {}, {}
    n = min(n, min(len(v) for v in rets.values()))
    avg = []
    for i in range(-n, 0):
        vals = [v[i] for v in rets.values() if len(v) >= -i]
        if vals:
            avg.append(sum(vals) / len(vals))
    out = {s: _corr(v[-n:], avg) for s, v in rets.items()}
    # forza del trend condiviso: quanto e' convinto il paniere in media
    ref = sum(v[-1] for v in rets.values()) / len(rets)
    return out, {"ref_day": ref, "avg": (sum(avg) / len(avg) if avg else None)}


def asset(sym):
    rows = ohlc(sym, rng="1y")
    closes = [r["c"] for r in rows]
    vols = [r["v"] for r in rows]
    rs = _rets(closes)
    a = {"sym": sym, "last": closes[-1] if closes else None,
         "rsi": md.rsi(closes), "cci": ind.cci(rows), "macd": ind.macd(closes),
         "vol_pct": (round(_stdev(rs[-60:]) * math.sqrt(252) * 100, 2)
                     if len(rs) > 20 else None),
         "vol_avg20": _avg(vols, 20), "vol_avg60": _avg(vols, 60),
         "levels20": levels(rows, 20), "levels60": levels(rows, 60),
         "events": events(sym), "rs": rs}
    a["beta"] = beta(rs, _bench_rets())
    return a


# ------------------------------------------------------------------- testi
def asset_text(sym):
    lab = labels().get(sym, sym)
    try:
        a = asset(sym)
    except Exception as e:
        return f"{lab}: fonte giu ({type(e).__name__})."
    L = [f"<b>{lab} ({sym})</b> · ultimo {_fmt_px(a['last'])}"]
    bits = []
    if a["rsi"] is not None:
        bits.append(f"RSI {a['rsi']:.0f}")
    if a["cci"] is not None:
        tag = " (estremo)" if abs(a["cci"]) >= 200 else ""
        bits.append(f"CCI {a['cci']:.0f}{tag}")
    if a["macd"] and a["macd"].get("hist") is not None:
        m = a["macd"]
        tag = "rialzista" if m["hist"] > 0 else "ribassista"
        bits.append(f"MACD {m['line']:.3g}/{m['signal']:.3g} {tag}")
    if bits:
        L.append(", ".join(bits))
    v = a["vol_pct"]
    b = a["beta"]
    tail = []
    if v is not None:
        tail.append(f"volatilità {v:.1f}% annua")
    if b is not None:
        tail.append(f"beta {b:.2f} su S&P")
    if tail:
        L.append(", ".join(tail))
    L.append(f"Volume medio: 20g {_fmt_big(a['vol_avg20'])} · 60g {_fmt_big(a['vol_avg60'])}")
    l20, l60 = a["levels20"], a["levels60"]
    if l20 and l60:
        L.append(f"Resistenze: 20g {_fmt_px(l20['hi'])} · 60g {_fmt_px(l60['hi'])}")
        L.append(f"Supporti: 20g {_fmt_px(l20['lo'])} · 60g {_fmt_px(l60['lo'])}")
        L.append(f"Pivot ieri: P {_fmt_px(l20['pivot'])} · S1 {_fmt_px(l20['s1'])} · R1 {_fmt_px(l20['r1'])}")
    ev = a["events"]
    if ev["splits"] or ev["dividends"]:
        d = ", ".join(str(x) for x in ev["dividends"][-2:]) or "nessuno"
        s = ", ".join(ev["splits"]) or "nessuno"
        L.append(f"Dividendi recenti: {d} · split: {s}")
    else:
        L.append("Split/dividendi: nessun evento dalla fonte")
    L.append(UNCOVERED)
    return "\n".join(L)


def money_plan(symbols, capital=None, risk_pct=None, rows_map=None):
    capital = capital or T.p("capital_eur", 100.0)
    rp = min(risk_pct or T.p("risk_pct", 1.0), T.p("max_risk_pct", 5.0))
    risk_eur = capital * rp / 100.0
    stop_atr = T.p("stop_atr", 1.5)
    L = ["<b>Gestione del denaro</b> (simulazione, nessun conto reale)",
         f"Capitale {capital:.0f}€ · rischio {rp:.1f}% a operazione = {risk_eur:.2f}€",
         f"Stop = {stop_atr}×ATR · target {T.p('target_atr', 3.0)}×ATR (1:2) · "
         f"size = rischio / stop in punti"]
    lab = labels()
    for s in symbols:
        try:
            rows = (rows_map or {})[s] if rows_map and s in rows_map else ohlc(s, rng="1y")
            atr = ind.atr(rows)
            px = rows[-1]["c"]
        except Exception:
            continue
        if not atr or not px:
            continue
        stop_pts = stop_atr * atr
        L.append(f"• {lab.get(s, s)}: stop {stop_pts/px*100:.2f}% → "
                 f"{risk_eur/stop_pts:.4g} unità")
    L.append("Tetto: max 5% di capitale a rischio; a 1% a testa = max 5 posizioni insieme.")
    return "\n".join(L)


def backtest_summary(symbols=None, refresh=False):
    """Backtest della regola in uso, in/out of sample. Cache giornaliera."""
    path = os.path.join(ROOT, "metrics_bt.json")
    today = datetime.now(timezone.utc).date().isoformat()
    if not refresh:
        try:
            c = json.load(open(path, encoding="utf-8"))
            if c.get("date") == today:
                return c
        except Exception:
            pass
    from .backtest import replay, _stats
    symbols = symbols or _cfg().get("symbols") or []
    rows = []
    for sym in symbols:
        try:
            o = ohlc(sym, rng="3y")
        except Exception:
            continue
        if len(o) < 300:
            continue
        split = int(len(o) * 0.7)
        b_is, b_oos = replay(o, split=split)
        rows.append({"sym": sym, "is": _stats(b_is), "oos": _stats(b_oos)})
    out = {"date": today, "rows": rows}
    try:
        json.dump(out, open(path, "w", encoding="utf-8"), indent=1)
    except Exception:
        pass
    return out


def backtest_text(symbols=None):
    b = backtest_summary(symbols)
    rows = b.get("rows") or []
    if not rows:
        return "Backtest: nessun dato sufficiente."
    def agg(k):
        n = sum(r[k]["n"] for r in rows)
        rsum = sum(r[k]["r"] for r in rows)
        return n, rsum, (rsum / n if n else 0.0)
    ni, ri, ei = agg("is")
    no, ro, eo = agg("oos")
    pos = sum(1 for r in rows if r["oos"]["n"] >= 5 and r["oos"]["exp"] > 0)
    tested = sum(1 for r in rows if r["oos"]["n"] >= 5)
    L = ["<b>Backtest della regola attuale</b> (rottura, stop 1.5×ATR, target 3×ATR, time stop 5 barre)",
         f"In-sample: {ni} op · {ri:+.1f}R · attesa {ei:+.3f}R/op",
         f"Out-of-sample: {no} op · {ro:+.1f}R · attesa {eo:+.3f}R/op",
         f"Simboli con attesa OOS positiva: {pos}/{tested}"]
    if eo <= 0:
        L.append("Lettura: fuori campione non c'è vantaggio. È il numero che conta, non quello in-sample.")
    return "\n".join(L)


def report(symbols=None, capital=None, risk_pct=None):
    symbols = symbols or _cfg().get("symbols") or []
    lab = labels()
    L = ["<b>METRICHE</b> — " + datetime.now(timezone.utc).strftime("%d/%m %H:%M UTC")]

    # Una passata sola per asset: una chiamata alla fonte, tutti i numeri.
    data, rets, rows_map = {}, {}, {}
    for s in symbols:
        try:
            rows = ohlc(s, rng="1y")
        except Exception:
            continue
        closes = [r["c"] for r in rows]
        if len(closes) < 60:
            continue
        rs = _rets(closes)
        data[s] = {
            "vol_pct": round(_stdev(rs[-60:]) * math.sqrt(252) * 100, 2),
            "beta": beta(rs, _bench_rets()),
            "vol_avg20": _avg([r["v"] for r in rows], 20),
        }
        rets[s] = rs
        rows_map[s] = rows

    com, extra = comunanza(rets=rets)
    if com:
        L.append("")
        L.append("<b>Comunanza</b> (correlazione col paniere, 60g)")
        for s, v in sorted(com.items(), key=lambda x: -(x[1] or 0)):
            if v is None:
                continue
            L.append(f"• {lab.get(s, s)}: {v*100:+.0f}%")
        if extra.get("ref_day") is not None:
            tone = "rialzista" if extra["ref_day"] > 0 else "ribassista"
            L.append(f"Paniere oggi: {tone} ({extra['ref_day']*100:+.2f}% medio)")

    L.append("")
    L.append("<b>Volatilità, beta e volume medio</b> (beta su S&P 500)")
    for s in symbols:
        d = data.get(s)
        if not d:
            L.append(f"• {lab.get(s, s)}: fonte giu")
            continue
        v = f"{d['vol_pct']:.1f}%" if d["vol_pct"] is not None else "n/d"
        b = f"{d['beta']:.2f}" if d["beta"] is not None else "n/d"
        L.append(f"• {lab.get(s, s)}: vol {v} · beta {b} · vol.medio {_fmt_big(d['vol_avg20'])}")

    L.append("")
    L.append(backtest_text(symbols))
    L.append("")
    L.append(money_plan(symbols, capital, risk_pct, rows_map=rows_map))
    L.append("")
    L.append(UNCOVERED)
    return "\n".join(L)


def handle(text, cfg, find_symbols=None):
    syms = find_symbols(text) if find_symbols else []
    if syms:
        return asset_text(syms[0])
    return report(cfg.get("symbols"))
