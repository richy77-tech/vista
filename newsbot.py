#!/usr/bin/env python3
"""Post a crypto digest to the Telegram channel. Free APIs only, no keys."""
import json, os, sys, urllib.parse, urllib.request
from datetime import datetime, timezone

TOKEN = os.environ["TG_TOKEN"]
CHAT = os.environ.get("TG_CHAT", "-1003559029410")
VISTA = "https://richy77-tech.github.io/vista/"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "vista-newsbot/1.0"})
    return json.load(urllib.request.urlopen(req, timeout=20))


def prices(n=8):
    d = get("https://api.coingecko.com/api/v3/coins/markets"
            "?vs_currency=usd&order=market_cap_desc&per_page=25&page=1&sparkline=false")
    return d[:n]


def news(k=3):
    out = []
    for feed in ("https://cointelegraph.com/rss", "https://decrypt.co/feed"):
        u = "https://api.rss2json.com/v1/api.json?rss_url=" + urllib.parse.quote(feed, safe="")
        try:
            for it in get(u).get("items", [])[:k]:
                out.append((it["title"], it["link"], it.get("pubDate", "")))
        except Exception:
            pass
    out.sort(key=lambda x: x[2], reverse=True)
    return out[:k]


def arrow(p):
    return "🟢" if p >= 0 else "🔴"


def compose():
    ps = prices()
    ns = news()
    ts = datetime.now(timezone.utc).strftime("%d/%m %H:%M UTC")
    lines = [f"📊 *Crypto* · {ts}", ""]
    for c in ps:
        s, p = c["symbol"].upper(), c["price_change_percentage_24h"] or 0
        price = f"${c['current_price']:,.2f}" if c["current_price"] >= 1 else f"${c['current_price']:.4f}"
        lines.append(f"{arrow(p)} {s} {price} ({p:+.1f}%)")
    if ns:
        lines += ["", "📰 *News*"]
        for t, l, _ in ns:
            lines.append(f"• [{t}]({l})")
    lines += ["", f"🔎 Tutto su Vista: {VISTA}", "_Non è consulenza finanziaria._"]
    return "\n".join(lines)


def post(text):
    body = urllib.parse.urlencode({
        "chat_id": CHAT, "text": text,
        "parse_mode": "Markdown", "disable_web_page_preview": "true",
    }).encode()
    r = json.load(urllib.request.urlopen(
        urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=body), timeout=20))
    return r["ok"]


if __name__ == "__main__":
    t = compose()
    print(t)
    if "--send" in sys.argv:
        print("\nSENT:", post(t))
