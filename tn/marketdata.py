"""Market data multi-asset via Yahoo Finance (gratis, senza chiave).
Crypto via CoinGecko. Nessun dato inventato: se una fonte cade, il simbolo
resta assente o marcato stale, non viene riempito a caso.
"""
from .http import get_json

# symbol, label, emoji
GROUPS = {
    "metals": [("GC=F", "GOLD", "🥇"), ("SI=F", "SILVER", "🥈"),
               ("PL=F", "PLATINUM", "⚪"), ("HG=F", "COPPER", "🟠")],
    "energy": [("CL=F", "WTI OIL", "🛢️"), ("BZ=F", "BRENT", "🛢️"),
               ("NG=F", "NAT GAS", "🔥")],
    "forex": [("EURUSD=X", "EUR/USD", "💵"), ("GBPUSD=X", "GBP/USD", "💵"),
              ("JPY=X", "USD/JPY", "💵"), ("AUDUSD=X", "AUD/USD", "💵"),
              ("USDCAD=X", "USD/CAD", "💵"), ("DX-Y.NYB", "DXY", "💵")],
    "indices": [("^GSPC", "S&P 500", "📊"), ("^IXIC", "NASDAQ", "📊"),
                ("^DJI", "DOW", "📊"), ("^RUT", "RUSSELL 2000", "📊"),
                ("^FTSE", "FTSE 100", "📊"), ("^GDAXI", "DAX", "📊"),
                ("^N225", "NIKKEI", "📊"), ("^VIX", "VIX", "📊")],
}


def yahoo(symbol, rng="3mo", interval="1d"):
    d = get_json(f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
                 f"?range={rng}&interval={interval}", tries=3)
    r = d["chart"]["result"][0]
    closes = [c for c in r["indicators"]["quote"][0]["close"] if c is not None]
    meta = r["meta"]
    price = meta.get("regularMarketPrice") or (closes[-1] if closes else None)
    prev = closes[-2] if len(closes) > 1 else None
    return {"symbol": symbol, "price": price, "prev": prev, "closes": closes,
            "currency": meta.get("currency"), "name": meta.get("shortName")}


def market_groups():
    """Tutti i gruppi (metalli, energia, forex, indici). Ogni simbolo e' isolato."""
    out, errors = {}, []
    for g, syms in GROUPS.items():
        out[g] = []
        for sym, label, emo in syms:
            try:
                q = yahoo(sym)
                q.update({"label": label, "emoji": emo})
                out[g].append(q)
            except Exception as e:
                errors.append(f"{sym}:{type(e).__name__}")
    return out, errors


def change_pct(q):
    p, prev = q.get("price"), q.get("prev")
    if not p or not prev:
        return None
    return (p / prev - 1) * 100


def rsi(closes, n=14):
    if len(closes) < n + 1:
        return None
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    ag, al = gains / n, losses / n
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(d, 0.0)) / n
        al = (al * (n - 1) + max(-d, 0.0)) / n
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def ma(closes, n):
    return sum(closes[-n:]) / n if len(closes) >= n else None


def technical(q):
    """Lettura meccanica: medie + RSI. Numeri, mai consigli."""
    closes = q.get("closes") or []
    if not closes:
        return None
    price = closes[-1]
    m20, m50 = ma(closes, 20), ma(closes, 50)
    r = rsi(closes)
    bits = []
    if m20 and m50:
        bits.append("sopra MA20/50" if price > m20 > m50
                    else "sotto MA20/50" if price < m20 < m50 else "tra le medie")
    if r is not None:
        tag = "ipercomprato" if r >= 70 else "ipervenduto" if r <= 30 else ""
        bits.append(f"RSI {r:.0f}" + (f" ({tag})" if tag else ""))
    return ", ".join(bits) or None
