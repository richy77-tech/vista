"""Gate di ingresso: se una regola non ha prova fuori campione, non tocca soldi."""
from tn import gates


def _data(**rules):
    return rules


def test_default_is_paper_never_live():
    ok, why = gates.allow("rottura", "SI=F", live=True)
    assert ok is False and "paper" in why


def test_default_allows_paper():
    ok, why = gates.allow("rottura", "SI=F")
    assert ok is True and "paper" in why


def test_gold_breakout_is_off():
    ok, why = gates.allow("rottura", "GC=F")
    assert ok is False and "off" in why and "0.90" in why


def test_unknown_rule_cannot_go_live():
    ok, why = gates.allow("mai-sentita", "BTC-USD", live=True)
    assert ok is False


def test_live_only_when_declared():
    d = _data(rottura={"BTC-USD": {"status": "live", "why": "test 3 anni"}})
    ok, why = gates.allow("rottura", "BTC-USD", live=True, data=d)
    assert ok is True
    ok2, _ = gates.allow("rottura", "ETH-USD", live=True, data=d)
    assert ok2 is False  # il default resta paper


def test_bad_status_falls_back_to_paper():
    d = _data(x={"GC=F": {"status": "si", "why": "typo"}})
    ok, why = gates.allow("x", "GC=F", live=True, data=d)
    assert ok is False and "paper" in why


def test_off_blocks_even_paper():
    d = _data(x={"A": {"status": "off", "why": "bocciata"}})
    assert gates.allow("x", "A", data=d)[0] is False


def test_missing_file_is_paper():
    g = gates.gate("rottura", "GC=F", data={})
    assert g["status"] == "paper"