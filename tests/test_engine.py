"""Test offline (nessuna rete): classificazione, impatto, dedup, sentiment."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tn import ai, calendar as cal  # noqa: E402


def mk(title, summary="", tier=2):
    return {"title": title, "summary": summary, "tier": tier, "source": "test",
            "url": "http://x/" + title[:20], "lang": "en"}


def test_impact_routine_is_low():
    it = ai.enrich(mk("Federal Reserve Board announces approval of application by BancFirst"))
    assert it["impact"] == "LOW", it["impact"]


def test_impact_shock_is_critical():
    it = ai.enrich(mk("Exchange halts trading after flash crash in bitcoin"))
    assert it["impact"] == "CRITICAL", it["impact"]


def test_rate_decision_high():
    it = ai.enrich(mk("Fed signals rate hike as inflation surprises"))
    assert it["impact"] in ("HIGH", "CRITICAL"), it["impact"]


def test_categories_and_assets():
    it = ai.enrich(mk("Gold jumps as dollar weakens", "gold and silver rally"))
    assert "GOLD" in it["categories"], it["categories"]
    assert "GOLD" in it["assets"], it["assets"]


def test_dedup_groups_sources():
    a = ai.enrich(mk("Bitcoin ETF sees record inflows this week"))
    b = ai.enrich(mk("Bitcoin ETF sees record inflows this week"))
    b["source"] = "other"
    out = ai.dedup([a, b])
    assert len(out) == 1, len(out)
    assert "other" in out[0]["sources"], out[0]["sources"]


def test_sentiment_direction():
    assert ai.rule_sentiment(mk("Stocks soar to record high on strong earnings"))["score"] > 50
    assert ai.rule_sentiment(mk("Markets plunge as recession fears grow"))["score"] < 50


def test_calendar_normalize():
    ev, err = cal.fetch_week()
    if err:
        return  # rete assente in test offline: salta
    assert all({"id", "ts", "country", "title", "impact"} <= set(e) for e in ev)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    ok = 0
    for f in fns:
        try:
            f()
            print("PASS", f.__name__)
            ok += 1
        except AssertionError as e:
            print("FAIL", f.__name__, e)
        except Exception as e:
            print("ERR ", f.__name__, type(e).__name__, e)
    print(f"\n{ok}/{len(fns)} test passati")
    sys.exit(0 if ok == len(fns) else 1)
