"""Testo libero nel bot privato: un agente dentro il bot, non un bot separato.

Due livelli, tenuti separati e dichiarati come tali:
  REGOLE -> intenti riconosciuti a parole (brief, prezzo di un asset, calendario,
            notizie, posizioni paper, chiudi tutto, stop/riprendi, aggiungi/togli
            asset, dottrina). Funziona sempre, senza chiavi, e non inventa numeri:
            quello che legge, lo dice; quello che non sa, lo dice.
  AI     -> se c'e' AI_API_KEY (endpoint OpenAI-compatibile) risponde in lingua
            naturale sul contesto reale (prezzi, calendario, paper, notizie).
            Senza chiave non finge di essere intelligente: spiega cosa sa fare.

Dottrina operativa: come si usano le news. Scritta qui, non nascosta.
"""
import html
import json
import os
import re

from . import marketdata as md
from . import calendar as cal
from . import paper
from . import newsengine as ne
from . import knowledge as kb

DOCTRINE = (
    "Come uso le news:\n"
    "1. Una notizia conta solo se sposta: impatto HIGH o CRITICAL dalla fonte, e il "
    "prezzo conferma nella stessa direzione (>=0.35%) entro la finestra.\n"
    "2. La notizia resta viva 6 ore. Passata la finestra, non riapre.\n"
    "3. Una posizione per asset. Mai piramidare, mai inseguire.\n"
    "4. Stop 1.5xATR, target 3xATR, time stop a 5 barre. Decisi prima di entrare.\n"
    "5. La notizia apre, il mercato chiude. Se il prezzo non conferma, non si entra.\n"
    "6. Al canale va l'informazione, mai il consiglio. Nessun segnale a persone.\n"
    "7. Paper first. Chiavi vere solo dopo un fuori campione positivo."
)

ALIASES = {
    "BTC-USD": ["bitcoin", "btc"],
    "ETH-USD": ["ethereum", "eth"],
    "GC=F": ["oro", "gold", "xau"],
    "SI=F": ["argento", "silver", "xag"],
    "CL=F": ["petrolio", "oil", "wti", "brent", "greggio"],
    "NG=F": ["gas", "gas naturale", "natural gas"],
    "EURUSD=X": ["euro", "eurusd", "eur/usd"],
    "GBPUSD=X": ["sterlina", "gbpusd", "gbp/usd"],
    "USDJPY=X": ["yen", "usdjpy", "usd/jpy"],
    "DX-Y.NYB": ["dollaro", "dxy", "dollar index"],
    "^GSPC": ["s&p", "s&p 500", "sp500"],
    "^IXIC": ["nasdaq"],
    "^DJI": ["dow"],
    "^VIX": ["vix", "volatilita"],
}


def _labels():
    out = {}
    for g in md.GROUPS.values():
        for sym, lab, _ in g:
            out[sym] = lab
    out["BTC-USD"] = "BITCOIN"
    out["ETH-USD"] = "ETHEREUM"
    return out


def _find_symbols(text):
    t = " " + re.sub(r"[^a-z0-9&/\- ]+", " ", text.lower()) + " "
    hits = []
    for sym, words in ALIASES.items():
        if any((" " + w + " ") in t or (" " + w) in t for w in words):
            hits.append(sym)
    return hits


def _price_line(sym, lab):
    try:
        q = md.yahoo(sym)
    except Exception as e:
        return f"{lab}: fonte giu ({type(e).__name__})"
    ch = md.change_pct(q)
    r = md.rsi(q.get("closes") or [])
    p = q.get("price")
    if p is None:
        return f"{lab}: prezzo non disponibile"
    ps = f"{p:,.0f}" if p >= 1000 else (f"{p:,.2f}" if p >= 10 else f"{p:.4f}")
    arrow = "▲" if (ch or 0) > 0 else ("▼" if (ch or 0) < 0 else "=")
    s = f"<b>{lab}</b> {ps} {q.get('currency') or ''}".strip()
    if ch is not None:
        s += f"  {arrow} {ch:+.2f}%"
    if r is not None:
        s += f"  RSI {r:.0f}"
    return s


def _close_all(cfg):
    st = paper.load()
    if not st["open"]:
        return "Nessuna posizione paper aperta."
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="minutes")
    ev = []
    for sym in list(st["open"]):
        pos = st["open"][sym]
        try:
            last = paper.ohlc(sym)[-1]["c"]
        except Exception:
            ev.append(f"{sym}: fonte giu, resta aperta")
            continue
        pos.update({"exit": last, "exit_ts": now, "reason": "manuale",
                    "r": round(paper._r(pos["entry"], last, pos["stop"], pos["side"]), 3)})
        st["closed"].append(pos)
        del st["open"][sym]
        ev.append(f"{sym}: chiusa {pos['side']} @ {last:.4f} -> {pos['r']:+.2f}R")
    paper.save(st)
    return "Chiudo tutto (paper, soldi veri fermi).\n" + "\n".join(ev) + "\n" + paper.report(st)


def _add_asset(cfg, text):
    syms = _find_symbols(text)
    if not syms:
        return "Quale asset? Dimmi il nome (oro, btc, gas, nasdaq...)."
    added = [s for s in syms if s not in cfg["symbols"]]
    if added:
        cfg["symbols"].extend(added)
        return "Aggiunti: " + ", ".join(added)
    return "Gia' seguiti."


def _remove_asset(cfg, text):
    syms = _find_symbols(text)
    keep = [s for s in cfg["symbols"] if s not in syms]
    if len(keep) == len(cfg["symbols"]):
        return "Non erano in lista."
    cfg["symbols"] = keep
    return "Rimossi. Restano: " + ", ".join(keep)


def _news(n=5):
    items, err = ne.pipeline(per_source=6)
    if not items:
        return "Notizie non raggiungibili" + (f" ({err})" if err else "") + "."
    items.sort(key=lambda x: {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}.get(x.get("impact"), 4))
    out = ["<b>Notizie</b>"]
    for it in items[:n]:
        out.append(f"• <a href=\"{html.escape(it['url'])}\">{html.escape(it['title'])}</a> · {it['impact']}")
    return "\n".join(out)


def _calendar():
    events, err = cal.fetch_week()
    if err and not events:
        return f"Calendario non raggiungibile ({err})."
    from datetime import datetime
    today = datetime.now(cal.ROME).date().isoformat()
    todays = [e for e in events if e["ts"][:10] == today and e.get("impact") in ("HIGH", "MEDIUM")]
    if not todays:
        return "Oggi nessun evento macro rilevante."
    return "<b>Oggi sul calendario</b>\n" + "\n".join(
        f"• {e['ts'][11:16]} {e['country']} · {e['title']} ({e['impact'].lower()})" for e in todays[:6])


HELP_TEXT = (
    "<b>Posso fare questo, scrivendomi in italiano normale:</b>\n"
    "• \"come sta il mercato\" / \"brief\" → brief completo\n"
    "• \"quanto sta il bitcoin\" / \"l'oro?\" → prezzo, variazione, RSI\n"
    "• \"cosa e' successo\" / \"notizie\" → le notizie del momento\n"
    "• \"calendario di oggi\" → eventi macro\n"
    "• \"come vanno le operazioni\" → registro paper\n"
    "• \"chiudi tutto\" → chiude il paper (i soldi veri restano fermi)\n"
    "• \"aggiungi il gas\" / \"togli l'oro\" → cambia gli asset seguiti\n"
    "• \"come usi le notizie\" → la dottrina\n"
    "• qualunque cosa di trading (ATR, leva, RSI, stop, funding, futures, CPI...) → "
    "te la spiego come un manuale\n"
    "Se scrivi altro, rispondo con quello che so, o lo dico che non lo so."
)


def _llm(question, ctx):
    """Hook AI opzionale. Non testato senza chiave: se manca, si torna alle regole."""
    key = os.environ.get("AI_API_KEY")
    if not key:
        return None
    base = os.environ.get("AI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("AI_MODEL", "gpt-4o-mini")
    sys_prompt = (
        "Sei l'agente dentro il bot privato di Richy. Rispondi in italiano, breve, "
        "con i numeri del contesto, mai inventandone. Non dai consigli di "
        "investimento e non prometti rendimenti. Dottrina operativa:\n" + DOCTRINE
    )
    body = json.dumps({
        "model": model, "temperature": 0,
        "messages": [{"role": "system", "content": sys_prompt},
                     {"role": "user", "content": f"CONTESTO:\n{ctx}\n\nDOMANDA: {question}"}],
    }).encode()
    try:
        from .http import fetch
        raw = fetch(base + "/chat/completions", headers={
            "Content-Type": "application/json", "Authorization": "Bearer " + key},
            timeout=40, tries=2)
        return json.loads(raw)["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def reply(text, cfg):
    """Risposta a testo libero. cfg e' il dict di configurazione (modificabile)."""
    t = text.lower().strip()
    lab = _labels()

    if not t:
        return HELP_TEXT

    # 1) intenti netti, prima di tutto
    if any(k in t for k in ("chiudi tutto", "chiudi le operazioni", "vai flat", "close all")):
        return _close_all(cfg)
    if t.startswith(("ciao", "hey", "buongiorno", "buonasera", "salve", "ehi")):
        return "Ciao. " + HELP_TEXT
    if any(k in t for k in ("come usi le notizie", "come leggi le news", "dottrina", "che regole hai")):
        return DOCTRINE
    if t.startswith(("aggiungi", "segui ", "metti ")) or " aggiungi " in t:
        return _add_asset(cfg, t)
    if t.startswith(("togli", "rimuovi", "leva")):
        return _remove_asset(cfg, t)
    if any(k in t for k in ("fermati", "pausa", "sospendi")) or t.strip() in ("stop", "stop bot"):
        return "PAUSA: scrivimi 'riprendi' quando vuoi ripartire."
    if any(k in t for k in ("cosa sai fare", "cosa fai", "aiuto", "help", "chi sei", "come funzioni")):
        return HELP_TEXT
    if any(k in t for k in ("come va", "posizion", "operazioni", "paper", "registro", "aperte")):
        return paper.report()
    if any(k in t for k in ("calendario", "calendar", "eventi di oggi", "dati di oggi")):
        return _calendar()
    if any(k in t for k in ("notizi", "news", "cosa e' successo", "cosa è successo", "ultime", "breaking")):
        return _news()
    if any(k in t for k in ("brief", "riepilogo", "situazione", "scenario", "come sta il mercato",
                            "aggiorna", "riassunto")):
        from .private import build_brief
        return build_brief()

    # 2) un asset nominato -> prezzo
    syms = _find_symbols(t)
    if syms:
        return "\n".join(_price_line(s, lab.get(s, s)) for s in syms[:4])

    # 3) enciclopedia: definizioni e meccanica del trading, senza chiave
    entry = kb.lookup(text)
    if entry:
        return entry

    # 4) AI (solo con chiave), con contesto reale
    ctx = "Prezzi:\n" + "\n".join(_price_line(s, lab.get(s, s)) for s in cfg["symbols"][:6])
    ctx += "\n" + paper.report()
    if any(k in t for k in ("notizi", "news", "perche", "perché", "mercato", "cosa")):
        ctx += "\n" + _news(4)
    known = kb.lookup(text, limit=3)
    if known:
        ctx += "\n\nVoci di manuale pertinenti:\n" + re.sub(r"<[^>]+>", "", known)
    ans = _llm(text, ctx)
    if ans:
        return ans

    # 5) non lo so: dico cosa so fare
    return "Questa non la capisco. " + HELP_TEXT
