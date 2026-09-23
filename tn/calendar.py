"""Calendario economico. Fonte gratuita senza chiave: feed settimanale
ForexFactory (nfs.faireconomy.media), JSON. Se il feed cade, si restituisce
lista vuota e si segnala l'errore: mai eventi inventati.
"""
import hashlib
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .http import get_json

FEED = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
ROME = ZoneInfo("Europe/Rome")

# paesi richiesti dal brief
WANTED = {"USD", "EUR", "GBP", "JPY", "CHF", "CNY", "CAD", "AUD", "NZD"}


def _ev_id(e):
    return hashlib.sha1((e.get("title", "") + e.get("date", "") + e.get("country", ""))
                        .encode()).hexdigest()[:16]


def fetch_week():
    """Eventi della settimana, normalizzati. Ritorna (eventi, errore)."""
    try:
        raw = get_json(FEED, tries=3)
    except Exception as e:
        return [], type(e).__name__
    out = []
    for e in raw:
        country = (e.get("country") or "").upper()
        if country not in WANTED:
            continue
        try:
            dt = datetime.fromisoformat(e["date"]).astimezone(ROME)
        except Exception:
            continue
        out.append({
            "id": _ev_id(e), "ts": dt.isoformat(), "country": country,
            "title": e.get("title", ""), "impact": (e.get("impact") or "Low").upper(),
            "forecast": e.get("forecast", ""), "previous": e.get("previous", ""),
            "actual": e.get("actual", "") or "DATA NOT AVAILABLE",
        })
    out.sort(key=lambda x: x["ts"])
    return out, None


def today(events=None):
    ev = events if events is not None else fetch_week()[0]
    d = datetime.now(ROME).date()
    return [e for e in ev if datetime.fromisoformat(e["ts"]).date() == d]


def upcoming(hours=24, events=None):
    ev = events if events is not None else fetch_week()[0]
    now = datetime.now(ROME)
    end = now + timedelta(hours=hours)
    return [e for e in ev if now <= datetime.fromisoformat(e["ts"]) <= end]


def soon(minutes=30, events=None):
    """Eventi ad alto impatto entro N minuti, per l'alert pre-evento."""
    ev = events if events is not None else fetch_week()[0]
    now = datetime.now(ROME)
    end = now + timedelta(minutes=minutes)
    return [e for e in ev
            if e["impact"] in ("HIGH", "MEDIUM")
            and now <= datetime.fromisoformat(e["ts"]) <= end]
