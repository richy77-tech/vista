"""Telegram commands. Polling singolo (una passata): la sandbox non puo' tenere
un demone acceso, quindi si processano gli update pendenti a ogni chiamata.
Comandi mantenuti e ampliati rispetto a prima.
"""
import html
import json
import os
import urllib.parse
import urllib.request

from . import calendar as cal
from . import marketdata as md
from .http import fetch, get_json

HELP = {
    "it": (
        "⚡ <b>TRADING NEWS AI</b>\n"
        "/news ultime notizie\n/breaking solo impatto alto\n/btc /crypto cripto\n"
        "/gold oro e argento\n/forex valute\n/stocks azioni\n/macro indici\n"
        "/calendar calendario economico\n/alerts alert attivi\n"
        "/sentiment sentiment di mercato\n/status stato sistema\n/settings impostazioni"
    ),
    "en": (
        "⚡ <b>TRADING NEWS AI</b>\n"
        "/news latest news\n/breaking high impact only\n/btc /crypto crypto\n"
        "/gold gold and silver\n/forex currencies\n/stocks equities\n/macro indices\n"
        "/calendar economic calendar\n/alerts active alerts\n"
        "/sentiment market sentiment\n/status system status\n/settings settings"
    ),
}

DISCLAIMER = ("<i>Informazioni a scopo informativo ed educativo. Non costituiscono "
              "consulenza finanziaria né raccomandazione di investimento. I mercati "
              "finanziari comportano rischi.</i>")


def _crypto(n=8):
    d = get_json("https://api.coingecko.com/api/v3/coins/markets"
                 "?vs_currency=usd&order=market_cap_desc&per_page=25&page=1&sparkline=false")
    stables = {"USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDE"}
    out = [c for c in d if c["symbol"].upper() not in stables][:n]
    lines = []
    for c in out:
        p = c.get("price_change_percentage_24h") or 0
        emo = "🟢" if p >= 0 else "🔴"
        lines.append(f"{emo} <b>{c['symbol'].upper()}</b> ${c['current_price']:,.2f} ({p:+.1f}%)")
    return lines


def _fmt_group(g, q):
    p = q.get("price")
    ch = md.change_pct(q)
    emo = "🟢" if (ch or 0) >= 0 else "🔴"
    chs = f" ({ch:+.2f}%)" if ch is not None else ""
    return f"{emo} {q.get('emoji','')} <b>{q.get('label')}</b> {p}{chs}"


def build(cmd, ctx):
    """Ritorna il testo di risposta a un comando. ctx porta i dati gia' scaricati."""
    if cmd in ("/start", "/help"):
        return HELP["it"] + "\n\n" + HELP["en"]
    if cmd == "/status":
        s = ctx.get("status", {})
        rows = "\n".join(f"{'🟢' if ok else '🔴'} {k}" for k, ok in s.items())
        return "⚙️ <b>System status</b>\n" + (rows or "n/d")
    if cmd == "/news":
        ns = ctx.get("news") or []
        lines = [f"📰 <b>News</b>"]
        for n in ns[:6]:
            lines.append(f"• <a href=\"{html.escape(n['url'])}\">{html.escape(n['title'])}</a>")
        return "\n".join(lines) + "\n\n" + DISCLAIMER
    if cmd == "/breaking":
        ns = [n for n in (ctx.get("news") or []) if n["impact"] in ("HIGH", "CRITICAL")]
        if not ns:
            return "🚨 <b>Breaking</b>\nNessuna notizia ad alto impatto al momento."
        out = ["🚨 <b>BREAKING</b>"]
        for n in ns[:5]:
            assets = " ".join(n.get("assets") or [])
            out.append(f"<b>{html.escape(n['title'])}</b>\n🔴 IMPACT: {n['impact']}"
                       + (f"\nAsset: {assets}" if assets else "")
                       + f"\n<a href=\"{html.escape(n['url'])}\">{html.escape(n['source'])}</a>")
        return "\n\n".join(out)
    if cmd == "/btc":
        return "₿ <b>BTC</b>\n" + "\n".join(_crypto(1))
    if cmd == "/crypto":
        return "🪙 <b>Crypto</b>\n" + "\n".join(_crypto(8))
    if cmd == "/gold":
        g = (ctx.get("market") or {}).get("metals") or []
        return "🥇 <b>Gold & Silver</b>\n" + "\n".join(_fmt_group("metals", q) for q in g)
    if cmd == "/forex":
        g = (ctx.get("market") or {}).get("forex") or []
        return "💵 <b>Forex</b>\n" + "\n".join(_fmt_group("forex", q) for q in g)
    if cmd == "/stocks":
        st = ctx.get("stocks") or {}
        lines = ["📈 <b>Stocks</b>"]
        for s, v in st.items():
            if v:
                price, prev = v
                p = (price / prev - 1) * 100 if prev else 0
                lines.append(f"{'🟢' if p >= 0 else '🔴'} <b>{s}</b> {price:,.2f} ({p:+.1f}%)")
        return "\n".join(lines)
    if cmd == "/macro":
        g = (ctx.get("market") or {}).get("indices") or []
        return "📊 <b>Indices</b>\n" + "\n".join(_fmt_group("indices", q) for q in g)
    if cmd == "/calendar":
        ev = cal.today(ctx.get("events"))
        if not ev:
            return "📅 <b>Calendar</b>\nNessun evento oggi."
        out = ["📅 <b>Economic calendar</b>"]
        for e in ev:
            t = e["ts"][11:16]
            out.append(f"⏰ {t} <b>{e['country']}</b> {html.escape(e['title'])} · {e['impact']}"
                       + (f"\nForecast {e['forecast']} · Prev {e['previous']}"
                          if e['forecast'] or e['previous'] else ""))
        return "\n".join(out)
    if cmd == "/alerts":
        return "🚨 <b>Alerts</b>\nSoglia movimento e alert pre-evento attivi. Usa /settings."
    if cmd == "/sentiment":
        try:
            fng = get_json("https://api.alternative.me/fng/?limit=1")["data"][0]
            return (f"🤖 <b>Market sentiment</b>\nFear &amp; Greed: <b>{fng['value']}</b> "
                    f"({fng['value_classification']})\n\n{DISCLAIMER}")
        except Exception:
            return "🤖 <b>Market sentiment</b>\nDATA NOT AVAILABLE"
    if cmd == "/settings":
        return ("⚙️ <b>Settings</b>\nDigest 6h · News 2h · Alert soglia "
                f"{os.environ.get('VISTA_ALERT_PCT', '5')}%\n"
                "Solo l'amministratore modifica fonti, soglie e frequenze.")
    return "Comando non riconosciuto. /help"


def set_commands(token):
    cmds = ["start", "help", "news", "breaking", "btc", "crypto", "gold", "forex",
            "stocks", "macro", "calendar", "alerts", "sentiment", "status", "settings"]
    body = urllib.parse.urlencode({
        "commands": json.dumps([{"command": c, "description": c} for c in cmds])}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(
            f"https://api.telegram.org/bot{token}/setMyCommands", data=body), timeout=20)
        return True
    except Exception:
        return False


def send(token, chat_id, text):
    body = urllib.parse.urlencode({
        "chat_id": chat_id, "text": text, "parse_mode": "HTML",
        "disable_web_page_preview": "true"}).encode()
    urllib.request.urlopen(urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", data=body), timeout=20)


def poll_once(token, ctx, state_path):
    """Legge gli update pendenti, risponde ai comandi, salva l'offset."""
    st = {}
    try:
        with open(state_path) as f:
            st = json.load(f)
    except Exception:
        pass
    offset = st.get("offset", 0)
    url = f"https://api.telegram.org/bot{token}/getUpdates?timeout=0"
    if offset:
        url += f"&offset={offset}"
    try:
        data = json.loads(fetch(url, timeout=20, tries=2))
    except Exception:
        return 0
    n = 0
    for u in data.get("result", []):
        st["offset"] = u["update_id"] + 1
        msg = u.get("message") or u.get("channel_post") or {}
        text = (msg.get("text") or "").strip()
        chat = (msg.get("chat") or {}).get("id")
        if not text or not chat:
            continue
        cmd = text.split()[0].split("@")[0].lower()
        try:
            send(token, chat, build(cmd, ctx))
            n += 1
        except Exception:
            pass
    with open(state_path, "w") as f:
        json.dump(st, f)
    return n
