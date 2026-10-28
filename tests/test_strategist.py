"""Test dello stratega su snap finti, senza rete.

Il punto non e' che il piano sia bello: e' che ogni ramo dica la verita' — se il
settimanale va contro, salta; se il prezzo e' a meta' range, salta; e quando
propone, stop e target stanno dalla parte giusta e il R/R e' almeno 1.5.
"""
from tn import strategist


def _snap(pos_price, hi=120.0, lo=100.0, prev_h=119.0, prev_l=101.0):
    step = (pos_price - lo) / 39.0
    rows = []
    for i in range(40):
        c = lo + i * step
        rows.append({"h": c + 0.4, "l": c - 0.4, "c": c, "v": 1000 + i})
    closes = [r["c"] for r in rows]
    return {"sym": "X", "price": pos_price, "hi20": hi, "lo20": lo,
            "prev_h": prev_h, "prev_l": prev_l, "rows": rows, "closes": closes}


def test_counter_trend_weekly_skips():
    old = strategist._weekly_regime
    strategist._weekly_regime = lambda s: "giu"
    try:
        p = strategist.plan("X", "long", _snap(118.0))
        assert p["ok"] is False and "controcorrente" in p["why"], p
    finally:
        strategist._weekly_regime = old


def test_middle_of_range_skips():
    old = strategist._weekly_regime
    strategist._weekly_regime = lambda s: "su"
    try:
        p = strategist.plan("X", "long", _snap(110.0, hi=120.0, lo=100.0))
        assert p["ok"] is False and "meta' range" in p["why"], p
    finally:
        strategist._weekly_regime = old


def test_breakout_long_plan_is_sane():
    old = strategist._weekly_regime
    strategist._weekly_regime = lambda s: "su"
    try:
        p = strategist.plan("X", "long", _snap(118.5, hi=120.0, lo=100.0, prev_h=119.0))
        assert p["ok"] is True, p
        assert p["kind"] == "breakout", p
        assert p["stop"] < p["entry"] < p["target"], p
        assert p["rr"] >= 1.5, p
    finally:
        strategist._weekly_regime = old


def test_no_data_is_declared():
    p = strategist.plan("X", "long", {"sym": "X", "price": None, "rows": []})
    assert p["ok"] is False and "insufficienti" in p["why"], p

def test_pullback_long_enters_at_mean():
    old = strategist._weekly_regime
    strategist._weekly_regime = lambda s: "su"
    try:
        p = strategist.plan("X", "long", _snap(108.0, hi=120.0, lo=100.0))
        assert p["ok"] is True, p
        assert p["kind"] == "pullback", p
        assert p["entry"] < 108.0, p          # entra piu' in basso, non insegue
        assert p["stop"] < p["entry"] < p["target"], p
        assert p["rr"] >= 1.5, p
    finally:
        strategist._weekly_regime = old
