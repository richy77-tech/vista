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
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# .env locale (facoltativo): tiene i secret fuori dal codice.
def _load_env():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(p):
        return
    for line in open(p):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _env_or(*names, default=""):
    for name in names:
        value = os.environ.get(name)
        if value not in (None, ""):
            return value
    return default


_load_env()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tn import calendar as tn_cal          # noqa: E402
from tn import commands as tn_cmd          # noqa: E402
from tn import marketdata as tn_md         # noqa: E402
from tn import newsengine as tn_news       # noqa: E402
from tn import store as tn_store           # noqa: E402

BRAND = "⚡ <b>TRADING NEWS AI</b>\n<i>REAL-TIME MARKET INTELLIGENCE</i>"

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # Pillow assente: le card degradano alla sola foto
    Image = None

TOKEN = _env_or("TG_TOKEN", "TELEGRAM_BOT_TOKEN")
CHAT = _env_or("TG_CHAT", "TELEGRAM_CHAT_ID", default="-1003559029410")
if not TOKEN:
    raise RuntimeError("Missing Telegram token. Set TG_TOKEN or TELEGRAM_BOT_TOKEN in .env")
VISTA = "https://richy77-tech.github.io/vista/"
CHANNEL = "https://t.me/tradingnewsbot_richy"
# Link referral (facoltativo): se impostato, compare nel footer dichiarato come referral.
AFFILIATE = os.environ.get("VISTA_AFFILIATE", "")
# Soglia alert prezzo (variazione % 24h). Default 5%.
ALERT_PCT = float(os.environ.get("VISTA_ALERT_PCT", "5"))

UA = {"User-Agent": "Mozilla/5.0 (vista-newsbot)"}

STOCKS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "SPY",
          "AMD", "NFLX", "JPM", "V", "WMT", "DIS", "COIN", "MSTR"]
STOCK_NAMES = {"AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "Nvidia", "TSLA": "Tesla",
               "AMZN": "Amazon", "GOOGL": "Google", "META": "Meta", "SPY": "S&P 500 ETF",
               "AMD": "AMD", "NFLX": "Netflix", "JPM": "JPMorgan", "V": "Visa",
               "WMT": "Walmart", "DIS": "Disney", "COIN": "Coinbase", "MSTR": "MicroStrategy"}
CRYPTO_TECH = ["bitcoin", "ethereum"]

# Feed RSS con alternative robuste. Se uno cade, le altre continuano a produrre news.
FEEDS = {
    "it": (
        "https://cryptonomist.ch/feed/",
        "https://www.criptovaluta.it/feed",
        "https://it.beincrypto.com/feed/",
        "https://www.milanofinanza.it/rss/mercati",
    ),
    "en": (
        "https://cointelegraph.com/rss",
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "https://decrypt.co/feed",
        "https://www.cnbc.com/id/100010915/device/rss/rss.html",
    ),
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
        "sources": "Fonti: CoinGecko · alternative.me · Yahoo Finance · Fed/ECB · RSS finanziari",
        "aff": "🔗 Apri un exchange (link referral): {url}",
        "aff_note": "<i>Link referral: se ti iscrivi possiamo ricevere una commissione, senza costi per te.</i>",
        "alerts_title": "🚨 <b>Alert di prezzo</b>",
        "alert_up": "forte rialzo",
        "alert_down": "forte ribasso",
        "alert_note": "<i>Movimenti sopra la soglia. Numeri, non consigli. I rischi restano tuoi.</i>",
        "movers": "🔥 <b>Top movimenti 24h</b>",
        "movers_note": "<i>Numeri, non consigli.</i>",
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
        "sources": "Sources: CoinGecko · alternative.me · Yahoo Finance · Fed/ECB · financial RSS",
        "aff": "🔗 Open an exchange (referral link): {url}",
        "aff_note": "<i>Referral link: if you sign up we may earn a commission, at no cost to you.</i>",
        "alerts_title": "🚨 <b>Price alert</b>",
        "alert_up": "sharp rise",
        "alert_down": "sharp drop",
        "alert_note": "<i>Moves above the threshold. Numbers, not advice. The risk is yours.</i>",
        "movers": "🔥 <b>Top 24h movers</b>",
        "movers_note": "<i>Numbers, not advice.</i>",
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


def _debug(msg):
    print(f"[vista-news] {msg}", file=sys.stderr, flush=True)


def crypto_prices(n=25):
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


def rss_direct(feed, k=8):
    """Legge l'RSS cosi' com'e', senza passare da un proxy: il proxy (rss2json)
    cachea i feed e le notizie arrivano in ritardo. Qui sono le ultime pubblicate."""
    raw = urllib.request.urlopen(urllib.request.Request(feed, headers=UA), timeout=20).read()
    root = ET.fromstring(raw)
    out = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        if title and link:
            out.append((html.unescape(title), link, (it.findtext("pubDate") or "").strip()))
    return out[:k]


def news(lang, k=4):
    out = []
    for feed in FEEDS.get(lang, ()):
        got = []
        try:
            got = rss_direct(feed, k)
            if not got:
                _debug(f"{lang}: feed empty or no items: {feed}")
        except Exception as e:
            _debug(f"{lang}: RSS direct failed for {feed}: {type(e).__name__}: {e}")
            try:
                u = "https://api.rss2json.com/v1/api.json?rss_url=" + urllib.parse.quote(feed, safe="")
                payload = get(u, tries=2)
                got = [(it["title"], it["link"], it.get("pubDate", ""))
                       for it in payload.get("items", [])[:k]]
                if not got:
                    _debug(f"{lang}: rss2json returned no items for {feed}")
            except Exception as e2:
                _debug(f"{lang}: rss2json fallback failed for {feed}: {type(e2).__name__}: {e2}")
        if got:
            out.extend(got)
    if not out:
        return []
    out.sort(key=lambda x: (x[2] if x[2] else ""), reverse=True)
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


# rest of file unchanged, omitted in patch for brevity
