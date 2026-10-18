"""Test offline (nessuna rete) della mappa settimanale: copertura multi-mercato,
righe costruite solo da dati presenti, e reso bilingue."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tn import weekly as wk  # noqa: E402


def _closes(n=60, base=100.0, step=0.5):
    return [base + i * step for i in range(n)]


def fake_d():
    return {
        "market": {
            "indices": [
                {"label": "S&P 500", "price": 100.0, "closes": _closes()},
                {"label": "NASDAQ", "price": 90.0, "closes": _closes(step=-0.4)},
                {"label": "DAX", "price": 50.0, "closes": _closes(base=40, step=-0.2)},
            ],
            "metals": [{"label": "GOLD", "price": 200.0, "closes": _closes(base=180)}],
            "energy": [],  # fonte assente: il gruppo non deve comparire
            "forex": [{"label": "EUR/USD", "price": 1.1, "closes": _closes(base=1.05)}],
        },
        "series": {
            "AAPL": _closes(), "META": _closes(step=-0.6), "NVDA": _closes(base=90),
            "BITCOIN": _closes(),  # non e' un'azione: va escluso
        },
        "crypto": [
            {"symbol": s, "current_price": 1,
             "price_change_percentage_7d_in_currency": ch}
            for s, ch in [("xmr", 9.1), ("leo", 1.4), ("trx", 0.5), ("usds", 0.0),
                          ("btc", -2.4), ("eth", -3.1), ("sol", -4.0), ("doge", -5.0),
                          ("link", -10.3), ("near", -11.3), ("zec", -11.9), ("ada", -13.1)]
        ] + [{"symbol": "x", "current_price": 1}],  # senza 7d: saltato
    }


def test_market_week_covers_groups_and_skips_empty():
    blocks = wk.market_week(fake_d())
    names = {b["group"] for b in blocks}
    assert "indices" in names and "metals" in names and "forex" in names
    assert "energy" not in names, "un gruppo senza dati non deve comparire"
    labels = [r["label"] for b in blocks if b["group"] == "indices" for r in b["rows"]]
    assert labels == ["S&P 500", "NASDAQ", "DAX"]


def test_market_week_change_is_computed():
    blocks = wk.market_week(fake_d())
    spx = next(r for b in blocks for r in b["rows"] if r["label"] == "S&P 500")
    assert spx["chg"] is not None and spx["chg"] > 0
    nas = next(r for b in blocks for r in b["rows"] if r["label"] == "NASDAQ")
    assert nas["chg"] is not None and nas["chg"] < 0


def test_crypto_week_pairs_and_orders():
    best, worst = wk.crypto_week(fake_d())
    assert best and best[0]["sym"] == "XMR"
    assert worst and worst[0]["sym"] == "ADA"
    # nessuna sovrapposizione tra le due liste
    assert not ({r["sym"] for r in best} & {r["sym"] for r in worst})
    # l'asset senza dato 7d non entra in nessuna delle due liste
    assert all(r["sym"] != "X" for r in best + worst)


def test_stock_week_excludes_crypto():
    rows = wk.stock_week(fake_d())
    syms = [r["sym"] for r in rows]
    assert "BITCOIN" not in syms
    assert syms[-1] == "META"  # il peggiore in coda


def test_tech_str_is_language_aware():
    above = {"trend": "above", "rsi": 55.0}
    below = {"trend": "below", "rsi": 25.0}
    assert "sopra" in wk._tech_str(above, "it")
    assert "above" in wk._tech_str(above, "en")
    assert "ipervenduto" in wk._tech_str(below, "it")
    assert "oversold" in wk._tech_str(below, "en")


def test_compose_bilingual_and_no_forecast_words():
    d = fake_d()
    it = wk.compose_weekly("it", d)
    en = wk.compose_weekly("en", d)
    assert "Dove guardare" in it and "Where to watch" in en
    assert "consulenza finanziaria" in it.lower()
    assert "not financial advice" in en.lower()
    assert it != en
