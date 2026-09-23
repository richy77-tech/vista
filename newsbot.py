#!/usr/bin/env python3
"""Vista Telegram bot: digest di mercato in italiano, solo API gratuite.
Cripto (CoinGecko) + azioni (Yahoo chart) + notizie italiane (RSS).
Numeri e medie, non consigli. Le decisioni e i rischi sono di chi legge.
"""
import html
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

TOKEN = os.environ["TG_TOKEN"]
CHAT = os.environ.get("TG_CHAT", "-1003559029410")
VISTA = "https://richy77-tech.github.io/vista/"

UA = {"User-Agent": "Mozilla/5.0 (vista-newsbot)"}

STOCKS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "SPY"]
CRYPTO_TECH = ["bitcoin", "ethereum"]


def get(url, headers=UA):
    req = urllib.request.Request(url, headers=headers)
    return json.load(urllib.request.urlopen(req, timeout=20))


# ---------- dati ----------

STABLES = {"USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDE"}


def crypto_prices(n=8):
    d = get("https://api.coingecko.com/api/v3/coins/markets"
            "?vs_currency=usd&order=market_cap_desc&per_page=25&page=1&sparkline=false")
    return [c for c in d if c["symbol"].upper() not in STABLES][:n]


def crypto_history(coin_id, days=90):
    d = get(f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
            f"?vs_currency=usd&days={days}&interval=daily")
    return [p[1] for p in d["prices"]]


def stock_history(symbol, rng="6mo"):
    d = get(f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
            f"?range={rng}&interval=1d")
    r = d["chart"]["result"][0]
    closes = [c for c in r["indicators"]["quote"][0]["close"] if c is not None]
    meta = r["meta"]
    return closes, meta.get("regularMarketPrice"), (closes[-2] if len(closes) > 1 else None)


FEEDS = (
    "https://cryptonomist.ch/feed/",
    "https://www.criptovaluta.it/feed",
    "https://it.beincrypto.com/feed/",
)


def news(k=4):
    out = []
    for feed in FEEDS:
        u = "https://api.rss2json.com/v1/api.json?rss_url=" + urllib.parse.quote(feed, safe="")
        try:
            for it in get(u).get("items", [])[:k]:
                out.append((it["title"], it["link"], it.get("pubDate", "")))
        except Exception:
            pass
    out.sort(key=lambda x: x[2], reverse=True)
    return out[:k]


# ---------- tecnica ----------

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
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n


def read(closes):
    """Lettura meccanica: medie + RSI. Nessuna previsione."""
    if not closes:
        return None
    price = closes[-1]
    m20, m50 = ma(closes, 20), ma(closes, 50)
    r = rsi(closes)
    parts = []
    if m20 and m50:
        if price > m20 > m50:
            parts.append("sopra MA20 e MA50")
        elif price < m20 < m50:
            parts.append("sotto MA20 e MA50")
        else:
            parts.append("tra le medie")
    if r is not None:
        if r >= 70:
            parts.append(f"RSI {r:.0f} (ipercomprato)")
        elif r <= 30:
            parts.append(f"RSI {r:.0f} (ipervenduto)")
        else:
            parts.append(f"RSI {r:.0f}")
    return ", ".join(parts) if parts else None


# ---------- composizione ----------

def arrow(p):
    return "🟢" if p >= 0 else "🔴"


def money(x):
    if x is None:
        return "n/d"
    return f"${x:,.2f}" if x >= 1 else f"${x:.4f}"


def compose():
    ts = datetime.now(timezone.utc).strftime("%d/%m %H:%M UTC")
    L = [f"📊 <b>Mercati</b> · {ts}", ""]

    # cripto
    try:
        L.append("<b>🪙 Cripto</b>")
        for c in crypto_prices():
            s = c["symbol"].upper()
            p = c["price_change_percentage_24h"] or 0
            L.append(f"{arrow(p)} <b>{s}</b> {money(c['current_price'])} ({p:+.1f}%)")
    except Exception as e:
        L.append(f"<i>cripto non disponibili ({type(e).__name__})</i>")
    L.append("")

    # azioni
    stock_series = {}
    try:
        L.append("<b>📈 Azioni</b>")
        for s in STOCKS:
            try:
                closes, price, prev = stock_history(s)
                stock_series[s] = closes
                p = (price / prev - 1) * 100 if price and prev else 0
                L.append(f"{arrow(p)} <b>{s}</b> {money(price)} ({p:+.1f}%)")
            except Exception:
                L.append(f"• <b>{s}</b> n/d")
    except Exception:
        pass
    L.append("")

    # lettura tecnica
    tech = []
    try:
        for cid in CRYPTO_TECH:
            try:
                rr = read(crypto_history(cid))
                if rr:
                    tech.append(f"<b>{cid.upper()}</b>: {rr}")
            except Exception:
                pass
    except Exception:
        pass
    for s, closes in stock_series.items():
        rr = read(closes)
        if rr:
            tech.append(f"<b>{s}</b>: {rr}")
    if tech:
        L.append("<b>🧭 Lettura tecnica</b>")
        L += tech
        L.append("<i>Medie e RSI, non consigli. Decisioni e rischi sono tuoi.</i>")
        L.append("")

    # notizie
    try:
        ns = news()
        if ns:
            L.append("<b>📰 Notizie crypto</b>")
            for t, l, _ in ns:
                L.append(f'• <a href="{html.escape(l)}">{html.escape(t)}</a>')
            L.append("")
    except Exception:
        pass

    L.append(f'🔎 Tutto su Vista: <a href="{VISTA}">richy77-tech.github.io/vista</a>')
    return "\n".join(L)


def post(text):
    body = urllib.parse.urlencode({
        "chat_id": CHAT, "text": text,
        "parse_mode": "HTML", "disable_web_page_preview": "true",
    }).encode()
    r = json.load(urllib.request.urlopen(
        urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=body), timeout=20))
    return r["ok"]


if __name__ == "__main__":
    t = compose()
    print(t)
    if "--send" in sys.argv:
        print("\nSENT:", post(t))
