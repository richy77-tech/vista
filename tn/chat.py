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
from . import indicators as ind
from .ai import ai_blocked, note_ai

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
    "• \"operazioni\" / \"che operazioni hai preso\" → cosa fa e quali ha preso, quali no\n"
    "• \"quanto ha guadagnato\" → stima onesta del guadagno (in R e in euro simulati)\n"
    "• \"chiudi tutto\" → chiude il paper (i soldi veri restano fermi)\n"
    "• \"aggiungi il gas\" / \"togli l'oro\" → cambia gli asset seguiti\n"
    "• \"come usi le notizie\" → la dottrina\n"
    "• \"agenti\" / \"chi decide\" → i tre ruoli (news, grafico, convalida) e l'ultimo giro\n"
    "• qualunque cosa di trading (ATR, leva, RSI, stop, funding, futures, CPI...) → "
    "te la spiego come un manuale\n"
    "Se scrivi altro, rispondo con quello che so, o lo dico che non lo so."
)


# Prompt del desk. Ricalca il metodo dei framework multi-agente di trading
# (TauricResearch/TradingAgents): piu' ruoli su cui il modello si sposta a turno,
# e un risk manager che puo' dire no. Il modello ragiona, i numeri restano quelli
# del contesto: se il contesto non li ha, li dichiara mancanti invece di inventarli.
DESK_SYS = (
    "Sei il desk di trading dell'agente di Richy. Ragioni a ruoli, in italiano, "
    "asciutto, senza cerimonie. REGOLE FERME:\n"
    "1. Usi SOLO i numeri del CONTESTO. Se un dato manca, scrivi 'non ce l'ho', "
    "non inventarlo mai.\n"
    "2. Non dai consigli di investimento e non prometti rendimenti. Descrivi, non "
    "ordini. Nessuna size in denaro vero: al massimo in % di rischio.\n"
    "3. Il risk manager ha l'ultimo veto: se il quadro e' confuso o il costo/beneficio "
    "non c'e', la conclusione e' 'niente operazione'.\n"
    "4. Distingui sempre FATTO (numero) da LETTURA (tua interpretazione).\n"
    "Formato della risposta, sezioni brevi (max 2 righe l'una):\n"
    "🎯 QUADRO — una riga su cosa fa il mercato adesso.\n"
    "📐 TECNICO — trend, RSI, ATR dai dati.\n"
    "📰 NEWS — solo cio' che sposta, con impatto; se non c'e', dillo.\n"
    "🌍 MACRO — calendario/contesto; se non c'e', dillo.\n"
    "🛡️ RISCHIO — cosa puo' andare storto, dove sta lo stop logico.\n"
    "✅ VERDETTO — operazione si'/no/aspetta, con motivo in una riga.\n"
    "❓ NON SO — i buchi del contesto.\n"
    "Dottrina operativa:\n" + DOCTRINE
)


def _tech(sym, lab):
    """Una riga tecnica su un asset: prezzo, RSI, trend (EMA), ATR%. Dati reali."""
    try:
        # 1y di barre: EMA200 ha bisogno di piu' di 3 mesi, altrimenti il trend
        # esce sempre 'n/d' (bug visto il 21/10).
        q = md.yahoo(sym, rng="1y")
    except Exception:
        return None
    closes = q.get("closes") or []
    if not closes:
        return None
    p = q.get("price")
    ps = (f"{p:,.0f}" if p is not None and p >= 1000
          else f"{p:,.2f}" if p is not None and p >= 10
          else f"{p:.4f}" if p is not None else "n/d")
    s = f"{lab} {ps}"
    r = md.rsi(closes)
    reg = ind.regime(closes)
    if r is not None:
        s += f", RSI {r:.0f}"
    s += f", trend {reg['state']}"
    try:
        a = ind.atr_pct(paper.ohlc(sym))
        if a is not None:
            s += f", ATR {a:.2f}%"
    except Exception:
        pass
    return s


def _desk_context(cfg):
    """Contesto reale per il desk: prezzi+indicatori, paper, news, calendario."""
    lab = _labels()
    out = ["PREZZI E STATO (barre giornaliere reali):"]
    for s in cfg.get("symbols", [])[:8]:
        t = _tech(s, lab.get(s, s))
        if t:
            out.append("• " + t)
    out.append("")
    out.append("REGISTRO PAPER (nessun denaro vero):")
    try:
        out.append(re.sub(r"<[^>]+>", "", paper.report()))
    except Exception:
        out.append("registro non disponibile")
    try:
        items, _err = ne.pipeline(per_source=5)
        items.sort(key=lambda x: {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}.get(x.get("impact"), 4))
        hot = [it for it in items if it.get("impact") in ("HIGH", "CRITICAL")][:5]
        out.append("")
        out.append("NEWS CHE SPOSTANO:")
        if hot:
            out.extend(f"• [{it['impact']}] {it['title']} ({it.get('source','')})" for it in hot)
        else:
            out.append("• nessuna ad alto impatto")
    except Exception:
        out.append("")
        out.append("NEWS: fonte non raggiungibile")
    try:
        events, _e = cal.fetch_week()
        from datetime import datetime
        today = datetime.now(cal.ROME).date().isoformat()
        tod = [e for e in events if e["ts"][:10] == today and e.get("impact") in ("HIGH", "MEDIUM")]
        out.append("")
        out.append("CALENDARIO OGGI:")
        if tod:
            out.extend(f"• {e['ts'][11:16]} {e['country']} {e['title']} ({e['impact']})" for e in tod[:6])
        else:
            out.append("• nulla di rilevante")
    except Exception:
        pass
    return "\n".join(out)


DESK_KEYS = ("che faccio", "che si fa", "conviene", "compro", "comprare",
             "vendo", "vendere", "entro", "entrare", "analisi", "analizza",
             "secondo te", "che ne pensi", "dovrei", "consiglio", "opportunita",
             "opportunità", "setup", "long o short", "che posizione",
             "come la vedi", "mi conviene", "operazione su", "che idea hai")



def _read_symbol(sym, lab):
    """Lettura secca di un asset: prezzo, variazione, RSI, trend, ATR%. Numeri reali."""
    try:
        q = md.yahoo(sym, rng="1y")
    except Exception:
        return None
    closes = q.get("closes") or []
    if not closes:
        return None
    p = q.get("price")
    reg = ind.regime(closes)
    r = md.rsi(closes)
    a = None
    try:
        a = ind.atr_pct(paper.ohlc(sym))
    except Exception:
        pass
    ch = md.change_pct(q)
    return {"sym": sym, "lab": lab, "price": p, "change": ch, "rsi": r,
            "trend": reg.get("state"), "atr_pct": a}


def _verdict(d):
    """Lettura a regole di un asset (nessun modello, nessuna promessa).
    Deterministica e dichiarata come lettura, non come previsione."""
    r, tr, p = d.get("rsi"), d.get("trend"), d.get("price")
    if p is None:
        return "dato non disponibile"
    if tr == "piatto":
        return "laterale: niente direzione, non e' un punto d'ingresso"
    if r is not None and r >= 70:
        return "caro (RSI alto): entrare qui e' inseguire, non seguire"
    if r is not None and r <= 30:
        return "scarico (RSI basso): puo' rimbalzare, ma il trend decide"
    if tr == "su":
        return "quadro in salita, niente estremi: si entra solo su rottura, con stop deciso prima"
    if tr == "giu":
        return "quadro in discesa, niente estremi: si entra solo su rottura, con stop deciso prima"
    return "nulla di netto: aspettare"


def _desk_rules(cfg, question):
    """Desk SENZA modello. Stessa struttura a sezioni del desk AI, ma composta
    dai numeri reali con regole fisse. Serve a rispondere sempre: se la chiave AI
    manca o e' a secco, l'agente non tace e non finge, da' il quadro a regole."""
    lab = _labels()
    syms = _find_symbols(question) or list(cfg.get("symbols", []))[:3]
    rows = [d for d in (_read_symbol(s, lab.get(s, s)) for s in syms) if d]
    L = ["<b>DESK</b> (a regole, senza motore AI: numeri veri, nessun giudizio inventato)", ""]
    if not rows:
        L.append("🎯 QUADRO — dati non raggiungibili adesso. Riprovo al prossimo giro.")
        L.append("❓ NON SO — prezzi/indicatori non disponibili.")
        return "\n".join(L)
    for d in rows:
        ps = (f"{d['price']:,.0f}" if d["price"] is not None and d["price"] >= 1000
              else f"{d['price']:,.2f}" if d["price"] is not None and d["price"] >= 10
              else f"{d['price']:.4f}" if d["price"] is not None else "n/d")
        ch = f"{d['change']:+.2f}%" if d["change"] is not None else "n/d"
        rsi = f"{d['rsi']:.0f}" if d["rsi"] is not None else "n/d"
        atr = f"{d['atr_pct']:.2f}%" if d["atr_pct"] is not None else "n/d"
        L.append(f"📐 <b>{d['lab']}</b> {ps} {ch} · RSI {rsi} · trend {d['trend']} · ATR {atr}")
        L.append(f"🛡️ rischio — {_verdict(d)}")
    L.append("")
    L.append("✅ VERDETTO — nessuna operazione e' decisa da questa lettura. "
             "Il registro paper aspetta un fuori campione che tenga. "
             "Scrivimi 'operazioni' per cosa ha preso, 'che regole hai' per la dottrina.")
    L.append("❓ NON SO — macro e news sono nel brief ('brief'); qui ho solo prezzo e indicatori.")
    return "\n".join(L)


def _desk(cfg, question):
    """Desk con modello se c'e' (chiave o Pollinations), altrimenti a regole.
    Mai silenzio."""
    if ai_blocked() and not os.environ.get("AI_API_KEY"):
        return _desk_rules(cfg, question)
    ctx = _desk_context(cfg)
    known = kb.lookup(question, limit=3)
    if known:
        ctx += "\n\nVoci di manuale pertinenti:\n" + re.sub(r"<[^>]+>", "", known)
    ans = _llm(question, ctx)
    if ans:
        return ans
    return _desk_rules(cfg, question)


def _llm(question, ctx):
    """Desk AI: endpoint con chiave, poi Pollinations senza chiave.
    Se nessuno risponde si torna alle regole, senza fingere."""
    from . import llm
    if ai_blocked() and not os.environ.get("AI_API_KEY"):
        return None
    ans = llm.chat(DESK_SYS, f"CONTESTO:\n{ctx}\n\nDOMANDA: {question}", timeout=45)
    if ans:
        note_ai(True)
        return ans.strip()
    note_ai(False)
    return None


def _roles():
    """Spiega i tre ruoli e mostra cosa ha detto l'ultimo giro (se c'e')."""
    L = ["<b>Tre agenti nel bot</b> (ruoli separati, ognuno con il suo compito):",
         "1. <b>Verificatore news</b> — sceglie la notizia che puo' spostare, e il verso.",
         "2. <b>Lettore grafico</b> — guarda trend, RSI, ATR, movimento: conferma o boccia.",
         "3. <b>Convalidatore</b> — ultimo veto: apre o salta, e chiude se la tesi cade.",
         "",
         "I numeri (entry, stop, target) li calcola il codice da prezzi e ATR reali: "
         "i ruoli decidono si'/no e spiegano, non inventano livelli.",
         "Ogni ruolo ha anche una versione a regole: se il modello tace, decide quella."]
    try:
        import json as _json
        import os as _os
        p = _os.path.join(paper.ROOT, "private_state.json")
        with open(p, encoding="utf-8") as f:
            st = _json.load(f)
        r = st.get("last_roles")
        if r:
            L += ["", f"<b>Ultimo giro</b> ({r.get('utc') or '?'}):",
                  f"• news: {html.escape(str(r.get('news_sym') or '-'))} — {html.escape(str(r.get('news') or ''))}",
                  f"• grafico: {html.escape(str(r.get('chart') or ''))}",
                  f"• convalidatore: {html.escape(str(r.get('action') or ''))} — {html.escape(str(r.get('verdict') or ''))}"]
        else:
            L += ["", "Ancora nessun giro registrato: arriva col prossimo ciclo."]
    except Exception:
        L += ["", "Stato non leggibile adesso."]
    return "\n".join(L)


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
    if any(k in t for k in ("quanto ha guadagnato", "quanto guadagn", "guadagn", "pnl",
                            "profitto", "soldi", "p&l", "rendimento", "bilancio")):
        return paper.earnings()
    if (any(k in t for k in ("come va", "posizion", "operazioni", "paper", "registro", "aperte"))
            or re.search(r"\bprese\b", t) or "che operazioni" in t or "non prese" in t):
        return paper.screen(symbols=cfg.get("symbols"))
    if any(k in t for k in ("metriche", "metrica", "comunanza", "volume medio", "supporti",
                            "resistenz", "beta", "volatilit", "macd", "cci",
                            "gestione del denaro", "money management", "backtest",
                            "backward test", "open interest", "correlazione")):
        from . import metrics
        return metrics.handle(text, cfg, lambda s: _find_symbols(s.lower()))
    if any(k in t for k in ("agenti", "tre agenti", "chi decide", "come decidete",
                            "ruoli", "chi apre", "chi convalida")):
        return _roles()
    if any(k in t for k in ("calendario", "calendar", "eventi di oggi", "dati di oggi")):
        return _calendar()
    if any(k in t for k in ("notizi", "news", "cosa e' successo", "cosa è successo", "ultime", "breaking")):
        return _news()
    if any(k in t for k in ("brief", "riepilogo", "situazione", "scenario", "come sta il mercato",
                            "aggiorna", "riassunto")):
        from .private import build_brief
        return build_brief()

    # 1b) domanda aperta -> desk (anche se nomina un asset: "che faccio sull'oro"
    #     non e' una richiesta di prezzo, e' una richiesta di lettura).
    if any(k in t for k in DESK_KEYS):
        return _desk(cfg, text)

    # 2) un asset nominato SENZA domanda aperta -> prezzo
    syms = _find_symbols(t)
    if syms:
        return "\n".join(_price_line(s, lab.get(s, s)) for s in syms[:4])

    # 3) enciclopedia: definizioni e meccanica del trading, senza chiave
    entry = kb.lookup(text)
    if entry:
        return entry

    # 4) tutto il resto -> desk (modello se c'e', altrimenti a regole)
    return _desk(cfg, text)
