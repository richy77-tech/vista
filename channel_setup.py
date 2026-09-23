#!/usr/bin/env python3
"""Vista channel setup: descrizione professionale + messaggio fissato (about/disclaimer).
Uso: TG_TOKEN=... python3 channel_setup.py
"""
import json
import os
import sys
import urllib.parse
import urllib.request

TOKEN = os.environ["TG_TOKEN"]
CHAT = os.environ.get("TG_CHAT", "-1003559029410")
CHANNEL = "https://t.me/tradingnewsbot_richy"
VISTA = "https://richy77-tech.github.io/vista/"

DESC = (
    "Vista · mercati crypto e azioni, in italiano e inglese. "
    "Numeri, medie e regole di rischio, non consigli di investimento. "
    "Dati da fonti pubbliche (CoinGecko, alternative.me, Yahoo Finance, testate crypto). "
    "I rischi restano di chi legge."
)

WELCOME = """📌 <b>Benvenuto su Vista</b>

Qui trovi un digest di mercato, in italiano e in inglese, con:
• 🪙 cripto (prezzi e variazioni 24h)
• 📈 azioni (watchlist)
• 🧭 lettura tecnica (medie e RSI)
• 🌡️ sentiment community (Fear &amp; Greed, dominanza BTC)
• 📰 notizie da testate crypto
• 🧯 regole per operare in sicurezza

<b>Come si legge</b>
Sono numeri e medie, non previsioni. Nessun "compra" o "vendi": quello decide chi legge, con i suoi soldi e i suoi rischi.

<b>Fonti</b>
CoinGecko · alternative.me (Fear &amp; Greed) · Yahoo Finance · RSS di testate crypto italiane ed estere.

<b>Disclaimer</b>
Contenuti informativi. Non sono consulenza finanziaria. Nessuna garanzia di risultato.

<b>Link</b>
Dashboard live: <a href="{vista}">Vista</a>
Canale: <a href="{ch}">@tradingnewsbot_richy</a>"""


def api(method, **params):
    body = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/{method}", data=body)
    try:
        return json.load(urllib.request.urlopen(req, timeout=20))
    except urllib.error.HTTPError as e:
        return json.load(e)


def main():
    r = api("setChatDescription", chat_id=CHAT, description=DESC)
    print("description:", r.get("ok"), r.get("description") if not r.get("ok") else "")

    r = api("sendMessage", chat_id=CHAT, text=WELCOME.format(vista=VISTA, ch=CHANNEL),
            parse_mode="HTML", disable_web_page_preview="true")
    print("send:", r.get("ok"))
    if not r.get("ok"):
        print(r)
        sys.exit(1)
    mid = r["result"]["message_id"]
    r = api("pinChatMessage", chat_id=CHAT, message_id=mid, disable_notification="true")
    print("pin:", r.get("ok"), r.get("description", "") if not r.get("ok") else "")


if __name__ == "__main__":
    main()
