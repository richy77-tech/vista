"""Spread tra due mercati: quanto e' largo, e quanto costa attraversarlo.

L'idea di Richy del 29/10: guadagnare sullo scarto di prezzo dello stesso
strumento su due posti diversi. Quindi il modulo non racconta la teoria: misura
lo scarto eseguibile (vendo al bid di A, compro all'ask di B), lo confronta con
il pedaggio (commissioni taker dei due lati) e dice il netto in punti base.

Nessuna chiave, nessun ordine: solo i book pubblici. Se il netto e' negativo,
il numero lo dice e la faccenda si chiude.
"""
import time

from . import http

# taker spot, listino pubblico standard, in punti base (1 bp = 0.01%)
FEES = {"coinbase": 60, "kraken": 26, "okx": 10, "raydium": 25, "orca": 30}

CEX = {
    "coinbase": ("https://api.exchange.coinbase.com/products/BTC-USD/ticker",
                 lambda d: (float(d["bid"]), float(d["ask"]))),
    "kraken": ("https://api.kraken.com/0/public/Ticker?pair=XBTUSD",
               lambda d: (float(d["result"]["XXBTZUSD"]["b"][0]),
                          float(d["result"]["XXBTZUSD"]["a"][0]))),
    "okx": ("https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT",
            lambda d: (float(d["data"][0]["bidPx"]), float(d["data"][0]["askPx"]))),
}


def books():
    out = {}
    for name, (url, pick) in CEX.items():
        try:
            out[name] = pick(http.get_json(url, tries=2, timeout=12))
        except Exception as e:
            print("spread", name, "ko", type(e).__name__, flush=True)
    return out


def dex_book():
    """WIF su raydium vs orca: due pool, stesso token, prezzo in USD."""
    try:
        d = http.get_json("https://api.dexscreener.com/token-pairs/v1/solana/"
                          "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
                          tries=2, timeout=15)
    except Exception:
        return {}
    out = {}
    for p in d:
        dex = p.get("dexId")
        liq = float(p.get("liquidity", {}).get("usd") or 0)
        if dex in FEES and liq > 50000 and dex not in out:
            out[dex] = float(p["priceUsd"])
    return out


def measure(samples=3, pause=5):
    """Scarto mid in bp tra coppie di venue, mediano su piu' letture."""
    gaps = {}
    for i in range(samples):
        b = books()
        for a, x in b.items():
            for c, y in b.items():
                if a >= c:
                    continue
                mid_a, mid_c = sum(x) / 2, sum(y) / 2
                gaps.setdefault((a, c), []).append((mid_a - mid_c) / mid_c * 1e4)
        if i < samples - 1:
            time.sleep(pause)
    med = {k: sorted(v)[len(v) // 2] for k, v in gaps.items() if v}
    return med


def best(med):
    """(coppia, scarto assoluto bp, pedaggio bp, netto bp)."""
    if not med:
        return None
    pair = max(med, key=lambda k: abs(med[k]))
    toll = FEES[pair[0]] + FEES[pair[1]]
    return pair, med[pair], toll, abs(med[pair]) - toll


def report():
    med = measure()
    dex = dex_book()
    L = ["<b>SCARTI, misurati adesso</b>"]
    if med:
        for (a, c), g in sorted(med.items(), key=lambda kv: -abs(kv[1])):
            toll = FEES[a] + FEES[c]
            net = abs(g) - toll
            segno = "netto +%.1f" % net if net > 0 else "netto %.1f" % net
            L.append("%s vs %s: scarto %.1f bp, pedaggio %.0f bp, <b>%s bp</b>"
                     % (a, c, g, toll, segno))
    else:
        L.append("book non leggibili adesso")
    if len(dex) >= 2:
        a, c = list(dex)[:2]
        g = (dex[a] - dex[c]) / dex[c] * 1e4
        toll = FEES[a] + FEES[c]
        L.append("WIF %s vs %s: scarto %.1f bp, pedaggio %.0f bp, netto %.1f"
                 % (a, c, g, toll, abs(g) - toll))
    b = best(med)
    if b:
        pair, g, toll, net = b
        if net > 0:
            L.append("Il piu' largo e' %s/%s: %+.1f bp netti. Serve inventario su "
                     "entrambi i lati e esecuzione istantanea." % (pair[0], pair[1], net))
        else:
            L.append("Il piu' largo e' %s/%s: scarto %.1f bp contro %.0f di "
                     "pedaggio. Attraversarlo costa %.1f bp: il guadagno non c'e'."
                     % (pair[0], pair[1], abs(g), toll, -net))
    L.append("Commissioni: listino taker pubblico. Numeri veri, nessun ordine.")
    return "\n".join(L)