"""Bot privato di Richy: stesso motore del canale, ma in DM.

Differenza dal canale:
- non e' un broadcast, e' una conversazione 1:1
- niente segnali: un brief all'ora scelta + alert solo sui break
- paper first: le operazioni si registrano, non si eseguono soldi veri

Config in private_cfg.json (asset, ora del brief). Stato in private_state.json.
Token dal secret PRIVATE_BOT_TOKEN. Il chat_id non e' un segreto.
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from . import marketdata as md
from . import calendar as cal
from . import paper
from . import card
from . import newsengine as ne
from . import newstrigger as nt
from . import chat

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CFG = os.path.join(ROOT, "private_cfg.json")
STATE = os.path.join(ROOT, "private_state.json")

DEFAULT_CFG = {
    "symbols": ["GC=F", "BTC-USD", "EURUSD=X"],
    "brief_hour_utc": 7,
    "chat_id": 6440475833,
}


def cfg():
    try:
        with open(CFG, encoding="utf-8") as f:
            return {**DEFAULT_CFG, **json.load(f)}
    except Exception:
        return dict(DEFAULT_CFG)


def save_cfg(c):
    with open(CFG, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False, indent=1)


def state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(s):
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)


def api(token, method, payload):
    body = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}", data=body)
    return json.load(urllib.request.urlopen(req, timeout=20))


def send(token, chat, text):
    try:
        return api(token, "sendMessage", {
            "chat_id": chat, "text": text, "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        })
    except Exception:
        # Se il testo non e' HTML valido (es. "S&P 500"), Telegram lo rifiuta:
        # lo rimando in chiaro invece di far cadere la risposta.
        return api(token, "sendMessage", {
            "chat_id": chat, "text": text,
            "disable_web_page_preview": "true",
        })


def send_photo(token, chat, png, caption=""):
    """Invia una card immagine (multipart, senza dipendenze esterne)."""
    import uuid
    boundary = "----tn" + uuid.uuid4().hex
    parts = []
    for k, v in (("chat_id", str(chat)), ("caption", caption), ("parse_mode", "HTML")):
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; '
        f'filename="brief.png"\r\nContent-Type: image/png\r\n\r\n'.encode() + png + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendPhoto", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def build_brief_image():
    c = cfg()
    rows = card.brief_rows(c["symbols"], labels())
    sub = datetime.now(timezone.utc).strftime("%d/%m %H:%M UTC")
    return card.render(rows, subtitle=sub,
                       footer="Paper register. Non e' un consiglio finanziario.")


def _fmt_price(p, cur):
    if p is None:
        return "n/d"
    if p >= 1000:
        s = f"{p:,.0f}"
    elif p >= 10:
        s = f"{p:,.2f}"
    else:
        s = f"{p:.4f}"
    return f"{s} {cur or ''}".strip()


def line_for(sym, labels):
    try:
        q = md.yahoo(sym)
    except Exception as e:
        return f"• {labels.get(sym, sym)}: fonte giu ({type(e).__name__})"
    ch = md.change_pct(q)
    r = md.rsi(q.get("closes") or [])
    arrow = "▲" if (ch or 0) > 0 else ("▼" if (ch or 0) < 0 else "=")
    parts = [f"• <b>{labels.get(sym, sym)}</b> {_fmt_price(q.get('price'), q.get('currency'))}"]
    if ch is not None:
        parts.append(f"{arrow} {ch:+.2f}%")
    if r is not None:
        tag = "ipercomprato" if r >= 70 else ("ipervenduto" if r <= 30 else "neutro")
        parts.append(f"RSI {r:.0f} ({tag})")
    return "  ".join(parts)


def labels():
    out = {}
    for g in md.GROUPS.values():
        for sym, lab, _ in g:
            out[sym] = lab
    out["BTC-USD"] = "BITCOIN"
    out["ETH-USD"] = "ETHEREUM"
    return out


def build_brief():
    c = cfg()
    lab = labels()
    L = ["<b>BRIEF PRIVATO</b> — " + datetime.now(timezone.utc).strftime("%d/%m %H:%M UTC"), ""]
    for s in c["symbols"]:
        L.append(line_for(s, lab))
    L.append("")
    events, err = cal.fetch_week()
    today = datetime.now(cal.ROME).date()
    todays = [e for e in events if e["ts"][:10] == today.isoformat()
              and e.get("impact") in ("HIGH", "MEDIUM")]
    if todays:
        L.append("<b>Oggi sul calendario</b>")
        for e in todays[:5]:
            t = e["ts"][11:16]
            L.append(f"• {t} {e['country']} · {e['title']} ({e['impact'].lower()})")
    elif err:
        L.append(f"Calendario non raggiungibile ({err}).")
    else:
        L.append("Calendario: nessun evento rilevante oggi.")
    L.append("")
    L.append("<i>" + paper.report() + "</i>")
    L.append("")
    L.append("<i>Paper register. Non e' consiglio finanziario.</i>")
    return "\n".join(L)


HELP = ("Comandi: /brief (manda ora il brief) · /asset (lista gli asset seguiti) · "
        "/stop (sospendi il brief giornaliero)\n"
        "Oppure scrivimi in italiano normale: \"come sta il mercato\", \"quanto sta "
        "il bitcoin\", \"notizie\", \"come vanno le operazioni\", \"chiudi tutto\".")


def poll(token, chat):
    """Risponde ai comandi. Ritorna il numero di update consumati."""
    try:
        data = api(token, "getUpdates", {"timeout": 0})
    except Exception:
        return 0
    ups = data.get("result") or []
    for u in ups:
        m = u.get("message") or {}
        txt = (m.get("text") or "").strip()
        low = txt.lower()
        if not txt:
            continue
        try:
            if low.startswith("/brief"):
                send(token, chat, build_brief())
            elif low.startswith("/asset"):
                send(token, chat, "Asset seguiti: " + ", ".join(cfg()["symbols"]))
            elif low.startswith("/stop"):
                s = state(); s["paused"] = True; save_state(s)
                send(token, chat, "Brief giornaliero sospeso. /brief per averlo a mano.")
            elif low.startswith("/start") or low.startswith("/help"):
                send(token, chat, "Attivo. " + HELP)
            elif low.startswith("/ping"):
                send(token, chat, "pong · " + datetime.now(timezone.utc).strftime("%H:%M UTC"))
            elif low.startswith("/riprendi") or "riprendi" in low or "riattiva" in low:
                s = state(); s["paused"] = False; save_state(s)
                send(token, chat, "Ripreso. Il brief torna all'ora scelta.")
            elif not low.startswith("/"):
                c = cfg()
                ans = chat.reply(txt, c)
                save_cfg(c)
                send(token, chat, ans[:4000])
        except Exception as e:
            # Un messaggio che rompe non deve far cadere il resto della coda.
            try:
                send(token, chat, f"Qualcosa non torna qui ({type(e).__name__}).")
            except Exception:
                pass
        # Ricevuta leggibile: prova che il bot ha letto davvero, visibile nel file di stato.
        try:
            s = state()
            s["last_in"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            save_state(s)
        except Exception:
            pass
    if ups:
        try:
            api(token, "getUpdates", {"offset": ups[-1]["update_id"] + 1})
        except Exception:
            pass
    return len(ups)


def auto(token, chat):
    """Poll dei comandi + un giro paper + brief giornaliero all'ora scelta."""
    poll(token, chat)
    c, s = cfg(), state()
    try:
        _, ev = paper.step(c["symbols"])
        for e in ev:
            send(token, chat, "paper · " + e)
    except Exception as e:
        print("paper giro fallito:", type(e).__name__)
    try:
        news, _err = ne.pipeline(per_source=8)
        _, nev = nt.run(c["symbols"], news)
        for e in nev:
            send(token, chat, "paper · " + e)
    except Exception as e:
        print("news trigger fallito:", type(e).__name__)
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    if s.get("paused"):
        return
    if now.hour >= c["brief_hour_utc"] and s.get("last_brief") != today:
        send(token, chat, build_brief())
        send_photo(token, chat, build_brief_image())
        s["last_brief"] = today
        save_state(s)


def main():
    token = os.environ.get("PRIVATE_BOT_TOKEN")
    if not token:
        print("PRIVATE_BOT_TOKEN mancante")
        return 1
    chat = cfg()["chat_id"]
    mode = sys.argv[1] if len(sys.argv) > 1 else "--auto"
    if mode == "--poll":
        # Solo risposta ai messaggi, veloce: cosi' l'agente risponde in pochi
        # secondi invece di aspettare il giro dei 20 minuti.
        poll(token, chat)
    elif mode == "--brief":
        send(token, chat, build_brief())
        send_photo(token, chat, build_brief_image())
    else:
        auto(token, chat)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
