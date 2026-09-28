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
    raise RuntimeError("Missing Telegram token. Set TG_TOKEN or TELEGRAM_BOT_TOKEN in .env or GitHub secret")
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

FEEDS = {
    "it": ("https://cryptonomist.ch/feed/",
           "https://www.criptovaluta.it/feed",
           "https://it.beincrypto.com/feed/",
           "https://www.milanofinanza.it/rss/mercati"),
    "en": ("https://cointelegraph.com/rss",
           "https://www.coindesk.com/arc/outboundfeeds/rss/",
           "https://decrypt.co/feed",
           "https://www.cnbc.com/id/100010915/device/rss/rss.html"),
}

# rest of file unchanged from repo version
