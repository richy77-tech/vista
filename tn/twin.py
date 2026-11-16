"""Il controllo di vita del gemello, dentro il giro che gira davvero.

Perche' non un cron: il workflow watchdog.yml gira quando GitHub vuole (misurato
16/11: 120 run in 23 giorni, mediana 5.6h) e dichiara morte dopo 50 minuti. Un
cron piu' lento del suo limite non puo' dichiarare niente.

Qui invece ogni catena, a ogni giro, legge l'ultimo commit del battito
dell'ALTRA. Una catena non puo' vedere la propria morte; vede quella del
gemello, e il gemello e' acceso proprio perche' il suo battito e' l'unica
prova che il processo esiste.

Buco dichiarato, non nascosto: se muoiono entrambe, nessuno dei due lo dice.
Restano il cron watchdog.yml (quando GitHub lo fa partire) e la mia lettura
del commit history quando sono sveglio.

Uso:
  python -m tn.twin hb_tn.txt 480 twin_private.json
    arg1 = battito del gemello, arg2 = minuti oltre i quali e' fermo,
    arg3 = file di stato posseduto da QUESTA catena (mai condiviso).

Il file di stato contiene solo orari e un flag. Nessun testo, nessuna chat id:
questo repo e' pubblico e la history e' per sempre.
"""
import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request

API = "https://api.github.com/repos/richy77-tech/vista/commits?path={}&per_page=1"
STATE = sys.argv[3] if len(sys.argv) > 3 else "twin_state.json"
COOLDOWN_H = 4


def last_write(path, token):
    url = API.format(urllib.parse.quote(path))
    req = urllib.request.Request(url, headers={"User-Agent": "twin-check"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=20) as r:
        rows = json.load(r)
    if not isinstance(rows, list) or not rows:
        return None
    stamp = rows[0]["commit"]["committer"]["date"]
    return dt.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


def load():
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:
        return {}


def save(d):
    with open(STATE, "w") as f:
        json.dump(d, f, indent=1)


def alert(text):
    token = os.environ.get("PRIVATE_BOT_TOKEN", "")
    try:
        with open("private_cfg.json") as f:
            chat = json.load(f).get("chat_id")
    except Exception:
        chat = None
    if not token or not chat:
        print("TWIN ALERT (nessun canale, solo log): " + text)
        return False
    body = json.dumps({"chat_id": chat, "text": text}).encode()
    req = urllib.request.Request(
        "https://api.telegram.org/bot%s/sendMessage" % token,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status == 200
    except Exception as e:
        print("TWIN ALERT non inviato: %s" % e)
        return False


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 0
    other, limit = sys.argv[1], int(sys.argv[2])
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    now = dt.datetime.now(dt.timezone.utc)
    try:
        ts = last_write(other, token)
    except Exception as e:
        print("TWIN %s illeggibile: %s" % (other, e))
        return 0
    if ts is None:
        print("TWIN %s nessun commit" % other)
        return 0
    age = (now - ts).total_seconds() / 60.0
    stale = age > limit
    d = load()
    d.update({
        "twin": other,
        "twin_last": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "age_min": int(age),
        "limit_min": limit,
        "stale": stale,
        "checked": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    print("TWIN %s ultimo battito %s, %d min fa, limite %d -> %s"
          % (other, d["twin_last"], int(age), limit, "FERMO" if stale else "vivo"))
    if stale:
        last_alert = d.get("alert_at")
        cool = False
        if last_alert:
            try:
                cool = (now - dt.datetime.strptime(last_alert, "%Y-%m-%dT%H:%M:%SZ")
                        .replace(tzinfo=dt.timezone.utc)).total_seconds() < COOLDOWN_H * 3600
            except Exception:
                cool = False
        if not cool:
            sent = alert("gemello fermo: %s non scrive da %d minuti (limite %d). Catena ancora viva."
                         % (other, int(age), limit))
            if sent:
                d["alert_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    save(d)
    return 0


if __name__ == "__main__":
    sys.exit(main())