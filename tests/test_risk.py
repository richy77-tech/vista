"""Test del risk manager: ogni limite deve bloccare da solo, e dirlo."""
from tn import risk


def _cand(sym="GC=F", side="long", entry=100.0, stop=90.0, target=120.0):
    return {"sym": sym, "side": side, "entry": entry, "stop": stop, "target": target}


def _st(open_syms=(), closed_rs=()):
    return {"open": {s: {"side": "long", "entry": 1, "stop": 0, "target": 2} for s in open_syms},
            "closed": [{"r": r} for r in closed_rs]}


def test_allow_clean():
    v = risk.vet(_st(), _cand())
    assert v["action"] == "allow", v
    assert all(c["ok"] for c in v["checks"])


def test_block_bad_rr():
    v = risk.vet(_st(), _cand(stop=98.0, target=101.0))  # 1:0.5
    assert v["action"] == "block" and v["why"].startswith("rr:"), v


def test_block_max_open():
    v = risk.vet(_st(["SI=F", "CL=F", "NG=F"]), _cand())
    assert v["action"] == "block" and v["why"].startswith("posizioni:"), v


def test_block_drawdown():
    v = risk.vet(_st(closed_rs=[-1.0] * 11), _cand())
    assert v["action"] == "block" and v["why"].startswith("drawdown:"), v


def test_block_duplicate():
    v = risk.vet(_st(["GC=F"]), _cand())
    assert v["action"] == "block" and v["why"].startswith("doppione:"), v


def test_block_correlation_same_side():
    up = [float(i) for i in range(80)]
    closes = {"GC=F": up, "SI=F": [x * 2 for x in up]}
    v = risk.vet(_st(["SI=F"]), _cand(), closes=closes)
    assert v["action"] == "block" and v["why"].startswith("correlazione:"), v


def test_correlation_declared_missing():
    v = risk.vet(_st(["SI=F"]), _cand(), closes=None)
    corr = [c for c in v["checks"] if c["check"] == "correlazione"][0]
    assert corr["ok"] is True and "non verificabile" in corr["detail"], corr


def test_block_missing_numbers():
    v = risk.vet(_st(), {"sym": "GC=F", "side": "long", "entry": None, "stop": None})
    assert v["action"] == "block" and v["why"].startswith("numeri:"), v


def test_block_cooldown_after_exit():
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="minutes")
    st = {"open": {}, "closed": [{"symbol": "GC=F", "exit_ts": now, "r": 0.0}]}
    v = risk.vet(st, _cand())
    assert v["action"] == "block" and v["why"].startswith("cooldown:"), v


def test_cooldown_expired_allows():
    st = {"open": {}, "closed": [{"symbol": "GC=F", "exit_ts": "2020-01-01T00:00+00:00", "r": 0.0}]}
    v = risk.vet(st, _cand())
    assert v["action"] == "allow", v
