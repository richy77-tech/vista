"""Tre agenti dentro il bot privato, come chiesto da Richy il 21/10.

  1. VERIFICATORE NEWS  -> dalle notizie forti tira fuori una candidata (asset, verso)
  2. LETTORE GRAFICO    -> guarda il grafico (trend, RSI, ATR, movimento): conferma o boccia
  3. CONVALIDATORE      -> ultimo veto: apre o salta, e sorveglia le aperte per chiuderle

Perche' a ruoli separati e non un unico prompt: ogni ruolo ha un compito stretto,
un output suo, e non puo' nascondere il proprio errore dietro gli altri. Il
convalidatore risponde solo del si'/no finale; il grafico solo della lettura; le
news solo della selezione.

Regola dura, uguale per tutti e tre: i numeri (entry, stop, target) li calcola
solo questo modulo da prezzi/ATR reali. Il modello decide si'/no e spiega. Se un
dato manca, si dichiara mancante. Se il modello non risponde, ogni ruolo ha la
sua versione a regole, cosi' il desk non tace mai e non inventa nulla.
"""
import json
import os
import re

from . import marketdata as md
from . import paper
from . import indicators as ind
from . import newstrigger as nt
from . import exec as ex
from . import llm
from . import briefs
from . import risk
from . import strategist

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAIN_LOG = os.path.join(ROOT, "desk_log.jsonl")

MAX_OPEN = 3          # quante operazioni paper aperte insieme al massimo
CONF_MIN = 0.55       # sotto questa confidenza dichiarata, il convalidatore salta

NEWS_SYS = (
    "Sei il VERIFICATORE NEWS di un desk di trading. Ricevi un elenco di notizie "
    "e gli asset seguiti. Scegli AL MASSIMO una notizia che possa spostare un "
    "mercato che seguiamo, e indica asset e verso. Una notizia conta solo se e' un "
    "fatto che cambia il quadro (decisione di banca centrale, dato macro a sorpresa, "
    "shock, sanzione, grande flusso). Titoli generici o vecchi: scartali.\n"
    "Rispondi SOLO con JSON: {\"sym\":\"<simbolo seguito o null>\","
    "\"side\":\"long|short|null\",\"confidence\":<0..1>,\"why\":\"<max 15 parole>\"}\n"
    "Se nessuna notizia merita, {\"sym\":null,\"side\":null,\"confidence\":0,\"why\":\"niente\"}."
)

CHART_SYS = (
    "Sei il LETTORE GRAFICO di un desk di trading. Ricevi per un asset i numeri "
    "reali (prezzo, variazione oggi, RSI, trend EMA, ATR%, massimo/minimo, "
    "posizione nella giornata) e una tesi (long o short). Il tuo compito: dire se "
    "il grafico conferma la tesi o la boccia, e descrivere il pattern in una riga.\n"
    "Usi SOLO i numeri ricevuti. Non inventi livelli. Se i dati sono insufficienti, "
    "confirm=false.\n"
    "Rispondi SOLO con JSON: {\"confirm\":true|false,\"setup\":\"<nome del pattern, max 6 parole>\","
    "\"why\":\"<max 15 parole>\",\"invalidate\":\"<cosa invaliderebbe la tesi, max 12 parole>\"}."
)

SUP_SYS = (
    "Sei il CONVALIDATORE, l'ultimo veto di un desk di trading. Ricevi la lettura "
    "delle news, la lettura del grafico e i numeri reali (entry, stop, target, R). "
    "Decidi una cosa sola: aprire l'operazione paper o saltarla.\n"
    "Apri solo se news e grafico concordano e il rapporto rischio/rendimento e' "
    "almeno 1:1.5. Nel dubbio, salta: il costo di un'operazione sbagliata e' piu' "
    "alto di quello di una mancata. Non prometti rendimenti e non inventi numeri.\n"
    "Rispondi SOLO con JSON: {\"action\":\"open|skip\",\"why\":\"<max 15 parole>\"}.\n"
    "IT: apri=solo con quadro chiaro e concorde."
)

ROLE_ORDER = ("verificatore news", "lettore grafico", "convalidatore")

# Ogni ruolo riceve il proprio dossier di mestiere (tn/briefs.py): cosa fa, come
# ragiona, dove sbaglia. Non sostituisce il prompt, lo istruisce.
NEWS_SYS = NEWS_SYS + "\n\n" + briefs.brief("news")
CHART_SYS = CHART_SYS + "\n\n" + briefs.brief("chart")
SUP_SYS = SUP_SYS + "\n\n" + briefs.brief("validator")


def _parse(raw):
    if not raw:
        return None
    s = raw.strip()
    if s.startswith("```"):
        s = s.strip("`")
        s = s[s.find("{"):s.rfind("}") + 1]
    else:
        i, j = s.find("{"), s.rfind("}")
        if i >= 0 and j > i:
            s = s[i:j + 1]
    try:
        d = json.loads(s)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def _ask(system, user, timeout=40):
    """Una chiamata a un ruolo. Ritorna il dict JSON o None."""
    try:
        raw = llm.chat(system, user, json_mode=True, timeout=timeout)
    except Exception:
        return None
    return _parse(raw)


def _ps(p):
    if p is None:
        return "n/d"
    if p >= 1000:
        return f"{p:,.0f}"
    if p >= 10:
        return f"{p:,.2f}"
    return f"{p:.4f}"


def _snapshot(sym, lab=None):
    """Numeri reali di un asset per il lettore grafico. Nessun numero inventato."""
    try:
        q = md.yahoo(sym, rng="1y")
    except Exception:
        return None
    closes = q.get("closes") or []
    if not closes:
        return None
    try:
        rows = paper.ohlc(sym)
    except Exception:
        rows = []
    reg = ind.regime(closes)
    rsi = md.rsi(closes)
    atr = ind.atr_pct(rows) if len(rows) > 15 else None
    n = len(rows)
    hi = max(r["h"] for r in rows[-20:]) if n >= 20 else (rows[-1]["h"] if rows else None)
    lo = min(r["l"] for r in rows[-20:]) if n >= 20 else (rows[-1]["l"] if rows else None)
    # Volumi reali: rapporto tra l'ultimo e la media delle ultime barre. Se il dato
    # non c'e' (alcuni simboli non lo danno), resta None e NON si inventa.
    vols = [r.get("v") for r in rows[-21:] if r.get("v") is not None]
    avgv = (sum(vols[:-1]) / len(vols[:-1])) if len(vols) > 1 else None
    lastv = rows[-1].get("v") if rows else None
    vol_ratio = (lastv / avgv) if (avgv and lastv) else None
    prev_h = rows[-2]["h"] if n >= 2 else None
    prev_l = rows[-2]["l"] if n >= 2 else None
    return {"sym": sym, "lab": lab or sym, "price": q.get("price"),
            "change": md.change_pct(q), "rsi": rsi, "trend": reg.get("state"),
            "atr_pct": atr, "hi20": hi, "lo20": lo, "closes": closes, "rows": rows,
            "vol_ratio": vol_ratio, "prev_h": prev_h, "prev_l": prev_l}


# ---------------------------------------------------------------- ruolo 1: news

def news_agent(news, symbols, lab=None):
    """Sceglie la notizia candidata. Ritorna la view: sym, side, confidence, why, news_id, title."""
    strong = [n for n in (news or [])
              if n.get("impact") in ("HIGH", "CRITICAL")
              and (n.get("sentiment") or {}).get("label") in ("bullish", "bearish")]
    # candidate a regole (riuso la mappa di newstrigger): e' il piano B, e serve
    # anche a dare al modello solo cio' che ha gia' un aggancio a un nostro asset.
    rule_cands = nt.candidates(news, symbols)
    if not strong:
        return {"sym": None, "side": None, "confidence": 0.0,
                "why": "nessuna notizia forte con verso", "rule": True}

    # il modello sceglie fra le candidate ancorate a un asset che seguiamo;
    # se non ce ne sono, non c'e' niente da verificare.
    if not rule_cands:
        # registro anche cosa ho lasciato per strada: senza l'etichetta e il
        # titolo, "asset non seguiti" resta una riga che non insegna niente.
        seen = []
        for n in strong:
            for a in (n.get("assets") or [])[:2]:
                seen.append("%s (%s)" % (a, (n.get("title") or "")[:70]))
                break
        return {"sym": None, "side": None, "confidence": 0.0,
                "why": "notizie forti ma su asset non seguiti: " + " | ".join(seen[:3]),
                "left": seen[:5], "rule": True}

    by_sym = {}
    for sym, side, title, nid in rule_cands:
        by_sym.setdefault(sym, []).append((side, title, nid))
    lines = []
    for sym, items in by_sym.items():
        for side, title, nid in items[:2]:
            lines.append(f"- {sym} {side}: {title[:140]}")
    user = ("ASSET SEGUITI: " + ", ".join(symbols) +
            "\nNOTIZIE CANDIDATE (gia' agganciate a un asset seguito):\n" + "\n".join(lines))
    d = _ask(NEWS_SYS, user)
    if isinstance(d, dict) and d.get("sym") in by_sym:
        side = d.get("side")
        if side in ("long", "short"):
            # trova titolo/id corrispondenti
            title = nid = None
            for s2, t2, i2 in by_sym.get(d["sym"], []):
                if s2 == side:
                    title, nid = t2, i2
                    break
            if title is None:
                title, nid = by_sym[d["sym"]][0][1], by_sym[d["sym"]][0][2]
            return {"sym": d["sym"], "side": side,
                    "confidence": _conf(d.get("confidence")),
                    "why": str(d.get("why") or "")[:120], "title": title, "news_id": nid,
                    "rule": False}
    # piano B: la prima candidata a regole
    sym, side, title, nid = rule_cands[0]
    return {"sym": sym, "side": side, "confidence": 0.5,
            "why": "regola: notizia forte agganciata all'asset", "title": title,
            "news_id": nid, "rule": True}


def _conf(v):
    try:
        f = float(v)
        return max(0.0, min(1.0, f))
    except Exception:
        return 0.5


# -------------------------------------------------------- ruolo 2: lettore grafico

def chart_agent(sym, side, lab=None):
    """Legge il grafico e conferma/boccia la tesi. Ritorna la view con i numeri reali."""
    s = _snapshot(sym, lab)
    if not s or s.get("price") is None or not s.get("rows"):
        return {"sym": sym, "confirm": False, "why": "dati insufficienti", "rule": True, "snap": None}
    entry = s["price"]
    a = nt.paper.atr(s["rows"]) if s["rows"] else None
    if not a:
        return {"sym": sym, "confirm": False, "why": "ATR non disponibile", "rule": True, "snap": s}
    if side == "long":
        stop = entry - paper.STOP_ATR * a
        tgt = entry + paper.TARGET_ATR * a
    else:
        stop = entry + paper.STOP_ATR * a
        tgt = entry - paper.TARGET_ATR * a

    # regole: la tesi tiene solo se il trend e' dalla parte giusta e il movimento c'e'
    ch = s["change"]
    rule_ok = (s["trend"] == ("su" if side == "long" else "giu")
               and ((ch or 0) >= nt.SOGLIA_PCT if side == "long" else (ch or 0) <= -nt.SOGLIA_PCT))
    user = (f"ASSET {sym} ({s['lab']})\n"
            f"prezzo {_ps(entry)} · oggi {(ch if ch is not None else 0):+.2f}% · "
            f"RSI {s['rsi']:.0f} · trend {s['trend']} · ATR {s['atr_pct']:.2f}% · "
            f"max20 {_ps(s['hi20'])} · min20 {_ps(s['lo20'])} · posizione nel range 20g: "
            f"{_range_pos(entry, s['lo20'], s['hi20'])}\n"
            f"livelli: max giorno prima {_ps(s.get('prev_h'))} · min giorno prima "
            f"{_ps(s.get('prev_l'))} · volumi ultima barra vs media "
            f"{('n/d' if s.get('vol_ratio') is None else format(s['vol_ratio'], '.2f') + 'x')}\n"
            f"TESI: {side.upper()} — {'la notizia spinge su' if side == 'long' else 'la notizia spinge giu'}")
    d = _ask(CHART_SYS, user)
    if isinstance(d, dict) and isinstance(d.get("confirm"), bool):
        return {"sym": sym, "side": side, "confirm": d["confirm"],
                "setup": str(d.get("setup") or "")[:60],
                "why": str(d.get("why") or "")[:120],
                "invalidate": str(d.get("invalidate") or "")[:80],
                "entry": entry, "stop": stop, "target": tgt, "atr": a, "rule": False, "snap": s}
    # piano B
    return {"sym": sym, "side": side, "confirm": bool(rule_ok),
            "setup": f"trend {s['trend']}", "why": "regola: trend e movimento dalla stessa parte"
            if rule_ok else "regola: trend o movimento non confermano",
            "invalidate": "chiusura oltre lo stop", "entry": entry, "stop": stop,
            "target": tgt, "atr": a, "rule": True, "snap": s}


def _range_pos(p, lo, hi):
    if lo is None or hi is None or hi <= lo:
        return "n/d"
    return f"{(p - lo) / (hi - lo) * 100:.0f}%"


# ---------------------------------------------------------- ruolo 3: convalidatore

def supervisor(news_view, chart_view):
    """Ultimo veto. Decide open/skip. I numeri restano quelli calcolati altrove."""
    if not news_view.get("sym") or not chart_view.get("confirm"):
        who = "news" if not news_view.get("sym") else "grafico"
        return {"action": "skip", "why": f"{who}: nessuna tesi confermata", "rule": True}
    r = paper._r(chart_view["entry"], chart_view["target"], chart_view["stop"], chart_view["side"])
    user = (f"NEWS: {news_view.get('title','')[:140]} — verso {news_view.get('side')}, "
            f"confidenza {news_view.get('confidence')}\n"
            f"GRAFICO: conferma={chart_view.get('confirm')}, setup={chart_view.get('setup')}, "
            f"rischio={chart_view.get('why')}\n"
            f"NUMERI: entry {_ps(chart_view['entry'])}, stop {_ps(chart_view['stop'])}, "
            f"target {_ps(chart_view['target'])}, R/R {r:.2f}")
    d = _ask(SUP_SYS, user)
    if isinstance(d, dict) and d.get("action") in ("open", "skip"):
        return {"action": d["action"], "why": str(d.get("why") or "")[:120], "rule": False}
    conf = news_view.get("confidence", 0) or 0
    ok = conf >= CONF_MIN and r >= 1.5
    return {"action": "open" if ok else "skip",
            "why": ("regola: tesi concorde, R/R ok" if ok
                    else f"regola: confidenza {conf:.2f} o R/R {r:.2f} sotto soglia"),
            "rule": True}


# ------------------------------------------------------------------- il giro

def _open_count(st):
    return len(st.get("open") or {})


def _run(symbols, news, lab=None, dry=False, max_open=MAX_OPEN):
    """Un giro completo dei tre ruoli. Apre al massimo una posizione paper.
    Ritorna (stato, eventi, traccia) — la traccia e' cosa ha detto ogni ruolo."""
    st = paper.load()
    # Anche a tetto raggiunto i tre ruoli ragionano e la decisione si registra:
    # e' materiale di addestramento, non esposizione. Si salta solo l'apertura.
    can_open = _open_count(st) < max_open

    nv = news_agent(news, symbols, lab)
    trace = {"news": nv}
    if not nv.get("sym"):
        return st, [], trace

    cv = chart_agent(nv["sym"], nv["side"], lab)
    trace["chart"] = {k: cv.get(k) for k in ("sym", "confirm", "setup", "why", "rule")}
    if not cv.get("confirm"):
        return st, [], trace

    # Muro, non un consiglio: se il trend e' girato contro il lato, non si apre.
    # Da qui venivano 4051 chiusure su "tesi invalidata", la maggior parte sulla
    # stessa candela dell'apertura: si entrava contro il trend e il sorvegliante
    # chiudeva al primo sguardo. Ora non nasce proprio.
    _snap = cv.get("snap") or {}
    _tr = _snap.get("trend")
    _want = "su" if nv["side"] == "long" else "giu"
    if _tr and _tr != "piatto" and _tr != _want:
        trace["skip"] = f"trend {_tr} contro {nv['side']}: non si apre"
        return st, [], trace

    # quarto ruolo prima del convalidatore: decide DOVE entrare. Non autorizza,
    # propone; il convalidatore puo' ancora dire no e il risk manager ha l'ultima.
    sp = strategist.plan(nv["sym"], nv["side"], cv.get("snap"))
    trace["strat"] = {k: sp.get(k) for k in ("ok", "kind", "tf", "rr", "why")}
    if not sp.get("ok"):
        trace["skip"] = sp.get("why")
        return st, [], trace
    cv["entry"], cv["stop"], cv["target"] = sp["entry"], sp["stop"], sp["target"]
    cv["plan"] = sp["kind"]

    sv = supervisor(nv, cv)
    trace["verdict"] = sv
    if sv.get("action") != "open":
        return st, [], trace

    sym = nv["sym"]
    if sym in st["open"]:
        return st, [], trace
    # quarto ruolo, e l'unico con veto: il risk manager non chiede permesso a
    # nessuno. Se blocca, la traccia resta scritta e l'operazione non nasce.
    rv = risk.vet(st, {"sym": sym, "side": nv["side"], "entry": cv["entry"],
                       "stop": cv["stop"], "target": cv["target"]},
                  closes={sym: (cv.get("snap") or {}).get("closes") or []})
    trace["risk"] = rv
    if rv["action"] == "block":
        trace["skip"] = f"risk: {rv['why']}"
        return st, [], trace
    if not can_open:
        trace["cap"] = f"{_open_count(st)} aperte (max {max_open}): valutata, non aperta"
        return st, [], trace
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="minutes")
    pos = {"symbol": sym, "side": nv["side"], "entry": cv["entry"], "stop": cv["stop"],
           "target": cv["target"], "atr": cv["atr"], "bars": 0, "entry_ts": now,
           "reason": f"3 ruoli: {cv.get('setup') or 'setup'}", "news_id": nv.get("news_id"),
           "headline": (nv.get("title") or "")[:120],
           "roles": {"news": nv.get("why"), "chart": cv.get("why"), "verdict": sv.get("why")}}
    try:
        pos["exec"] = ex.get().place(sym, nv["side"], qty=None, stop=cv["stop"],
                                     target=cv["target"],
                                     meta={"reason": "3ruoli", "news_id": nv.get("news_id")})
    except Exception as e:
        pos["exec"] = {"rejected": str(e)}
    st["open"][sym] = pos
    if not dry:
        paper.save(st)
    ev = [f"{sym}: aperta {nv['side']} @ {_ps(cv['entry'])} — {sv.get('why')}"
          f" [{cv.get('setup')}]"]
    return st, ev, trace


def run(symbols, news, lab=None, dry=False, max_open=MAX_OPEN):
    """Il giro, piu' la riga di addestramento. Ogni giro — anche uno che salta —
    lascia una traccia in desk_log.jsonl: cosa ha visto ogni ruolo e cosa ha
    deciso. Quel file e' il materiale con cui si correggono i prompt: senza
    registrare anche i 'no', non si impara nulla dai rifiuti."""
    st, ev, trace = _run(symbols, news, lab=lab, dry=dry, max_open=max_open)
    _record("open" if ev else "skip", trace, opened=bool(ev))
    return st, ev, trace


def _record(kind, trace, opened=False):
    try:
        from datetime import datetime, timezone
        nv = trace.get("news") or {}
        cv = trace.get("chart") or {}
        sv = trace.get("verdict") or {}
        rec = {"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
               "kind": kind, "opened": bool(opened),
               "news": {"sym": nv.get("sym"), "side": nv.get("side"),
                        "left": nv.get("left"),
                        "conf": nv.get("confidence"), "why": (nv.get("why") or "")[:160],
                        "rule": nv.get("rule")},
               "chart": {k: cv.get(k) for k in ("confirm", "setup", "why", "rule")},
               "verdict": {"action": sv.get("action"), "why": (sv.get("why") or "")[:160],
                           "rule": sv.get("rule")},
               "risk": {"action": (trace.get("risk") or {}).get("action"),
                        "why": ((trace.get("risk") or {}).get("why") or "")[:160],
                        "checks": (trace.get("risk") or {}).get("checks")}}
        if not trace.get("news") and trace.get("skip"):
            rec["note"] = str(trace["skip"])[:160]
        with open(TRAIN_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def review(symbols, dry=False):
    """Sorveglianza delle aperte: il convalidatore puo' chiudere prima dello stop
    se la tesi e' invalidata (trend invertito contro la posizione). Non tocca i
    numeri: stop/target/time restano di paper.step()."""
    st = paper.load()
    events = []
    now_iso = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(timespec="minutes")
    for sym, pos in list((st.get("open") or {}).items()):
        s = _snapshot(sym)
        if not s or s.get("trend") is None:
            continue
        want = "su" if pos["side"] == "long" else "giu"
        if s["trend"] != "piatto" and s["trend"] != want:
            try:
                last = s["price"]
            except Exception:
                continue
            pos.update({"exit": last, "exit_ts": now_iso, "reason": "ruolo 3: tesi invalidata",
                        "r": round(paper._r(pos["entry"], last, pos["stop"], pos["side"]), 3)})
            st["closed"].append(pos)
            del st["open"][sym]
            events.append(f"{sym}: chiusa {pos['side']} @ {_ps(last)} (trend {s['trend']}) "
                          f"-> {pos['r']:+.2f}R")
    if events and not dry:
        paper.save(st)
    return st, events
