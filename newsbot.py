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

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # Pillow assente: le card degradano alla sola foto
    Image = None

TOKEN = os.environ["TG_TOKEN"]
CHAT = os.environ.get("TG_CHAT", "-1003559029410")
VISTA = "https://richy77-tech.github.io/vista/"
CHANNEL = "https://t.me/tradingnewsbot_richy"
# Link referral (facoltativo): se impostato, compare nel footer dichiarato come referral.
AFFILIATE = os.environ.get("VISTA_AFFILIATE", "")
# Soglia alert prezzo (variazione % 24h). Default 5%.
ALERT_PCT = float(os.environ.get("VISTA_ALERT_PCT", "5"))

UA = {"User-Agent": "Mozilla/5.0 (vista-newsbot)"}

STOCKS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "SPY"]
STOCK_NAMES = {"AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "Nvidia", "TSLA": "Tesla",
               "AMZN": "Amazon", "GOOGL": "Google", "META": "Meta", "SPY": "S&P 500 ETF"}
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
        "sources": "Fonti: CoinGecko · alternative.me · Yahoo Finance · RSS crypto",
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
        "sources": "Sources: CoinGecko · alternative.me · Yahoo Finance · crypto RSS",
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
    for feed in FEEDS[lang]:
        got = []
        try:
            got = rss_direct(feed, k)
        except Exception:
            try:
                u = "https://api.rss2json.com/v1/api.json?rss_url=" + urllib.parse.quote(feed, safe="")
                got = [(it["title"], it["link"], it.get("pubDate", ""))
                       for it in get(u, tries=2).get("items", [])[:k]]
            except Exception:
                pass
        out += got
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

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache.json")


def load_cache():
    try:
        with open(CACHE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(d):
    try:
        with open(CACHE, "w") as f:
            json.dump(d, f)
    except Exception:
        pass


def gather():
    """Scarica tutto una volta. Se una fonte cade, riusa l'ultimo dato buono
    dalla cache invece di stampare 'n/d' (le API gratuite ogni tanto throttlano)."""
    c = load_cache()
    d = {"crypto": None, "sentiment": None, "stocks": {}, "series": {},
         "news": {}, "errors": [], "stale": []}

    try:
        d["crypto"] = crypto_prices()
    except Exception as e:
        d["crypto"] = c.get("crypto")
        (d["stale"] if d["crypto"] else d["errors"]).append("crypto")
        if not d["crypto"]:
            d["errors"].append(type(e).__name__)
    time.sleep(1)

    try:
        d["sentiment"] = sentiment()
    except Exception as e:
        d["sentiment"] = c.get("sentiment")
        (d["stale"] if d["sentiment"] else d["errors"]).append("sentiment")
        if not d["sentiment"]:
            d["errors"].append(type(e).__name__)
    time.sleep(1)

    for s in STOCKS:
        try:
            closes, price, prev = stock_history(s)
            d["series"][s] = closes
            d["stocks"][s] = (price, prev)
        except Exception:
            if s in c.get("series", {}):
                d["series"][s] = c["series"][s]
                d["stocks"][s] = c.get("stocks", {}).get(s)
                d["stale"].append(s)
            else:
                d["stocks"][s] = None

    for cid in CRYPTO_TECH:
        try:
            d["series"][cid.upper()] = crypto_history(cid)
        except Exception:
            if cid.upper() in c.get("series", {}):
                d["series"][cid.upper()] = c["series"][cid.upper()]
                d["stale"].append(cid.upper())

    for lg in ("it", "en"):
        try:
            d["news"][lg] = news(lg)
        except Exception:
            d["news"][lg] = c.get("news", {}).get(lg, [])

    save_cache({k: d[k] for k in ("crypto", "sentiment", "stocks", "series", "news")})
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
    ts = datetime.now(ZoneInfo("Europe/Rome")).strftime("%d/%m %H:%M") + (" ora di Roma" if lang == "it" else " Rome time")
    L = [f"{t['title']} · {ts}", ""]
    if d.get("stale"):
        L.append("<i>alcuni dati sono l'ultimo aggiornamento disponibile</i>" if lang == "it"
                 else "<i>some data is the last available update</i>")
        L.append("")

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
        for c in d["crypto"][:8]:
            s = c["symbol"].upper()
            p = c["price_change_percentage_24h"] or 0
            L.append(f"{arrow(p)} <b>{s}</b> {money(c['current_price'])} ({p:+.1f}%)")
    else:
        L.append(f"<i>crypto n/d</i>")
    L.append("")

    # top movimenti 24h (tutti i 25 + azioni, non solo gli 8 mostrati)
    tm = sorted(movers(d, 0), key=lambda x: -abs(x[2]))[:3]
    if tm:
        L.append(t["movers"])
        for sym, price, p in tm:
            L.append(f"{arrow(p)} <b>{sym}</b> {money(price)} ({p:+.1f}%)")
        L.append(t["movers_note"])
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

    if AFFILIATE:
        L.append(t["aff"].format(url=f'<a href="{html.escape(AFFILIATE)}">exchange</a>'))
        L.append(t["aff_note"])
        L.append("")

    L.append(f"<i>{t['sources']}</i>")
    L.append(t["banner"].format(
        ch=f'<a href="{CHANNEL}">@tradingnewsbot_richy</a>',
        link=f'<a href="{VISTA}">Vista</a>'))
    return "\n".join(L)


# ---------- alert di prezzo ----------

ALERT_STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alert_state.json")
DIGEST_STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "digest_state.json")
NEWS_STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "news_state.json")
DIGEST_EVERY_H = float(os.environ.get("VISTA_DIGEST_EVERY_H", "6"))
# Le notizie invecchiano prima del digest: post dedicato ogni 2h, solo se c'e' roba nuova.
NEWS_EVERY_H = float(os.environ.get("VISTA_NEWS_EVERY_H", "2"))


def compose_news(fresh):
    """Solo le notizie non ancora postate. Un messaggio, IT + EN."""
    ts = datetime.now(ZoneInfo("Europe/Rome")).strftime("%d/%m %H:%M") + " ora di Roma"
    L = [f"🗞️ <b>Ultime notizie</b> · {ts}", ""]
    for lg, label in (("it", "IT"), ("en", "EN")):
        rows = [(t, l) for (g, t, l) in fresh if g == lg]
        if not rows:
            continue
        L.append(f"<b>{label}</b>")
        for title, link in rows[:4]:
            L.append(f'• <a href="{html.escape(link)}">{html.escape(title)}</a>')
        L.append("")
    L.append(T["it"]["banner"].format(
        ch=f'<a href="{CHANNEL}">@tradingnewsbot_richy</a>',
        link=f'<a href="{VISTA}">Vista</a>'))
    return "\n".join(L)


def _hours_since(iso):
    if not iso:
        return 1e9
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 3600
    except Exception:
        return 1e9


def load_json(p):
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return {}


def movers(d, pct):
    """Cripto e azioni con variazione 24h oltre la soglia, ordinate per ampiezza."""
    out = []
    for c in d.get("crypto") or []:
        p = c.get("price_change_percentage_24h") or 0
        if abs(p) >= pct:
            out.append((c["symbol"].upper(), c["current_price"], p))
    for s, val in (d.get("stocks") or {}).items():
        if val:
            price, prev = val
            p = (price / prev - 1) * 100 if price and prev else 0
            if abs(p) >= pct:
                out.append((s, price, p))
    out.sort(key=lambda x: -abs(x[2]))
    return out


def fresh_movers(d, pct):
    """Solo i movimenti nuovi: un simbolo viene ripostato quando entra in una
    fascia piu' ampia (5%, 10%, 15%...), non a ogni heartbeat. Evita lo spam."""
    st = load_json(ALERT_STATE)
    fresh = []
    for sym, price, p in movers(d, pct):
        b = int(abs(p) // pct)
        if b > st.get(sym, 0):
            fresh.append((sym, price, p))
        st[sym] = max(st.get(sym, 0), b)
    return fresh, st


def compose_alerts(lang, fresh):
    t = T[lang]
    if not fresh:
        return None
    ts = datetime.now(ZoneInfo("Europe/Rome")).strftime("%d/%m %H:%M") + (" ora di Roma" if lang == "it" else " Rome time")
    L = [f"{t['alerts_title']} · {ts}", ""]
    for sym, price, p in fresh:
        tag = t["alert_up"] if p > 0 else t["alert_down"]
        L.append(f"{arrow(p)} <b>{sym}</b> {money(price)} ({p:+.1f}%) · {tag}")
    L.append("")
    L.append(t["alert_note"])
    L.append(t["banner"].format(
        ch=f'<a href="{CHANNEL}">@tradingnewsbot_richy</a>',
        link=f'<a href="{VISTA}">Vista</a>'))
    return "\n".join(L)


def post_album(items, header=None):
    """Posta le icone come album di foto. Scarica le immagini (CoinGecko per le
    cripto, financialmodelingprep per le azioni) e le carica in multipart: piu'
    affidabile del far scaricare gli URL a Telegram."""
    media, files = [], {}
    for i, (src, cap) in enumerate(items):
        cap = cap or ""
        if i == 0 and header:
            cap = header + ("\n\n" + cap if cap else "")
        if isinstance(src, bytes):
            data = src
        else:
            try:
                data = urllib.request.urlopen(urllib.request.Request(src, headers=UA), timeout=30).read()
            except Exception:
                continue
        name = f"p{i}.png"
        files[name] = data
        m = {"type": "photo", "media": f"attach://{name}"}
        if cap:
            m["caption"], m["parse_mode"] = cap[:1024], "HTML"
        media.append(m)
    if not media:
        return False
    b = "----vista" + str(int(time.time()))
    out = []

    def field(name, value):
        out.append(f'--{b}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())

    field("chat_id", CHAT)
    field("media", json.dumps(media))
    for name, data in files.items():
        out.append(f'--{b}\r\nContent-Disposition: form-data; name="{name}"; filename="{name}"\r\n'
                   f'Content-Type: image/png\r\n\r\n'.encode() + data + b"\r\n")
    out.append(f"--{b}--\r\n".encode())
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TOKEN}/sendMediaGroup", data=b"".join(out),
        headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    try:
        r = json.load(urllib.request.urlopen(req, timeout=60))
    except urllib.error.HTTPError as e:
        print("sendMediaGroup", e.code, e.read().decode()[:400], file=sys.stderr)
        raise
    return r["ok"]


FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_R = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
_FONTS = {}


def _font(path, size):
    key = (path, size)
    if key not in _FONTS:
        try:
            _FONTS[key] = ImageFont.truetype(path, size)
        except Exception:
            _FONTS[key] = ImageFont.load_default()
    return _FONTS[key]


def fetch_icon(url):
    try:
        return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25).read()
    except Exception:
        return None


def make_card(icon_bytes, title, price, ch):
    """Card: icona vera a sinistra, prezzo e variazione % a destra, accanto.
    Verde/rosso in base al segno. Nessun consiglio, solo il numero."""
    if Image is None:
        return icon_bytes
    W, H = 900, 260
    img = Image.new("RGB", (W, H), (13, 17, 23))
    dr = ImageDraw.Draw(img)
    if icon_bytes:
        try:
            ic = Image.open(io.BytesIO(icon_bytes)).convert("RGBA")
            side = 150
            ic.thumbnail((side, side), Image.LANCZOS)
            canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
            canvas.paste(ic, ((side - ic.width) // 2, (side - ic.height) // 2), ic)
            img.paste(canvas, (48, (H - side) // 2), canvas)
        except Exception:
            pass
    f_title, f_price, f_ch = _font(FONT_B, 38), _font(FONT_B, 60), _font(FONT_B, 50)
    x = 245
    dr.text((x, 48), title, font=f_title, fill=(170, 178, 190))
    dr.text((x, 100), price, font=f_price, fill=(255, 255, 255))
    if ch is not None:
        col = (46, 204, 113) if ch >= 0 else (231, 76, 60)
        px = x + dr.textlength(price, font=f_price) + 28
        dr.text((px, 112), f"{ch:+.2f}%", font=f_ch, fill=col)
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def icons_album(d, lang):
    """5 cripto + azioni reali: card con icona vera accanto a prezzo e variazione."""
    items = []
    for c in (d.get("crypto") or [])[:5]:
        if not c.get("image"):
            continue
        ch = c.get("price_change_percentage_24h")
        card = make_card(fetch_icon(c["image"]), c["symbol"].upper(), money(c["current_price"]), ch)
        if card:
            items.append((card, f"<b>{c['symbol'].upper()}</b>"))
    for s in STOCKS:
        if len(items) >= 9:
            break
        st = (d.get("stocks") or {}).get(s)
        if not st or st[0] is None:
            continue
        price, prev = st
        ch = (price / prev - 1) * 100 if prev else None
        card = make_card(fetch_icon(f"https://financialmodelingprep.com/image-stock/{s}.png"),
                         f"{STOCK_NAMES.get(s, s)} ({s})", money(price), ch)
        if card:
            items.append((card, f"<b>{STOCK_NAMES.get(s, s)}</b> ({s})"))
    head = ("🪙 Cripto & 📈 Azioni" if lang == "it" else "🪙 Crypto & 📈 Stocks")
    head += " · " + datetime.now(ZoneInfo("Europe/Rome")).strftime("%d/%m %H:%M")
    return items, head


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
    send = "--send" in sys.argv

    if "--auto" in sys.argv:
        # Chiamato dai miei heartbeat: posta il digest solo se sono passate
        # DIGEST_EVERY_H ore, e gli alert solo se un movimento e' nuovo.
        # Cosi' il canale si aggiorna da solo senza che nessuno lo lanci a mano.
        st = load_json(DIGEST_STATE)
        last = st.get("last")
        due, age = True, 0.0
        if last:
            try:
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() / 3600
                due = age >= DIGEST_EVERY_H
            except Exception:
                due = True
        if due:
            for lg in ("it", "en"):
                post(compose(lg, d))
            items, head = icons_album(d, "it")
            if items:
                post_album(items, head)
            with open(DIGEST_STATE, "w") as f:
                json.dump({"last": datetime.now(timezone.utc).isoformat()}, f)
            print("DIGEST: postato (IT+EN) + icone", len(items))
        else:
            print(f"DIGEST: salto, ultimo {age:.1f}h fa (< {DIGEST_EVERY_H}h)")

        # Notizie: post dedicato, ogni NEWS_EVERY_H, solo se c'e' qualcosa di nuovo.
        nst = load_json(NEWS_STATE)
        if _hours_since(nst.get("last")) >= NEWS_EVERY_H:
            seen = set(nst.get("seen", []))
            fresh_n = [(lg, t, l) for lg in ("it", "en")
                       for (t, l, _) in ((d.get("news") or {}).get(lg) or [])
                       if l not in seen]
            if fresh_n:
                post(compose_news(fresh_n))
                seen |= {l for _, _, l in fresh_n}
                print("NEWS: postato", len(fresh_n))
            else:
                print("NEWS: nessuna novita")
            nst["seen"] = list(seen)[-300:]
            nst["last"] = datetime.now(timezone.utc).isoformat()
            with open(NEWS_STATE, "w") as f:
                json.dump(nst, f)
        else:
            print(f"NEWS: salto, ultimo {_hours_since(nst.get('last')):.1f}h fa")

        fresh, astate = fresh_movers(d, ALERT_PCT)
        if fresh:
            for lg in ("it", "en"):
                post(compose_alerts(lg, fresh))
            with open(ALERT_STATE, "w") as f:
                json.dump(astate, f)
            print("ALERT: postato", [m[0] for m in fresh])
        else:
            print("ALERT: nessuno nuovo")
        sys.exit(0)

    if "--alerts" in sys.argv:
        fresh, st = fresh_movers(d, ALERT_PCT)
        if not fresh:
            print("ALERTS: nessun movimento nuovo sopra", ALERT_PCT, "%")
            sys.exit(0)
        if send:
            with open(ALERT_STATE, "w") as f:
                json.dump(st, f)
        for lg in ("it", "en"):
            txt = compose_alerts(lg, fresh)
            print("=" * 20, "ALERT", lg.upper(), "=" * 20)
            print(txt)
            if send:
                print("\nSENT:", post(txt))
        sys.exit(0)

    if "--news" in sys.argv:
        nst = load_json(NEWS_STATE)
        seen = set(nst.get("seen", []))
        fresh_n = [(lg, t, l) for lg in ("it", "en")
                   for (t, l, _) in ((d.get("news") or {}).get(lg) or [])
                   if l not in seen]
        print(compose_news(fresh_n) if fresh_n else "NEWS: nessuna novita")
        if send and fresh_n:
            print("SENT:", post(compose_news(fresh_n)))
        sys.exit(0)

    if "--icons" in sys.argv:
        items, head = icons_album(d, "it")
        for u, c in items:
            print(c.replace("<b>", "").replace("</b>", ""), u)
        if send:
            print("SENT:", post_album(items, head))
        sys.exit(0)

    langs = ["it", "en"] if send else [sys.argv[1] if len(sys.argv) > 1 else "it"]
    for lg in langs:
        txt = compose(lg, d)
        print("=" * 20, lg.upper(), "=" * 20)
        print(txt)
        if send:
            print("\nSENT:", post(txt))
    if send:
        items, head = icons_album(d, "it")
        if items:
            print("ICONS:", post_album(items, head))
