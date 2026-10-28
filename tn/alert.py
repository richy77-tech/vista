"""Avviso diretto a Richy quando una catena si ferma.

Il problema vero non e' che il loop si rompe, e' che si rompe in silenzio:
il rilancio fa `curl -s` e un 401 non lo vede nessuno. Questo manda un
messaggio sul bot privato ogni volta che un rilancio o il watchdog toccano
un guasto, cosi' il guasto fa rumore invece di deserto.

Senza PRIVATE_BOT_TOKEN esce pulito (0): non deve mai essere la cosa che
rompe la catena che sta cercando di salvare.
"""

import os
import sys
import urllib.parse
import urllib.request

CHAT = os.environ.get("ALERT_CHAT", "6440475833")


def send(text):
    token = os.environ.get("PRIVATE_BOT_TOKEN")
    if not token:
        print("alert: nessun token, salto")
        return False
    data = urllib.parse.urlencode({"chat_id": CHAT, "text": text[:3900]}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", data=data
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            print("alert inviato", r.status)
            return True
    except Exception as exc:  # noqa: BLE001 - l'avviso non deve mai far fallire altro
        print("alert fallito:", exc)
        return False


if __name__ == "__main__":
    msg = " ".join(sys.argv[1:]).strip() or "watchdog: guasto senza dettagli"
    send(msg)