#!/usr/bin/env python3
"""Vista Telegram bot v4: digest di mercato bilingue (IT + EN), solo API gratuite.
Cripto (CoinGecko) + sentiment community (Fear & Greed) + azioni (Yahoo chart)
+ notizie (RSS IT/EN) + regole di rischio.
Numeri, medie e regole di rischio. Nessun consiglio compra/vendi.
Le decisioni e i rischi sono di chi legge.

v4: i dati si scaricano UNA volta sola e si rendono in due lingue.
    Prima IT ed EN scaricavano tutto due volte e beccavano il rate-limit (HTTPError).
    Ora c'e' anche retry con backoff sui 429.
"""
import html
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

TOKEN = os.environ["TG_TOKEN"]
CHAT = os.environ.get("TG_CHAT", "-1003559029410")
VISTA = "https://richy77-tech.github.io/vista/"
CHANNEL = "https://t.me/tradingnewsbot_richy"

UA = {"User-Agent": "Mozilla/5.0 (vista-newsbot)"}

STOCKS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "SPY"]
CRYPTO_TECH = ["bitcoin", "ethereum"]

FEEDS = {
    "it": ("https://cryptonomist.ch/feed/",
           "https://www.criptovaluta.it/feed",
           "https://it.beincrypto.com/feed/"),
    "en": ("https://cointelegraph.com/rss",
           "https://www.coindesk.com/arc/outboundfeeds/rss/",
           "https://decrypt.co/feed"),
}

T = {
    "it": {
        "title": "📊 <b>Mercati</b>",
        "mood": "🌡️ <b>Sentiment community</b>",
        "crypto": "🪙 <b>Cripto</b>",
        "stocks": "📈 <b>Azioni</b>",
        "tech": "🧭 <b>Lettura tecnica</b>",
        "tech_note": "<i>Medie e RSI: numeri, non consigli.</i>",
        "safe": "🧯 <b>Operare in sicurezza</b>",
        "safe_rules": ("• Rischia max 1-2% del capitale per operazione\n"
                       "• Stop loss deciso prima di entrare, mai dopo\n"
                       "• Mai mediare in perdita\n"
                       "• Se il sentiment è <i>Extreme Greed</i>, il rischio di comprare tardi sale\n"
                       "<i>Regole di gestione del rischio, non previsioni. I rischi restano tuoi.</i>"),
        "news": "📰 <b>Notizie</b>",
        "fng": {"Extreme Fear": "Paura estrema", "Fear": "Paura",
                "Neutral": "Neutrale", "Greed": "Ingordigia",
                "Extreme Greed": "Ingordigia estrema"},
        "dom": "Dominanza BTC",
        "mcap": "Mercato crypto 24h",
        "above": "sopra MA20 e MA50", "below": "sotto MA20 e MA50",
        "between": "tra le medie", "ob": "ipercomprato", "os": "ipervenduto",
        "banner": "📈 Segnali e news ogni giorno: {ch} · {link}",
    },
    "en": {
        "title": "📊 <b>Markets</b>",
        "mood": "🌡️ <b>Community sentiment</b>",
        "crypto": "🪙 <b>Crypto</b>",
        "stocks": "📈 <b>Stocks</b>",
        "tech": "🧭 <b>Technical read</b>",
        "tech_note": "<i>Moving averages and RSI: numbers, not advice.</i>",
        "safe": "🧯 <b>Trading safely</b>",
        "safe_rules": ("• Risk max 1-2% of capital per trade\n"
                       "• Stop loss set before entry, never after\n"
                       "• Never average down into a loss\n"
                       "• When sentiment is <i>Extreme Greed</i>, the risk of buying late is higher\n"
                       "<i>Risk-management rules, not predictions. The risk is yours.</i>"),
        "news": "📰 <b>News</b>",
        "fng": {"Extreme Fear": "Extreme Fear", "Fear": "Fear",
                "Neutral": "Neutral", "Greed": "Greed",
                "Extreme Greed": "Extreme Greed"},
        "dom": "BTC dominance",
        "mcap": "Crypto market 24h",
        "above": "above MA20 and MA50", "below": "below MA20 and MA50",
        "between": "between the averages", "ob": "overbought", "os": "oversold",
        "banner": "📈 Daily signals and news: {ch} · {link}",
    },
}


def get(url, headers=UA, tries=4):
    """GET JSON con retry e backoff. Ritenta su qualsiasi errore di rete/HTTP:
    le API gratuite (alternative.me, CoinGecko) ogni tanto rispondono 429 o 5xx."""
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers)
            return json.load(urllib.request.urlopen(req, timeout=25))
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


# ---------- dati (una volta sola) ----------

STABLES = {"USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDE"}


def crypto_prices(n=8):
    d = get("https://api.coingecko.com/api/v3/coins/markets"
            "?vs_currency=usd&order=market_cap_desc&per_page=25&page=1&sparkline=false")
    return [c for c in d if c["symbol"].upper() not in STABLES
            and "_" not in c["symbol"] and len(c["symbol"]) <= 5][:n]


def crypto_history(coin_id, days=90):
    d = get(f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
            f"?vs_currency=usd&days={days}&interval=daily")
    return [p[1] for p in d["prices"]]


def sentiment():
    """Fear & Greed (community) + dominanza BTC + variazione mkt 24h.
    Le due fonti sono indipendenti: se una cade, l'altra resta."""
    v = cls = btcdom = mcap = None
    try:
        fng = get("https://api.alternative.me/fng/?limit=1", tries=5)["data"][0]
        v, cls = int(fng["value"]), fng["value_classification"]
    except Exception:
        pass
    try:
        g = get("https://api.coingecko.com/api/v3/global")["data"]
        btcdom = g["market_cap_percentage"].get("btc")
        mcap = g.get("market_cap_change_percentage_24h_usd")
    except Exception:
        pass
    if v is None and btcdom is None:
        raise RuntimeError("sentiment sources down")
    return v, cls, btcdom, mcap


def stock_history(symbol, rng="6mo"):
    d = get(f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
            f"?range={rng}&interval=1d")
    r = d["chart"]["result"][0]
    closes = [c for c in r["indicators"]["quote"][0]["close"] if c is not None]
    meta = r["meta"]
    return closes, meta.get("regularMarketPrice"), (closes[-2] if len(closes) > 1 else None)


def news(lang, k=4):
    out = []
    for feed in FEEDS[lang]:
        u = "https://api.rss2json.com/v1/api.json?rss_url=" + urllib.parse.quote(feed, safe="")
        try:
            for it in get(u, tries=2).get("items", [])[:k]:
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


def read(closes, t):
    """Lettura meccanica: medie + RSI. Nessuna previsione."""
    if not closes:
        return None
    price = closes[-1]
    m20, m50 = ma(closes, 20), ma(closes, 50)
    r = rsi(closes)
    parts = []
    if m20 and m50:
        if price > m20 > m50:
            parts.append(t["above"])
        elif price < m20 < m50:
            parts.append(t["below"])
        else:
            parts.append(t["between"])
    if r is not None:
        tag = t["ob"] if r >= 70 else t["os"] if r <= 30 else ""
        parts.append(f"RSI {r:.0f}" + (f" ({tag})" if tag else ""))
    return ", ".join(parts) if parts else None


# ---------- raccolta dati (una volta) ----------

def gather():
    d = {"crypto": None, "sentiment": None, "stocks": {}, "series": {},
         "news": {}, "errors": []}
    try:
        d["crypto"] = crypto_prices()
    except Exception as e:
        d["errors"].append(f"crypto:{type(e).__name__}")
    try:
        d["sentiment"] = sentiment()
    except Exception as e:
        d["errors"].append(f"sentiment:{type(e).__name__}")
    for s in STOCKS:
        try:
            closes, price, prev = stock_history(s)
            d["series"][s] = closes
            d["stocks"][s] = (price, prev)
        except Exception:
            d["stocks"][s] = None
    for cid in CRYPTO_TECH:
        try:
            d["series"][cid.upper()] = crypto_history(cid)
        except Exception:
            pass
    for lg in ("it", "en"):
        try:
            d["news"][lg] = news(lg)
        except Exception:
            d["news"][lg] = []
    return d


# ---------- composizione ----------

def arrow(p):
    return "🟢" if p >= 0 else "🔴"


def money(x):
    if x is None:
        return "n/d"
    return f"${x:,.2f}" if x >= 1 else f"${x:.4f}"


def compose(lang, d):
    t = T[lang]
    ts = datetime.now(timezone.utc).strftime("%d/%m %H:%M UTC")
    L = [f"{t['title']} · {ts}", ""]

    # sentiment community
    if d["sentiment"]:
        v, cls, btcdom, mcap = d["sentiment"]
        L.append(t["mood"])
        if v is not None:
            label = t["fng"].get(cls, cls)
            emo = "😱" if v <= 25 else "😐" if v < 55 else "🤑"
            L.append(f"{emo} Fear &amp; Greed <b>{v}</b> · {label}")
        if btcdom:
            L.append(f"₿ {t['dom']}: {btcdom:.1f}%")
        if mcap is not None:
            L.append(f"{arrow(mcap)} {t['mcap']}: {mcap:+.1f}%")
        L.append("")
    else:
        L.append(f"<i>sentiment n/d</i>\n")

    # cripto
    if d["crypto"]:
        L.append(t["crypto"])
        for c in d["crypto"]:
            s = c["symbol"].upper()
            p = c["price_change_percentage_24h"] or 0
            L.append(f"{arrow(p)} <b>{s}</b> {money(c['current_price'])} ({p:+.1f}%)")
    else:
        L.append(f"<i>crypto n/d</i>")
    L.append("")

    # azioni
    L.append(t["stocks"])
    for s, val in d["stocks"].items():
        if val:
            price, prev = val
            p = (price / prev - 1) * 100 if price and prev else 0
            L.append(f"{arrow(p)} <b>{s}</b> {money(price)} ({p:+.1f}%)")
        else:
            L.append(f"• <b>{s}</b> n/d")
    L.append("")

    # lettura tecnica
    tech = []
    for name, closes in d["series"].items():
        rr = read(closes, t)
        if rr:
            tech.append(f"<b>{name}</b>: {rr}")
    if tech:
        L.append(t["tech"])
        L += tech
        L.append(t["tech_note"])
        L.append("")

    # operare in sicurezza
    L.append(t["safe"])
    L.append(t["safe_rules"])
    L.append("")

    # notizie
    ns = d["news"].get(lang) or []
    if ns:
        L.append(t["news"])
        for title, link, _ in ns:
            L.append(f'• <a href="{html.escape(link)}">{html.escape(title)}</a>')
        L.append("")

    L.append(t["banner"].format(
        ch=f'<a href="{CHANNEL}">@tradingnewsbot_richy</a>',
        link=f'<a href="{VISTA}">Vista</a>'))
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
    d = gather()
    if d["errors"]:
        print("ERRORS:", d["errors"], file=sys.stderr)
    langs = ["it", "en"] if "--send" in sys.argv else [sys.argv[1] if len(sys.argv) > 1 else "it"]
    for lg in langs:
        txt = compose(lg, d)
        print("=" * 20, lg.upper(), "=" * 20)
        print(txt)
        if "--send" in sys.argv:
            print("\nSENT:", post(txt))
