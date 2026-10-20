"""Registro paper. Apre e chiude operazioni DA SOLO, su regole scritte prima.

Perche' paper e non soldi veri: goldbot, stesso rigore, in-sample PF 4.90 e
fuori campione 0.99. Il numero out-of-sample e' l'unico che conta. Qui si
produce quel numero, prima di toccare una chiave.

Regola (dichiarata, non nascosta):
- ingresso: rottura del massimo/minimo del giorno precedente (momentum).
- stop: 1.5 x ATR(14) contro. target: 3 x ATR(14). rapporto 1:2.
- time stop: dopo 5 giorni di borsa la posizione si chiude al close.
- una posizione aperta per simbolo. mai pyramiding.
Se il motore perde o la fonte cade, il simbolo resta assente. mai inventato.
"""
import json
import os
import sys
from datetime import datetime, timezone

from .http import get_json

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATE = os.path.join(ROOT, "paper_state.json")

ATR_N = 14
STOP_ATR = 1.5
TARGET_ATR = 3.0
MAX_BARS = 5


def ohlc(sym, rng="6mo"):
    d = get_json(f"https://query2.finance.yahoo.com/v8/finance/chart/{sym}"
                 f"?range={rng}&interval=1d", tries=3)
    r = d["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    rows = []
    for i, c in enumerate(q["close"]):
        h, l, o = q["high"][i], q["low"][i], q["open"][i]
        if None in (c, h, l, o):
            continue
        rows.append({"o": o, "h": h, "l": l, "c": c})
    return rows


def atr(rows, n=ATR_N):
    if len(rows) < n + 1:
        return None
    trs = []
    for i in range(1, len(rows)):
        p, r = rows[i - 1]["c"], rows[i]
        trs.append(max(r["h"] - r["l"], abs(r["h"] - p), abs(r["l"] - p)))
    w = trs[-n:]
    return sum(w) / len(w)


def load():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"open": {}, "closed": []}


def save(s):
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)


def _r(entry, exit_, stop, side):
    """P&L in R (multipli del rischio iniziale)."""
    risk = abs(entry - stop)
    if risk == 0:
        return 0.0
    pnl = (exit_ - entry) if side == "long" else (entry - exit_)
    return pnl / risk


def step(symbols, s=None, dry=False):
    """Un giro: prima chiude quello che va chiuso, poi apre le nuove rotture."""
    s = s or load()
    now = datetime.now(timezone.utc).isoformat(timespec="minutes")
    events = []

    for sym in symbols:
        try:
            rows = ohlc(sym)
        except Exception as e:
            events.append(f"{sym}: fonte giu ({type(e).__name__})")
            continue
        if len(rows) < ATR_N + 2:
            continue
        a = atr(rows)
        if not a:
            continue
        last, prev = rows[-1], rows[-2]
        pos = s["open"].get(sym)

        if pos:
            pos["bars"] = pos.get("bars", 0) + 1
            exit_ = None
            if pos["side"] == "long":
                if last["l"] <= pos["stop"]:
                    exit_ = pos["stop"]
                elif last["h"] >= pos["target"]:
                    exit_ = pos["target"]
            else:
                if last["h"] >= pos["stop"]:
                    exit_ = pos["stop"]
                elif last["l"] <= pos["target"]:
                    exit_ = pos["target"]
            if exit_ is None and pos["bars"] >= MAX_BARS:
                exit_ = last["c"]
                pos["reason"] = "time"
            if exit_ is not None:
                pos.update({"exit": exit_, "exit_ts": now,
                            "r": round(_r(pos["entry"], exit_, pos["stop"], pos["side"]), 3)})
                pos.setdefault("reason", "stop/target")
                s["closed"].append(pos)
                del s["open"][sym]
                events.append(f"{sym}: chiusa {pos['side']} @ {exit_:.4f} -> {pos['r']:+.2f}R ({pos['reason']})")
            continue

        # nessuna posizione: cerco una rottura della barra precedente
        if last["c"] > prev["h"]:
            side, entry, stop, tgt = "long", last["c"], last["c"] - STOP_ATR * a, last["c"] + TARGET_ATR * a
        elif last["c"] < prev["l"]:
            side, entry, stop, tgt = "short", last["c"], last["c"] + STOP_ATR * a, last["c"] - TARGET_ATR * a
        else:
            continue
        s["open"][sym] = {
            "symbol": sym, "side": side, "entry": entry,
            "stop": stop, "target": tgt, "atr": a, "bars": 0,
            "entry_ts": now, "reason": "",
        }
        events.append(f"{sym}: aperta {side} @ {entry:.4f} stop {stop:.4f} target {tgt:.4f}")

    if not dry:
        save(s)
    return s, events


def report(s=None):
    s = s or load()
    closed = s["closed"]
    if not closed:
        return "Registro paper: 0 operazioni chiuse."
    rs = [t["r"] for t in closed]
    wins = [r for r in rs if r > 0]
    exp = sum(rs) / len(rs)
    peak = dd = 0.0
    eq = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    return (f"Registro paper: {len(rs)} chiuse, hit {len(wins)/len(rs)*100:.0f}%, "
            f"expectancy {exp:+.2f}R, max drawdown {dd:.2f}R, aperte {len(s['open'])}")


if __name__ == "__main__":
    syms = json.load(open(os.path.join(ROOT, "private_cfg.json"), encoding="utf-8"))["symbols"]
    st, ev = step(syms, dry="--dry" in sys.argv)
    for e in ev:
        print(e)
    print(report(st))
