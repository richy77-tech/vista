"""Due post extra chiesti da Richy, tenuti fuori dal digest per non appesantirlo:

  - preview domenica sera: "cosa guardare lunedi'" (catalizzatori + riapertura);
  - mini-recap a chiusura della seduta USA.

Regole di casa invariate: numeri = fatti, niente previsioni, niente consigli.
Se una fonte manca, la riga semplicemente non compare.
"""
import html
from datetime import datetime
from zoneinfo import ZoneInfo

from . import marketdata as md
from . import weekly as wk

ROME = ZoneInfo("Europe/Rome")

# righe del recap di chiusura: (gruppo, label, emoji)
CLOSE_ROWS = [
    ("indices", "S&P 500", "📊"),
    ("indices", "NASDAQ", "📊"),
    ("indices", "DOW", "📊"),
    ("indices", "VIX", "🌪️"),
    ("metals", "GOLD", "🥇"),
    ("energy", "WTI OIL", "🛢️"),
]


def _find(d, group, label):
    for q in (d.get("market") or {}).get(group, []):
        if q.get("label") == label:
            return q
    return None


def _pstr(p):
    if p is None:
        return "n/d"
    if p >= 100:
        return f"{p:,.0f}"
    if p >= 1:
        return f"{p:,.2f}"
    return f"{p:.4f}"


def _chg(ch):
    return "n/d" if ch is None else f"{ch:+.2f}%"


def compose_close_recap(lang, d):
    """Mini-recap della seduta USA. Solo fatti: variazioni del giorno."""
    it = lang == "it"
    rows = []
    for group, label, emo in CLOSE_ROWS:
        q = _find(d, group, label)
        if not q:
            continue
        ch = md.change_pct(q)
        rows.append((emo, label, q.get("price"), ch))
    for cid, label, emo in (("BITCOIN", "BTC", "₿"), ("ETHEREUM", "ETH", "Ξ")):
        closes = (d.get("series") or {}).get(cid)
        if not closes or len(closes) < 2:
            continue
        ch = (closes[-1] / closes[-2] - 1) * 100 if closes[-2] else None
        rows.append((emo, label, closes[-1], ch))
    if not rows:
        return None

    now = datetime.now(ROME)
    L = ["⚡ <b>TRADING NEWS AI</b>",
         (f"🔔 <b>CHIUSURA USA</b> · {now.strftime('%d/%m %H:%M')}" if it
          else f"🔔 <b>US CLOSE</b> · {now.strftime('%d/%m %H:%M')}"), ""]
    for emo, label, price, ch in rows:
        L.append(f"{emo} <b>{label}</b> {_pstr(price)} ({_chg(ch)})")

    valid = [(l, c) for _, l, _, c in rows if c is not None]
    if valid:
        best = max(valid, key=lambda x: x[1])
        worst = min(valid, key=lambda x: x[1])
        L.append("")
        L.append((f"La seduta in una riga: meglio <b>{best[0]}</b> {_chg(best[1])}, "
                  f"peggio <b>{worst[0]}</b> {_chg(worst[1])}.") if it
                 else (f"The session in one line: best <b>{best[0]}</b> {_chg(best[1])}, "
                       f"worst <b>{worst[0]}</b> {_chg(worst[1])}."))
    L.append("")
    L.append("<i>Numeri di chiusura, nessun segnale. Informazione, non consulenza.</i>"
             if it else
             "<i>Closing numbers, no signals. Information, not advice.</i>")
    return "\n".join(L)


def compose_sunday_preview(lang, d):
    """Domenica sera: cosa guardare lunedi'. Catalizzatori + riapertura."""
    it = lang == "it"
    ahead = wk.week_ahead(d.get("events"))
    L = ["⚡ <b>TRADING NEWS AI</b>",
         ("🗓️ <b>DOMENICA SERA</b> · cosa guardare lunedì" if it
          else "🗓️ <b>SUNDAY EVENING</b> · what to watch Monday"),
         "",
         ("Settimana nuova. I mercati riaprono lunedì: ecco cosa c'è in calendario."
          if it else
          "New week. Markets reopen Monday: here is what is on the calendar."),
         ""]
    high = [e for e in ahead if e["impact"] == "HIGH"]
    picks = (high or ahead)[:5]
    if picks:
        L.append("📅 <b>In calendario</b>" if it else "📅 <b>On the calendar</b>")
        for e in picks:
            emo = "🔴" if e["impact"] == "HIGH" else "🟠"
            day = datetime.fromisoformat(e["ts"]).strftime("%a %d/%m")
            L.append(f"{emo} {day} {e['ts'][11:16]} {e['country']} "
                     f"{html.escape(e['title'])}")
    else:
        L.append(("<i>Il calendario della settimana non è ancora uscito dalla fonte. "
                  "Arriva lunedì.</i>" if it else
                  "<i>Next week's calendar is not out from the source yet. "
                  "It lands Monday.</i>"))
    L.append("")
    bar = wk.barometer(d)
    if bar:
        L.append(f"🧭 Barometro <b>{bar['score']:.0f}/100</b> · {wk._band(bar['score'], lang)}")
        L.append("<i>Composito euristico, non un fatto né una previsione.</i>" if it
                 else "<i>Heuristic composite, not a fact nor a forecast.</i>")
        L.append("")
    L.append(("Buona domenica. Lunedì si riparte." if it
              else "Have a good Sunday. Back at it Monday."))
    L.append("")
    L.append("<i>Informazione, non consulenza finanziaria.</i>" if it
             else "<i>Information, not financial advice.</i>")
    return "\n".join(L)


def due_close(now_ro, hours_since):
    """True una volta al giorno, feriali, nella finestra di chiusura USA (~22 Roma)."""
    if now_ro.weekday() >= 5:
        return False
    if not (22 <= now_ro.hour < 23):
        return False
    return hours_since >= 12


def due_sunday(now_ro, hours_since):
    """True una volta, domenica sera (18-21 Roma)."""
    if now_ro.weekday() != 6:
        return False
    if not (18 <= now_ro.hour < 21):
        return False
    return hours_since >= 12
