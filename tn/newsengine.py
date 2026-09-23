"""News engine: ingestion -> filtro -> dedup -> classificazione -> impatto ->
asset -> sentiment -> Telegram. Nessuna fonte inventata: solo feed RSS reali,
verificati. Le fonti ufficiali (Fed, ECB) hanno tier 1 e pesano di piu'.
"""
import hashlib
import html
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from . import ai
from .http import fetch

# tier 1 = ufficiale (banca centrale / agenzia), tier 2 = media finanziario
SOURCES = [
    {"name": "Federal Reserve", "url": "https://www.federalreserve.gov/feeds/press_all.xml", "lang": "en", "tier": 1},
    {"name": "ECB", "url": "https://www.ecb.europa.eu/rss/press.html", "lang": "en", "tier": 1},
    {"name": "WSJ Markets", "url": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml", "lang": "en", "tier": 2},
    {"name": "MarketWatch", "url": "https://feeds.content.dowjones.io/public/rss/mw_topstories", "lang": "en", "tier": 2},
    {"name": "CNBC", "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html", "lang": "en", "tier": 2},
    {"name": "Yahoo Finance", "url": "https://finance.yahoo.com/news/rssindex", "lang": "en", "tier": 2},
    {"name": "Investing.com", "url": "https://www.investing.com/rss/news_25.rss", "lang": "en", "tier": 2},
    {"name": "Cointelegraph", "url": "https://cointelegraph.com/rss", "lang": "en", "tier": 2},
    {"name": "CoinDesk", "url": "https://www.coindesk.com/arc/outboundfeeds/rss/", "lang": "en", "tier": 2},
    {"name": "Decrypt", "url": "https://decrypt.co/feed", "lang": "en", "tier": 2},
    {"name": "Cryptonomist", "url": "https://cryptonomist.ch/feed/", "lang": "it", "tier": 2},
    {"name": "Criptovaluta.it", "url": "https://www.criptovaluta.it/feed", "lang": "it", "tier": 2},
    {"name": "BeInCrypto IT", "url": "https://it.beincrypto.com/feed/", "lang": "it", "tier": 2},
]


def _parse_date(s):
    if not s:
        return None
    try:
        return parsedate_to_datetime(s).astimezone(timezone.utc)
    except Exception:
        pass
    for f in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:19], f).replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


def _items(raw, limit):
    try:
        root = ET.fromstring(raw)
    except Exception:
        return []
    out = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        if not title or not link:
            continue
        summary = (it.findtext("description") or "").strip()
        if summary:
            summary = html.unescape(summary)
        out.append({"title": html.unescape(title), "url": link,
                    "summary": summary[:600], "pub": (it.findtext("pubDate") or "").strip()})
        if len(out) >= limit:
            break
    return out


def _id(it):
    return hashlib.sha1((it["url"] or it["title"]).encode("utf-8", "ignore")).hexdigest()[:16]


def fetch_all(per_source=12):
    """Ingestion da tutte le fonti. Una fonte che cade non blocca le altre."""
    items, errors = [], []
    for s in SOURCES:
        try:
            raw = fetch(s["url"], timeout=20, tries=2)
            for it in _items(raw, per_source):
                dt = _parse_date(it.get("pub"))
                items.append({
                    "id": _id(it), "title": it["title"], "url": it["url"],
                    "summary": it["summary"], "source": s["name"], "lang": s["lang"],
                    "tier": s["tier"],
                    "ts": (dt or datetime.now(timezone.utc)).isoformat(),
                })
        except Exception as e:
            errors.append(f"{s['name']}:{type(e).__name__}")
        time.sleep(0.2)
    return items, errors


def pipeline(per_source=12, dedup_thr=0.6):
    """Esegue l'intera catena e restituisce (news, errori)."""
    raw, errors = fetch_all(per_source)
    for it in raw:
        it.update(ai.enrich(it))
    news = ai.dedup(raw)
    news.sort(key=lambda x: ({"CRITICAL": 3, "HIGH": 2, "MEDIUM": 1, "LOW": 0}[x["impact"]],
                             x["ts"]), reverse=True)
    return news, errors
