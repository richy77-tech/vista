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


def _fmt(x):
    if x is None:
        return "n/d"
    ax = abs(x)
    return f"{x:,.4f}" if ax < 10 else (f"{x:,.2f}" if ax < 1000 else f"{x:,.0f}")


def _pl_emoji(x):
    if x is None:
        return "\u26aa"
    return "\U0001f7e2" if x > 0 else ("\U0001f534" if x < 0 else "\u26aa")


def _pct(entry, cur, side):
    if not entry or cur is None:
        return None
    d = (cur - entry) / entry * 100.0
    return d if side == "long" else -d


def screen(s=None, symbols=None, risk_eur=100.0):
    """Schermata operazioni, chiara e completa: badge verde/rosso, P/L aggiornato,
    tutte le info (entrata, prezzo ora, stop, target, barre, R, %, data)."""
    s = s or load()
    open_ = s.get("open") or {}
    closed = s.get("closed") or []
    L = ["<b>\U0001f4cb OPERAZIONI</b> \u00b7 registro paper (soldi veri fermi, nessun ordine vero)", ""]
    L.append("<b>Regola</b>: entro sulla rottura del max/min del giorno prima \u00b7 "
             "stop 1,5\u00d7ATR \u00b7 target 3\u00d7ATR \u00b7 chiudo a target, a stop o dopo 5 barre \u00b7 "
             "una posizione per asset.")
    L.append("")

    L.append(f"<b>\U0001f7e2 PRESE \u2014 aperte ora: {len(open_)}</b>")
    if not open_:
        L.append("\u2022 nessuna")
    else:
        for sym, p in open_.items():
            cur = None
            try:
                cur = ohlc(sym, rng="5d")[-1]["c"]
            except Exception:
                pass
            r_now = None if cur is None else _r(p["entry"], cur, p["stop"], p["side"])
            pc = _pct(p["entry"], cur, p["side"])
            emo = _pl_emoji(r_now)
            side = "LONG" if p["side"] == "long" else "SHORT"
            L.append(f"{emo} <b>{sym}</b> {side}")
            L.append(f"   entrata {_fmt(p['entry'])} \u2192 ora {_fmt(cur)}")
            L.append(f"   stop {_fmt(p['stop'])} \u00b7 target {_fmt(p['target'])} \u00b7 "
                     f"{p.get('bars', 0)}/5 barre")
            pl = []
            if r_now is not None:
                pl.append(f"{r_now:+.2f}R")
                pl.append(f"se rischiavi {risk_eur:.0f}\u20ac: {r_now * risk_eur:+.0f}\u20ac")
            if pc is not None:
                pl.append(f"{pc:+.2f}%")
            if pl:
                L.append("   P/L ora: " + " \u00b7 ".join(pl))
            L.append(f"   aperta {p.get('entry_ts', '')}")
    L.append("")

    watch = [x for x in (symbols or []) if x not in open_]
    L.append(f"<b>\U0001f7e1 NON PRESE \u2014 seguite, in attesa di segnale: {len(watch)}</b>")
    L.append("\u2022 " + (", ".join(watch) if watch else "nessuna"))
    L.append("")

    L.append(f"<b>Chiuse: {len(closed)}</b>")
    if not closed:
        L.append("\u2022 nessuna")
    else:
        rs = [t["r"] for t in closed]
        wins = [r for r in rs if r > 0]
        tot = sum(rs)
        L.append(f"\u2022 {len(rs)} totali \u00b7 {len(wins)} vinte (\U0001f7e2) \u00b7 "
                 f"{len(rs) - len(wins)} perse (\U0001f534) \u00b7 hit {len(wins) / len(rs) * 100:.0f}%")
        L.append(f"\u2022 risultato {tot:+.2f}R \u00b7 expectancy {tot / len(rs):+.2f}R \u00b7 "
                 f"se rischiavi {risk_eur:.0f}\u20ac/op: {tot * risk_eur:+.0f}\u20ac (simulazione)")
        for t in closed[-8:]:
            emo = _pl_emoji(t["r"])
            side = "LONG" if t["side"] == "long" else "SHORT"
            L.append(f"{emo} {t['symbol']} {side} {_fmt(t['entry'])}\u2192{_fmt(t.get('exit'))} "
                     f"{t['r']:+.2f}R ({t.get('reason', '')})")
    L.append("")
    L.append("<i>Paper: simulazione su prezzi reali. Non e' un consiglio finanziario. "
             "Soldi veri: 0.</i>")
    return "\n".join(L)


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
            f"totale {sum(rs):+.2f}R, expectancy {exp:+.2f}R, "
            f"max drawdown {dd:.2f}R, aperte {len(s['open'])}")


def earnings(s=None, risk_eur=100.0):
    """Stima onesta del guadagno. Il registro e' simulato: qui il risultato in R
    (multipli del rischio) e la stessa cifra se ogni operazione avesse rischiato
    `risk_eur`, dichiarata come simulazione. Soldi veri: non ne ha mossi nessuno."""
    s = s or load()
    closed = s["closed"]
    if not closed:
        return ("Guadagno: 0. Nessuna operazione chiusa nel registro paper. "
                "Soldi veri: 0.")
    rs = [t["r"] for t in closed]
    wins = [r for r in rs if r > 0]
    tot = sum(rs)
    sim = tot * risk_eur
    return (
        "<b>Stima del guadagno</b>\n"
        "Soldi veri guadagnati dal bot: <b>0</b> (nessun ordine, nessun conto collegato).\n"
        f"Registro paper: {len(rs)} chiuse, {len(wins)} in utile, hit {len(wins)/len(rs)*100:.0f}%.\n"
        f"Risultato: <b>{tot:+.2f}R</b> (expectancy {tot/len(rs):+.3f}R per operazione).\n"
        f"Se ogni operazione avesse rischiato {risk_eur:.0f}\u20ac: <b>{sim:+.0f}\u20ac</b> "
        "(simulazione, non soldi reali).\n"
        "Aperte ora: " + str(len(s["open"])) + "\n"
        "Verdetto: " + ("positivo, ma piccolo campione" if tot > 0
                        else "negativo. Con questo campione non e' un edge.")
    )


if __name__ == "__main__":
    syms = json.load(open(os.path.join(ROOT, "private_cfg.json"), encoding="utf-8"))["symbols"]
    st, ev = step(syms, dry="--dry" in sys.argv)
    for e in ev:
        print(e)
    print(report(st))
