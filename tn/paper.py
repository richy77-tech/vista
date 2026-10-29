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
import re
from html import escape
import sys
from datetime import datetime, timezone

from .http import get_json
from . import indicators as ind
from . import marketdata as md
from . import tunables as T
from . import gates

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATE = os.path.join(ROOT, "paper_state.json")
# Secondo registro, per il desk a sole regole (esperimento A/B, vedi rules_desk.py).
STATE_RULES = os.path.join(ROOT, "paper_state_rules.json")

# Nome leggibile di ogni asset: nel bot si legge "ARGENTO", non "SI=F".
LABELS = {sym: lab for g in md.GROUPS.values() for sym, lab, _ in g}
LABELS["BTC-USD"] = "BITCOIN"
LABELS["ETH-USD"] = "ETHEREUM"


def label(sym):
    return LABELS.get(sym, sym)

# Parametri: un posto solo (tn/tunables.py). Moduli leggono da li, non da qui.
ATR_N = T.p("atr_n", 14)
STOP_ATR = T.p("stop_atr", 1.5)
TARGET_ATR = T.p("target_atr", 3.0)
MAX_BARS = T.p("max_bars", 5)


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
        v = (q.get("volume") or [None] * (i + 1))[i]
        rows.append({"o": o, "h": h, "l": l, "c": c, "v": v})
    return rows


def atr(rows, n=ATR_N):
    return ind.atr(rows, n)


def load(path=None):
    try:
        with open(path or STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"open": {}, "closed": []}


def save(s, path=None):
    with open(path or STATE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)


def _r(entry, exit_, stop, side):
    """P&L in R (multipli del rischio iniziale)."""
    risk = abs(entry - stop)
    if risk == 0:
        return 0.0
    pnl = (exit_ - entry) if side == "long" else (entry - exit_)
    return pnl / risk


_TREND_TXT = {"su": "tendenza in salita", "giu": "tendenza in discesa",
              "piatto": "tendenza incerta", "n/d": "tendenza non leggibile"}


_PLAIN = {
    "3 ruoli": "tre conferme insieme: la notizia era forte, il grafico andava "
               "nella stessa parte, e il movimento continuava",
    "news+movimento": "la notizia era forte e il prezzo si stava gia' muovendo "
                      "nella stessa direzione",
}


def pretty_reason(reason):
    """Le voci salvate prima del 21/10 sono in gergo. Qui tornano frasi."""
    if not reason:
        return reason
    for k, v in _PLAIN.items():
        if reason.startswith(k):
            return v
    if " | " not in reason:
        return reason
    out = []
    for part in reason.split(" | "):
        p = part.strip()
        if p.startswith("rottura"):
            v = "rialzo" if p.split(" ieri")[0].endswith("max") else "ribasso"
            what = "il massimo" if v == "rialzo" else "il minimo"
            px = re.findall(r"[\d.,]+", p)
            b = px[0] if px else "?"
            c = px[1] if len(px) > 1 else "?"
            out.append(f"ha superato {what} di ieri ({b}) e ha chiuso a {c}: segnale al {v}")
        elif p.startswith("trend"):
            out.append(_TREND_TXT.get(p.split()[-1], "tendenza incerta"))
        elif p.startswith("RSI"):
            try:
                r = float(re.findall(r"[\d.]+", p)[0])
                lbl = "comprato" if r >= 70 else ("venduto" if r <= 30 else "neutro")
                out.append(f"RSI {r:.0f}, {lbl}")
            except Exception:
                out.append(p)
        elif p.startswith("volatil"):
            try:
                v = float(re.findall(r"[\d.]+", p)[0])
                out.append(f"si muove del {v:.1f}% al giorno")
            except Exception:
                out.append(p)
        else:
            out.append(p)
    return "; ".join(out)


def describe(side, prev, last, reg, r_now, apct):
    """Perche' e' entrata, in parole semplici. Scritta all'apertura, non dopo."""
    brk = prev["h"] if side == "long" else prev["l"]
    move = "rialzo" if side == "long" else "ribasso"
    what = "il massimo" if side == "long" else "il minimo"
    bits = [f"ha superato {what} di ieri ({_fmt(brk)}) e ha chiuso a {_fmt(last['c'])}: segnale al {move}"]
    trend = {"su": "tendenza in salita", "giu": "tendenza in discesa",
             "piatto": "tendenza incerta", "n/d": "tendenza non leggibile"}.get(
                 reg.get("state"), "tendenza incerta")
    bits.append(trend)
    if r_now is not None:
        if r_now >= 70:
            bits.append(f"RSI {r_now:.0f}, comprato")
        elif r_now <= 30:
            bits.append(f"RSI {r_now:.0f}, venduto")
        else:
            bits.append(f"RSI {r_now:.0f}, neutro")
    if apct is not None:
        bits.append(f"si muove del {apct:.1f}% al giorno")
    return "; ".join(bits)


def step(symbols, s=None, dry=False, path=None, open_new=True):
    """Un giro: prima chiude quello che va chiuso, poi apre le nuove rotture."""
    s = s or load(path)
    now = datetime.now(timezone.utc).isoformat(timespec="minutes")
    events = []

    for sym in symbols:
        try:
            rows = ohlc(sym, rng="2y")  # 2y: serve per EMA200 vera, non finta
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
            exit_, why = None, None
            if pos["side"] == "long":
                if last["l"] <= pos["stop"]:
                    exit_, why = pos["stop"], "stop"
                elif last["h"] >= pos["target"]:
                    exit_, why = pos["target"], "target"
            else:
                if last["h"] >= pos["stop"]:
                    exit_, why = pos["stop"], "stop"
                elif last["l"] <= pos["target"]:
                    exit_, why = pos["target"], "target"
            if exit_ is None and pos["bars"] >= MAX_BARS:
                exit_, why = last["c"], "time"
            if exit_ is not None:
                pos.update({"exit": exit_, "exit_ts": now, "exit_reason": why,
                            "r": round(_r(pos["entry"], exit_, pos["stop"], pos["side"]), 3)})
                s["closed"].append(pos)
                del s["open"][sym]
                why_txt = {"stop": "stop scattato", "target": "obiettivo raggiunto",
                           "time": "tempo scaduto"}.get(why, why)
                verso = "rialzo" if pos["side"] == "long" else "ribasso"
                events.append(f"{label(sym)}: chiusa al {verso} a {_fmt(exit_)} "
                              f"\u2192 {pos['r']:+.2f}R ({why_txt})")
            continue

        if not open_new:
            continue
        # nessuna posizione: cerco una rottura della barra precedente,
        # ma solo se il contesto non la contraddice (filtri in tunables.py)
        closes = [r["c"] for r in rows]
        reg = ind.regime(closes, T.p("ema_fast", 50), T.p("ema_slow", 200), T.p("slope_n", 10))
        r_now = ind.rsi(closes, 14)
        apct = ind.atr_pct(rows, ATR_N)

        if last["c"] > prev["h"]:
            side = "long"
        elif last["c"] < prev["l"]:
            side = "short"
        else:
            continue
        if apct is not None and apct < T.p("min_atr_pct", 0.10):
            events.append(f"{label(sym)}: segnale al {('rialzo' if side == 'long' else 'ribasso')} "
                          f"scartato (prezzo troppo fermo, {apct:.2f}%)")
            continue
        if T.p("trend_filter", True) and reg["state"] != ("su" if side == "long" else "giu"):
            events.append(f"{label(sym)}: segnale al {('rialzo' if side == 'long' else 'ribasso')} "
                          f"scartato (tendenza {reg['state']})")
            continue

        ok, why_gate = gates.allow("rottura", sym)
        if not ok:
            events.append(f"{label(sym)}: segnale al {('rialzo' if side == 'long' else 'ribasso')} "
                          f"non operato ({why_gate})")
            continue

        entry = last["c"]
        stop = entry - STOP_ATR * a if side == "long" else entry + STOP_ATR * a
        tgt = entry + TARGET_ATR * a if side == "long" else entry - TARGET_ATR * a
        s["open"][sym] = {
            "symbol": sym, "side": side, "entry": entry,
            "stop": stop, "target": tgt, "atr": a, "bars": 0,
            "entry_ts": now,
            "reason": describe(side, prev, last, reg, r_now, apct),
            "context": {"trend": reg["state"], "ema_fast": reg["ema_fast"],
                        "ema_slow": reg["ema_slow"], "rsi": r_now, "atr_pct": apct},
        }
        events.append(f"{label(sym)}: aperta al {('rialzo' if side == 'long' else 'ribasso')} "
                      f"a {_fmt(entry)}; perdita massima {_fmt(stop)}, obiettivo {_fmt(tgt)}. "
                      f"{s['open'][sym]['reason']}")

    if not dry:
        save(s, path)
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


def _money(capital=None, risk_pct=None):
    """Capitale, % a rischio (col tetto) e euro a rischio per operazione.
    Tre numeri distinti: confonderli e' l'errore che fa credere di aver perso
    il capitale quando si e' solo letto il rischio per operazione."""
    capital = T.p("capital_eur", 100.0) if capital is None else capital
    risk_pct = T.p("risk_pct", 1.0) if risk_pct is None else risk_pct
    risk_pct = min(risk_pct, T.p("max_risk_pct", 5.0))
    return capital, risk_pct, capital * risk_pct / 100.0


def screen(s=None, symbols=None, capital=None, risk_pct=None):
    """Schermata operazioni in parole semplici: cosa ho preso, cosa aspetto,
    com'e' andata. Zero gergo."""
    s = s or load(path)
    open_ = s.get("open") or {}
    closed = s.get("closed") or []
    cap, rpct, eur = _money(capital, risk_pct)
    L = ["<b>\U0001f4cb OPERAZIONI</b> \u00b7 simulazione su prezzi veri "
         "(nessun ordine vero, soldi veri: 0)", ""]
    L.append("<b>Come decido</b>: compro quando il prezzo supera il massimo di ieri, "
             "vendo allo scoperto quando scende sotto il minimo di ieri. Metto uno "
             "stop a 1,5 volte il movimento medio, un obiettivo a 3 volte, e chiudo "
             "da solo se in 5 giorni non succede niente. Una sola operazione per asset.")
    L.append(f"<b>Quanto rischio</b>: su un capitale finto di {cap:.0f}\u20ac rischio "
             f"{rpct:.1f}% a operazione, cioe' {eur:.2f}\u20ac. Numeri di prova, non un conto vero.")
    L.append("")

    L.append(f"<b>\U0001f7e2 OPERAZIONI APERTE ORA: {len(open_)}</b>")
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
            verso = "al RIALZO" if p["side"] == "long" else "al RIBASSO"
            L.append(f"{emo} <b>{label(sym)}</b> \u00b7 {verso}")
            L.append(f"   sono entrato a {_fmt(p['entry'])}, ora vale {_fmt(cur)}")
            L.append(f"   perdita massima (stop) {_fmt(p['stop'])} \u00b7 obiettivo {_fmt(p['target'])}")
            bars = p.get("bars", 0)
            L.append(f"   giorni in corso: {bars} di 5 (chiudo da solo al quinto)")
            if r_now is not None:
                stato = "sta guadagnando" if r_now > 0 else ("sta perdendo" if r_now < 0 else "in pari")
                L.append(f"   {stato}: {r_now * eur:+.2f}\u20ac (su {cap:.0f}\u20ac provati) \u00b7 {pc:+.2f}%")
            if p.get("reason"):
                L.append(f"   perche' sono entrato: {pretty_reason(p['reason'])}")
            if p.get("headline"):
                L.append(f"   la notizia: {escape(str(p['headline'])[:110])}")
            L.append(f"   aperta il {p.get('entry_ts', '')[:16].replace('T', ' ')}")
    L.append("")

    watch = [x for x in (symbols or []) if x not in open_]
    L.append(f"<b>\U0001f7e1 SEGUO, NON HO ANCORA COMPRATO: {len(watch)}</b>")
    L.append("\u2022 " + (", ".join(label(x) for x in watch) if watch else "nessuno"))
    L.append("")

    L.append(f"<b>CHIUSE: {len(closed)}</b>")
    if not closed:
        L.append("\u2022 nessuna")
    else:
        rs = [t["r"] for t in closed]
        wins = [r for r in rs if r > 0]
        tot = sum(rs)
        sim = tot * eur
        L.append(f"\u2022 {len(rs)} in tutto: {len(wins)} in utile, "
                 f"{len(rs) - len(wins)} in perdita ({len(wins) / len(rs) * 100:.0f}% indovinate)")
        L.append(f"\u2022 risultato {sim:+.2f}\u20ac su {cap:.0f}\u20ac provati "
                 f"({sim / cap * 100:+.2f}%), cioe' {tot:+.2f} volte il rischio di una singola operazione")
        for t in closed[-8:]:
            emo = _pl_emoji(t["r"])
            verso = "rialzo" if t["side"] == "long" else "ribasso"
            why = {"stop": "stop", "target": "obiettivo", "time": "tempo scaduto"}.get(
                t.get("exit_reason"), t.get("exit_reason") or "")
            L.append(f"{emo} {label(t['symbol'])} al {verso}: {_fmt(t['entry'])}\u2192{_fmt(t.get('exit'))} "
                     f"\u00b7 {t['r'] * eur:+.2f}\u20ac ({why})")
    L.append("")
    L.append("<i>Simulazione su prezzi veri, non e' un consiglio e non ho mosso soldi. "
             "Serve a misurare se la regola funziona, prima di rischiare davvero.</i>")
    return "\n".join(L)


def report(s=None):
    s = s or load(path)
    closed = s["closed"]
    if not closed:
        return "Simulazione: 0 operazioni chiuse."
    rs = [t["r"] for t in closed]
    wins = [r for r in rs if r > 0]
    exp = sum(rs) / len(rs)
    peak = dd = 0.0
    eq = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    why = [t.get("exit_reason") or t.get("reason", "") for t in closed]
    time_ex = sum(1 for x in why if x == "time")
    return (f"Simulazione: {len(rs)} chiuse, {len(wins) / len(rs) * 100:.0f}% in utile, "
            f"totale {sum(rs):+.2f} volte il rischio, attesa {exp:+.2f} per operazione, "
            f"perdita massima dal picco {dd:.2f}, chiuse per tempo {time_ex}/{len(rs)}, "
            f"aperte {len(s['open'])}")


def earnings(s=None, capital=None, risk_pct=None):
    """Stima onesta del guadagno. Il registro e' simulato: qui il risultato in R
    (multipli del rischio) e la stessa cifra su `capital`, dichiarata come
    simulazione. Soldi veri: non ne ha mossi nessuno."""
    s = s or load(path)
    cap, rpct, eur = _money(capital, risk_pct)
    closed = s["closed"]
    if not closed:
        return ("Guadagno: 0. Nessuna operazione chiusa nella simulazione. "
                "Soldi veri: 0.")
    rs = [t["r"] for t in closed]
    wins = [r for r in rs if r > 0]
    tot = sum(rs)
    sim = tot * eur
    return (
        "<b>Stima del guadagno</b>\n"
        "Soldi veri guadagnati dal bot: <b>0</b> (nessun ordine, nessun conto collegato).\n"
        f"Nella simulazione: {len(rs)} operazioni chiuse, {len(wins)} in utile "
        f"({len(wins)/len(rs)*100:.0f}%).\n"
        f"Risultato: <b>{tot:+.2f} volte il rischio di una singola operazione</b> "
        f"({tot/len(rs):+.3f} per operazione).\n"
        f"Su un capitale finto di {cap:.0f}\u20ac, rischiando {rpct:.1f}% "
        f"({eur:.2f}\u20ac) a operazione: <b>{sim:+.2f}\u20ac</b> ({sim/cap*100:+.2f}% del capitale). "
        "Simulazione, non soldi reali.\n"
        "Aperte ora: " + str(len(s["open"])) + "\n"
        "Verdetto: " + ("positivo, ma piccolo campione" if tot > 0
                        else "negativo. Con questo campione non e' un vantaggio reale.")
    )


if __name__ == "__main__":
    syms = json.load(open(os.path.join(ROOT, "private_cfg.json"), encoding="utf-8"))["symbols"]
    st, ev = step(syms, dry="--dry" in sys.argv)
    for e in ev:
        print(e)
    print(report(st))
