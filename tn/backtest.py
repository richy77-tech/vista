"""Test walk-forward della regola, onesto e fuori campione.

Perche' esiste: le regole dentro paper.py girano avanti, non si giudicano da
sole. Qui la stessa identica regola viene rigiocata su barre reali, e divisa in
due: una parte che "conosco" (in-sample) e una che non ho mai visto
(out-of-sample). Solo il numero fuori campione conta. goldbot insegna: IS PF
4.90, OOS 0.99. Il numero bello non si pubblica.

Non tocca soldi. Non apre ordini. Scrive solo numeri.
"""
import json
import os
import sys

from .paper import ohlc
from . import indicators as ind

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def replay(rows, atr_n=14, stop_atr=1.5, target_atr=3.0, max_bars=5,
           trend_filter=False, min_atr_pct=0.10, split=None,
           spread_bp=0.0, slippage_bp=0.0, commission_bp=0.0):
    """Rigioca la regola su una serie di barre. Ritorna (trades_is, trades_oos).

    I costi si pagano tutti e due i lati: spread a meta' (entrata peggiore di
    mezzo spread), slippage a ogni riempimento, commissione in basis point sul
    valore nozionale. Vengono sottratti all'R, non al prezzo, cosi' il numero
    finale e' confrontabile con quello senza costi.
    """
    trs = []
    i = max(atr_n + 1, 210)
    open_pos = None
    while i < len(rows):
        bar = rows[i]
        if open_pos:
            open_pos["bars"] += 1
            exit_, why = None, None
            if open_pos["side"] == "long":
                if bar["l"] <= open_pos["stop"]:
                    exit_, why = open_pos["stop"], "stop"
                elif bar["h"] >= open_pos["target"]:
                    exit_, why = open_pos["target"], "target"
            else:
                if bar["h"] >= open_pos["stop"]:
                    exit_, why = open_pos["stop"], "stop"
                elif bar["l"] <= open_pos["target"]:
                    exit_, why = open_pos["target"], "target"
            if exit_ is None and open_pos["bars"] >= max_bars:
                exit_, why = bar["c"], "time"
            if exit_ is not None:
                risk = abs(open_pos["entry"] - open_pos["stop"]) or 1e-9
                pnl = (exit_ - open_pos["entry"]) if open_pos["side"] == "long" \
                    else (open_pos["entry"] - exit_)
                # costo in unita' di prezzo, poi in R: spread 1x (entrata+uscita),
                # slippage 2x, commissione sul nozionale a entrata e a uscita.
                px = open_pos["entry"]
                cost_px = px * (spread_bp + 2 * slippage_bp + 2 * commission_bp) / 10000.0
                trs.append({"i": open_pos["i"], "r": pnl / risk - cost_px / risk,
                            "r_gross": pnl / risk, "cost_r": cost_px / risk,
                            "why": why})
                open_pos = None
            i += 1
            continue

        prev = rows[i - 1]
        side = "long" if bar["c"] > prev["h"] else ("short" if bar["c"] < prev["l"] else None)
        if side:
            closes = [r["c"] for r in rows[:i + 1]]
            a = ind.atr(rows[:i + 1], atr_n)
            apct = ind.atr_pct(rows[:i + 1], atr_n)
            reg = ind.regime(closes)
            ok = a and (apct is None or apct >= min_atr_pct)
            if ok and trend_filter:
                ok = reg["state"] == ("su" if side == "long" else "giu")
            if ok:
                entry = bar["c"]
                open_pos = {
                    "i": i, "side": side, "entry": entry, "bars": 0,
                    "stop": entry - stop_atr * a if side == "long" else entry + stop_atr * a,
                    "target": entry + target_atr * a if side == "long" else entry - target_atr * a,
                }
        i += 1
    if split is None:
        return trs, []
    return [t for t in trs if t["i"] < split], [t for t in trs if t["i"] >= split]


def _stats(trs):
    if not trs:
        return {"n": 0, "r": 0.0, "hit": 0.0, "exp": 0.0, "time": 0}
    rs = [t["r"] for t in trs]
    w = [r for r in rs if r > 0]
    return {"n": len(rs), "r": sum(rs), "hit": len(w) / len(rs) * 100,
            "exp": sum(rs) / len(rs), "time": sum(1 for t in trs if t["why"] == "time")}


def run(symbols=None):
    cfg = json.load(open(os.path.join(ROOT, "private_cfg.json"), encoding="utf-8"))
    symbols = symbols or cfg["symbols"]
    print(f"{'symbol':<10} {'bars':>5} | {'base IS':>16} | {'base OOS':>16} | "
          f"{'filt IS':>16} | {'filt OOS':>16}")
    agg = {"b_is": [], "b_oos": [], "f_is": [], "f_oos": []}
    for sym in symbols:
        try:
            rows = ohlc(sym, rng="5y")
        except Exception as e:
            print(f"{sym:<10} fonte giu ({type(e).__name__})")
            continue
        if len(rows) < 300:
            continue
        split = int(len(rows) * 0.7)
        b_is, b_oos = replay(rows, trend_filter=False, split=split)
        f_is, f_oos = replay(rows, trend_filter=True, split=split)
        agg["b_is"] += b_is; agg["b_oos"] += b_oos
        agg["f_is"] += f_is; agg["f_oos"] += f_oos

        def s(x):
            d = _stats(x)
            return f"{d['n']:>3}tr {d['r']:>+6.1f}R"

        print(f"{sym:<10} {len(rows):>5} | {s(b_is):>16} | {s(b_oos):>16} | "
              f"{s(f_is):>16} | {s(f_oos):>16}")
    print()
    for label, key in [("BASE in-sample", "b_is"), ("BASE out-of-sample", "b_oos"),
                       ("FILTRO in-sample", "f_is"), ("FILTRO out-of-sample", "f_oos")]:
        d = _stats(agg[key])
        print(f"{label:<24} {d['n']:>4} op  tot {d['r']:>+7.2f}R  "
              f"exp {d['exp']:>+.3f}R  hit {d['hit']:>4.0f}%  uscite tempo {d['time']}")


if __name__ == "__main__":
    run(sys.argv[1:] or None)
