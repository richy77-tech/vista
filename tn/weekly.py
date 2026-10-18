"""Riepilogo settimanale + settimana entrante + barometro composito.

Regole di casa, le stesse del resto del bot:
  - nessun dato inventato: se una fonte manca, il campo resta assente o "n/d";
  - numeri e calendario sono FATTI; il barometro e' una INTERPRETAZIONE
    euristica, dichiarata come tale, mai una previsione di prezzo.
"""
import html
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import marketdata as md

ROME = ZoneInfo("Europe/Rome")

# asset settimanali: (gruppo, label, chiave breve, emoji)
WEEKLY = [
    ("metals", "GOLD", "GOLD", "🥇"),
    ("forex", "DXY", "DXY", "💵"),
    ("indices", "S&P 500", "SP500", "📊"),
    ("indices", "NASDAQ", "NASDAQ", "📊"),
    ("indices", "VIX", "VIX", "🌪️"),
    ("metals", "SILVER", "SILVER", "🥈"),
    ("energy", "WTI OIL", "WTI", "🛢️"),
]


# mappa settimanale: copre tutti i mercati del bot, non solo i 7 principali
MARKET_MAP = [
    ("indices", "Azioni e indici", "Stocks & indices",
     ["S&P 500", "NASDAQ", "DOW", "RUSSELL 2000", "FTSE 100", "DAX", "NIKKEI"]),
    ("metals", "Metalli", "Metals",
     ["GOLD", "SILVER", "PLATINUM", "COPPER"]),
    ("energy", "Energia", "Energy",
     ["WTI OIL", "BRENT", "NAT GAS"]),
    ("forex", "Valute", "Currencies",
     ["EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD", "DXY"]),
]


def _tech(closes):
    """Solo numeri: posizione vs medie + RSI. Nessun consiglio."""
    if not closes or len(closes) < 21:
        return {}
    price = closes[-1]
    m20, m50 = md.ma(closes, 20), md.ma(closes, 50)
    t = None
    if m20 and m50:
        t = ("above" if price > m20 > m50 else
             "below" if price < m20 < m50 else "between")
    return {"trend": t, "rsi": md.rsi(closes)}


def _tech_str(t, lang):
    if not t:
        return None
    it = lang == "it"
    bits = []
    tr = t.get("trend")
    if tr:
        bits.append({"above": "sopra trend" if it else "above trend",
                     "below": "sotto trend" if it else "below trend",
                     "between": "tra le medie" if it else "between averages"}[tr])
    r = t.get("rsi")
    if r is not None:
        tag = (("ipercomprato" if it else "overbought") if r >= 70 else
               ("ipervenduto" if it else "oversold") if r <= 30 else "")
        bits.append(f"RSI {r:.0f}" + (f" {tag}" if tag else ""))
    return ", ".join(bits) or None


def market_week(d):
    """Un blocco per gruppo: variazione a ~5 sedute + lettura meccanica."""
    out = []
    for group, it_lbl, en_lbl, labels in MARKET_MAP:
        rows = []
        for label in labels:
            q = _q(d, group, label)
            if not q:
                continue
            rows.append({"label": label, "chg": _pct(q.get("closes"), 5),
                         "tech": _tech(q.get("closes"))})
        if any(r["chg"] is not None for r in rows):
            out.append({"group": group, "it": it_lbl, "en": en_lbl, "rows": rows})
    return out


def crypto_week(d, n=5):
    """Cripto: migliori e peggiori a 7 giorni sul listino. Solo cio' che esiste."""
    rows = []
    for c in (d.get("crypto") or []):
        ch = c.get("price_change_percentage_7d_in_currency")
        if ch is None:
            ch = c.get("price_change_percentage_7d")
        if ch is None:
            continue
        rows.append({"sym": (c.get("symbol") or "?").upper(),
                     "price": c.get("current_price"), "chg": float(ch)})
    if not rows:
        return [], []
    rows.sort(key=lambda r: r["chg"], reverse=True)
    best = rows[:n]
    rest = rows[n:]
    worst = list(reversed(rest[-n:])) if rest else []
    return best, worst


def stock_week(d, n=8):
    """Azioni seguite dal bot: variazione a ~5 sedute, ordinate. Il paniere
    settimanale, non solo i soliti 7."""
    skip = {"BITCOIN", "ETHEREUM"}
    rows = []
    for sym, closes in (d.get("series") or {}).items():
        if sym in skip or not closes:
            continue
        ch = _pct(closes, 5)
        if ch is None:
            continue
        rows.append({"sym": sym, "chg": ch, "tech": _tech(closes)})
    rows.sort(key=lambda r: r["chg"], reverse=True)
    return rows[:n]


def _pct(closes, back):
    """Variazione % su `back` sedute. None se i dati non bastano."""
    if not closes or len(closes) <= back:
        return None
    a, b = closes[-1 - back], closes[-1]
    if not a:
        return None
    return (b / a - 1) * 100


def _q(d, group, label):
    for q in (d.get("market") or {}).get(group, []):
        if q.get("label") == label:
            return q
    return None


def week_recap(d):
    """Rendimento delle ultime ~5 sedute per asset. Solo cio' che esiste."""
    rows = []
    for group, label, key, emo in WEEKLY:
        q = _q(d, group, label)
        if not q:
            continue
        ch = _pct(q.get("closes"), 5)
        rows.append({"key": key, "label": label, "emoji": emo,
                     "price": q.get("price"), "chg": ch})
    for cid, key, label, emo in (("BITCOIN", "BTC", "BTC", "₿"),
                                 ("ETHEREUM", "ETH", "ETH", "Ξ")):
        closes = (d.get("series") or {}).get(cid)
        ch = _pct(closes, 7)
        if ch is None:
            continue
        price = closes[-1] if closes else None
        rows.append({"key": key, "label": label, "emoji": emo,
                     "price": price, "chg": ch})
    return [r for r in rows if r["chg"] is not None or r["price"] is not None]


def week_ahead(events, days=7):
    """Eventi HIGH/MEDIUM nei prossimi `days` giorni, raggruppati per data."""
    if not events:
        return []
    now = datetime.now(ROME)
    end = now + timedelta(days=days)
    out = []
    for e in events:
        try:
            ts = datetime.fromisoformat(e["ts"])
        except Exception:
            continue
        if now <= ts <= end and e.get("impact") in ("HIGH", "MEDIUM"):
            out.append(e)
    out.sort(key=lambda x: x["ts"])
    return out


def barometer(d):
    """Composito 0-100 da componenti dichiarate. Euristico, non un fatto.
    Componenti: volatilita' (VIX), sentiment crypto (Fear&Greed), notizie,
    tecnica (RSI). Media dei pezzi disponibili; se manca tutto, None."""
    parts = []
    detail = {}

    vix = _q(d, "indices", "VIX")
    if vix and vix.get("price"):
        v = vix["price"]
        s = max(0, min(100, (40 - v) / (40 - 10) * 100))
        parts.append(s)
        detail["volatility"] = {
            "raw": f"VIX {v:.1f}",
            "it": "bassa volatilita'" if s >= 60 else "volatilita' alta" if s <= 40 else "volatilita' media",
            "en": "low volatility" if s >= 60 else "high volatility" if s <= 40 else "average volatility",
        }

    sent = d.get("sentiment")
    if sent and sent[0] is not None:
        parts.append(float(sent[0]))
        detail["sentiment"] = {"raw": f"Fear&Greed {sent[0]} ({sent[1]})",
                               "it": "sentiment crypto", "en": "crypto sentiment"}

    scores = [n["sentiment"]["score"] for n in (d.get("news2") or [])
              if n.get("sentiment") and n["sentiment"].get("score") is not None]
    if scores:
        s = sum(scores) / len(scores)
        parts.append(s)
        detail["news"] = {"raw": f"news {s:.0f}/100 ({len(scores)})",
                          "it": "tono delle notizie", "en": "news tone"}

    tech = []
    for group, label in (("indices", "S&P 500"), ("metals", "GOLD")):
        q = _q(d, group, label)
        r = md.rsi(q.get("closes") or []) if q else None
        if r is not None:
            tech.append(r)
    btc_c = (d.get("series") or {}).get("BITCOIN")
    if btc_c:
        r = md.rsi(btc_c)
        if r is not None:
            tech.append(r)
    if tech:
        s = sum(tech) / len(tech)
        parts.append(s)
        detail["technical"] = {"raw": f"RSI medio {s:.0f}",
                               "it": "lettura tecnica", "en": "technical read"}

    if not parts:
        return None
    return {"score": sum(parts) / len(parts), "parts": detail}


def _band(score, lang):
    if score is None:
        return "DATA NOT AVAILABLE"
    if lang == "it":
        if score >= 65:
            return "risk-on, propensione al rischio"
        if score >= 45:
            return "neutrale"
        if score >= 35:
            return "cauto"
        return "risk-off, propensione alla difesa"
    if score >= 65:
        return "risk-on, appetite for risk"
    if score >= 45:
        return "neutral"
    if score >= 35:
        return "cautious"
    return "risk-off, defensive"


def _chg(ch):
    if ch is None:
        return "n/d"
    return f"{ch:+.2f}%"


def compose_weekly(lang, d):
    it = lang == "it"
    now = datetime.now(ROME)
    monday = now - timedelta(days=now.weekday())
    week_lbl = monday.strftime("%d/%m") + " – " + now.strftime("%d/%m/%Y")
    L = ["⚡ <b>TRADING NEWS AI</b>", "<i>REAL-TIME MARKET INTELLIGENCE</i>", "",
         (f"🗓️ <b>RIEPILOGO SETTIMANALE</b> · settimana {week_lbl}" if it
          else f"🗓️ <b>WEEKLY RECAP</b> · week {week_lbl}"), ""]
    L.append(("È il momento di fare il punto: come è andata questa settimana e cosa "
              "aspettarci dalla prossima. In parole semplici, solo quello che conta."
              if it else
              "Time to take stock: how this week went and what to watch next week. "
              "Plain words, only what matters."))
    L.append("")

    rows = week_recap(d)
    if rows:
        L.append("📉 <b>Come è andata questa settimana</b>" if it
                 else "📉 <b>How the week went</b>")
        for r in rows:
            p = r["price"]
            pstr = (f"{p:,.2f}" if p is not None and p >= 1 else
                    f"{p:.4f}" if p is not None else "n/d")
            L.append(f"{r['emoji']} <b>{r['label']}</b> {pstr} ({_chg(r['chg'])})")
        ranked = [r for r in rows if r["chg"] is not None]
        if ranked:
            best = max(ranked, key=lambda r: r["chg"])
            worst = min(ranked, key=lambda r: r["chg"])
            L.append("")
            L.append((f"🏆 Migliore: <b>{best['label']}</b> {_chg(best['chg'])} · "
                      f"Peggiore: <b>{worst['label']}</b> {_chg(worst['chg'])}") if it
                     else (f"🏆 Best: <b>{best['label']}</b> {_chg(best['chg'])} · "
                           f"Worst: <b>{worst['label']}</b> {_chg(worst['chg'])}"))
        L.append("")

    bar = barometer(d)
    if bar:
        L.append("🧭 <b>TRADING NEWS AI BAROMETER</b>")
        L.append(f"{bar['score']:.0f}/100 · {_band(bar['score'], lang)}")
        L.append("<i>Composito euristico (volatilita', sentiment, notizie, tecnica). "
                 "Non un fatto, non una previsione.</i>" if it else
                 "<i>Heuristic composite (volatility, sentiment, news, technicals). "
                 "Not a fact, not a forecast.</i>")
        L.append("")

    # dove guardare, mercato per mercato (copertura ampia, cifre non consigli)
    mkw = market_week(d)
    if mkw:
        L.append("🧭 <b>Dove guardare, mercato per mercato</b>" if it
                 else "🧭 <b>Where to watch, market by market</b>")
        for blk in mkw:
            bits = [f"{r['label']} {_chg(r['chg'])}" for r in blk["rows"]
                    if r["chg"] is not None]
            if bits:
                L.append(f"• <b>{blk['it'] if it else blk['en']}</b>: " + " · ".join(bits))
        L.append("<i>Variazione a ~5 sedute. Lettura meccanica, non un consiglio.</i>" if it
                 else "<i>~5-session change. Mechanical read, not advice.</i>")
        L.append("")

    cbest, cworst = crypto_week(d)
    if cbest:
        L.append("🪙 <b>Cripto: chi si muove (7g)</b>" if it
                 else "🪙 <b>Crypto movers (7d)</b>")
        L.append("🟢 " + " · ".join(f"{r['sym']} {_chg(r['chg'])}" for r in cbest))
        if cworst:
            L.append("🔻 " + " · ".join(f"{r['sym']} {_chg(r['chg'])}" for r in cworst))
        L.append("")

    sw = stock_week(d)
    if sw:
        L.append("📈 <b>Azioni: chi si muove (5 sedute)</b>" if it
                 else "📈 <b>Stock movers (5 sessions)</b>")
        L.append("🟢 " + " · ".join(f"{r['sym']} {_chg(r['chg'])}" for r in sw[:4]))
        if len(sw) > 4:
            L.append("🔴 " + " · ".join(f"{r['sym']} {_chg(r['chg'])}"
                                          for r in sw[-4:][::-1]))
        L.append("")

    ahead = week_ahead(d.get("events"))
    L.append("📅 <b>Settimana entrante: catalizzatori</b>" if it
             else "📅 <b>Week ahead: catalysts</b>")
    if ahead:
        for e in ahead[:10]:
            emo = {"HIGH": "🔴", "MEDIUM": "🟠"}.get(e["impact"], "⚪")
            day = datetime.fromisoformat(e["ts"]).strftime("%a %d/%m")
            L.append(f"{emo} {day} {e['ts'][11:16]} {e['country']} "
                     f"{html.escape(e['title'])}")
    else:
        L.append("<i>calendario della settimana entrante non ancora pubblicato "
                 "dalla fonte; arriva lunedi'.</i>" if it else
                 "<i>next week's calendar not published by the source yet; "
                 "it lands Monday.</i>")
    L.append("")

    L.append("🔭 <b>Come potrebbe andare</b>" if it else "🔭 <b>How the week may play</b>")
    if bar:
        s = bar["score"]
        if it:
            tone = ("contesto orientato al rischio: i dati forti possono cambiare "
                    "tono in fretta." if s >= 65 else
                    "contesto neutro: i catalizzatori in calendario decidono la "
                    "direzione." if s >= 45 else
                    "contesto cauto: il mercato prezza piu' rischio che opportunita'.")
        else:
            tone = ("risk-on backdrop: strong data can flip the tone quickly." if s >= 65
                    else "neutral backdrop: the calendar catalysts set the direction."
                    if s >= 45 else
                    "cautious backdrop: the market is pricing more risk than reward.")
        L.append(f"• {tone}")
    above, below = [], []
    for blk in mkw:
        for r in blk["rows"]:
            tr = (r.get("tech") or {}).get("trend")
            if tr == "above":
                above.append(r["label"])
            elif tr == "below":
                below.append(r["label"])
    if above:
        L.append(("• Sopra il trend: " if it else "• Above trend: ")
                 + ", ".join(above[:9]) + ".")
    if below:
        L.append(("• Sotto il trend: " if it else "• Below trend: ")
                 + ", ".join(below[:9]) + ".")
    if ahead:
        top = [e for e in ahead if e["impact"] == "HIGH"][:3]
        for e in top:
            day = datetime.fromisoformat(e["ts"]).strftime("%a %d/%m")
            L.append(f"• {day} {e['country']} {html.escape(e['title'])}: "
                     + ("volatilita' attesa sull'evento." if it else "expect event volatility."))
    L.append("<i>Scenari meccanici dai dati, non previsioni di prezzo. I rischi restano tuoi.</i>"
             if it else
             "<i>Mechanical scenarios from data, not price forecasts. The risk is yours.</i>")
    L.append("")
    L.append("Buon weekend. Lunedì il calendario riparte e ricominciamo da qui." if it
             else "Have a good weekend. Monday the calendar resets and we start again.")
    L.append("")
    L.append(("<i>Informazioni a scopo informativo ed educativo. Non costituiscono "
              "consulenza finanziaria ne' raccomandazione di investimento.</i>" if it else
              "<i>For information and education only. Not financial advice and not an "
              "investment recommendation.</i>"))
    return "\n".join(L)
