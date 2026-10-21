"""Motore di analisi delle news.

Due livelli, tenuti separati e dichiarati come tali:
  FACT / MARKET DATA  -> cio' che la fonte dice (titolo, link, numeri)
  AI INTERPRETATION   -> categoria, impatto, sentiment (mai presentati come fatto)

Se e' configurata una chiave AI (AI_API_KEY, endpoint OpenAI-compatibile) si usa
il modello; altrimenti si usa il classificatore a regole, che funziona sempre e
non inventa nulla. L'interpretazione AI non e' mai una previsione di prezzo.
"""
import hashlib
import json
import os
import re
import time

# Il modello gratuito risponde a raffica, poi chiude la porta (429). Se fallisce
# tre volte di fila smetto di provarci per un quarto d'ora: le regole restano
# accese e il giro successivo riprova da solo.
_AI_FAILS = 0
_AI_UNTIL = 0.0


def ai_blocked():
    return time.time() < _AI_UNTIL


def note_ai(ok):
    global _AI_FAILS, _AI_UNTIL
    if ok:
        _AI_FAILS, _AI_UNTIL = 0, 0.0
    else:
        _AI_FAILS += 1
        if _AI_FAILS >= 3:
            _AI_FAILS, _AI_UNTIL = 0, time.time() + 900

CATEGORIES = {
    "BREAKING": ["breaking", "urgent", "flash", "just in", "ultim'ora"],
    "BTC": ["bitcoin", "btc", "satoshi"],
    "CRYPTO": ["crypto", "ethereum", "eth", "altcoin", "token", "defi", "stablecoin",
               "solana", "xrp", "ripple", "binance", "coinbase", "exchange"],
    "GOLD": ["gold", "oro", "bullion", "xau"],
    "SILVER": ["silver", "argento", "xag"],
    "FOREX": ["forex", "eur/usd", "gbp/usd", "usd/jpy", "dollar", "dollaro", "euro",
              "currency", "valuta", "yield", "treasury", "bond"],
    "STOCKS": ["stock", "shares", "earnings", "equity", "nasdaq", "s&p", "dow",
               "apple", "nvidia", "tesla", "microsoft"],
    "INDICES": ["index", "indices", "indice", "s&p 500", "ftse", "dax", "nikkei"],
    "MACRO": ["inflation", "inflazione", "cpi", "ppi", "gdp", "pil", "pmi",
              "unemployment", "disoccupazione", "retail sales", "recession",
              "recessione", "jobless", "nfp", "payroll"],
    "CENTRAL BANKS": ["fed", "federal reserve", "ecb", "bce", "boe", "boj", "rate",
                      "rates", "tassi", "fomc", "powell", "lagarde", "hawkish", "dovish"],
    "ENERGY": ["oil", "petrolio", "opec", "gas", "brent", "wti", "energy"],
    "GEOPOLITICS": ["war", "guerra", "sanctions", "sanzioni", "tariff", "dazi",
                    "geopolitic", "conflict", "strike", "election"],
    "ETF": ["etf", "spot etf", "inflow", "outflow"],
    "REGULATION": ["sec", "regulation", "regolament", "lawsuit", "court", "ban",
                   "crackdown", "fine", "settlement", "mica", "cftc"],
}

ASSETS = {
    "BTC": ["bitcoin", "btc"], "ETH": ["ethereum", "eth"],
    "GOLD": ["gold", "oro", "xau"], "SILVER": ["silver", "argento", "xag"],
    "USD": ["dollar", "dollaro", "usd", "dxy"], "EUR": ["euro", "eur"],
    "JPY": ["yen", "jpy"], "GBP": ["pound", "sterlina", "gbp"],
    "OIL": ["oil", "petrolio", "brent", "wti"],
    "EQUITIES": ["stocks", "equity", "s&p", "nasdaq", "dow", "shares"],
    "VIX": ["vix", "volatility"],
}

# Shock veri: rari. Se non c'e' uno di questi, non e' CRITICAL.
CRIT_WORDS = ["flash crash", "halt trading", "emergency rate", "declares default",
              "sovereign default", "declares war", "invasion", "market collapse",
              "bank collapse", "contagion"]
# Movers chiari: decisioni, shock, sorprese.
HIGH_WORDS = ["crash", "plunge", "surge", "soar", "slump", "hack", "exploit",
              "bankrupt", "indict", "rate decision", "rate hike", "rate cut",
              "rate pause", "record high", "record low", "sanctions", "tariff",
              "rejects", "approves", "emergency"]
# Routine: banca centrale che pubblica atti ordinari, non e' una notizia di mercato.
ROUTINE_WORDS = ["announces approval of application", "enforcement action",
                 "termination of enforcement", "survey", "bank holiday",
                 "monthly report", "speaks", "minutes of the", "holiday",
                 "publication", "opinion on", "appointment of", "annual report"]

POS = ["rally", "surge", "soar", "gain", "rise", "jump", "record high", "bullish",
       "approval", "approve", "inflow", "beat", "strong", "rialzo", "cresce", "su"]
NEG = ["crash", "plunge", "fall", "drop", "slump", "fear", "bearish", "reject",
       "hack", "lawsuit", "ban", "outflow", "miss", "weak", "default",
       "ribasso", "crolla", "giu", "perdita"]


def _text(it):
    return (it.get("title", "") + " " + it.get("summary", "")).lower()


def rule_categories(it):
    t = _text(it)
    cats = [c for c, kws in CATEGORIES.items() if any(k in t for k in kws)]
    return cats or ["MACRO"]


def rule_assets(it):
    t = _text(it)
    return [a for a, kws in ASSETS.items() if any(k in t for k in kws)]


def rule_impact(it, cats):
    t = _text(it)
    tier = it.get("tier", 2)
    score = 0
    crit = any(k in t for k in CRIT_WORDS)
    if crit:
        score += 4
    if any(k in t for k in HIGH_WORDS):
        score += 2
    if "BREAKING" in cats:
        score += 1
    if "CENTRAL BANKS" in cats and any(
            k in t for k in ("rate", "fomc", "decision", "tassi", "lagarde", "powell")):
        score += 2
    if "MACRO" in cats or "GEOPOLITICS" in cats or "REGULATION" in cats:
        score += 1
    if tier == 1 and any(k in t for k in ("rate", "policy", "decision", "emergency")):
        score += 1
    if any(k in t for k in ROUTINE_WORDS):
        score -= 3
    if crit:
        return "CRITICAL"
    return ("HIGH" if score >= 3 else "MEDIUM" if score >= 2 else "LOW")


def rule_sentiment(it):
    t = _text(it)
    p = sum(1 for w in POS if w in t)
    n = sum(1 for w in NEG if w in t)
    if p == n == 0:
        return {"score": 50, "label": "neutral"}
    score = int(50 + 50 * (p - n) / max(1, p + n))
    score = max(0, min(100, score))
    label = ("bullish" if score >= 65 else "bearish" if score <= 35 else "neutral")
    return {"score": score, "label": label}


# Il modello gratuito ha un tetto di token al giorno (200k su Groq). Un feed da
# 13 fonti riporta le stesse notizie ogni 20 minuti: senza memoria l'analisi
# brucia il tetto in un'ora e per il resto del giorno tace. Qui tengo da parte
# il verdetto di ogni notizia gia' vista, su file, cosi' il ciclo successivo
# non la richiede.
MEMO_PATH = os.environ.get(
    "AI_MEMO",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "ai_cache.json"))
MEMO_MAX = 500
_MEMO = None


def _memo_key(it):
    raw = (it.get("title", "") + "|" + (it.get("summary") or "")[:200])
    return hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()[:20]


def _memo_load():
    global _MEMO
    if _MEMO is None:
        try:
            with open(MEMO_PATH) as f:
                _MEMO = json.load(f)
        except Exception:
            _MEMO = {}
    return _MEMO


def _memo_put(key, val):
    m = _memo_load()
    m[key] = val
    while len(m) > MEMO_MAX:            # via le voci piu' vecchie
        m.pop(next(iter(m)), None)
    try:
        tmp = MEMO_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(m, f, ensure_ascii=False)
        os.replace(tmp, MEMO_PATH)
    except Exception:
        pass


def _ai_analyze(it):
    """Hook LLM opzionale. Prima l'endpoint con chiave, poi Pollinations
    (nessuna chiave). Se nessuno risponde, si torna alle regole."""
    from . import llm
    if ai_blocked():
        return None
    system = (
        "Sei un analista di mercati. Rispondi SOLO con JSON valido con chiavi: "
        "categories (lista tra BREAKING,BTC,CRYPTO,GOLD,SILVER,FOREX,STOCKS,INDICES,"
        "MACRO,CENTRAL BANKS,ENERGY,GEOPOLITICS,ETF,REGULATION), assets (lista), "
        "impact (LOW|MEDIUM|HIGH|CRITICAL), sentiment_score (0-100), "
        "interpretation (una frase, mai un consiglio di acquisto/vendita)."
    )
    user = (f"Titolo: {it.get('title','')}\n"
            f"Sommario: {it.get('summary','')[:400]}")
    data = llm.chat(system, user, json_mode=True, timeout=40)
    if not data:
        note_ai(False)
        return None
    try:
        out = json.loads(data)
        note_ai(True)
        return out
    except Exception:
        note_ai(False)
        return None


def rules(it):
    """Livello regole: offline, gratis, sempre acceso. Non inventa nulla."""
    cats = rule_categories(it)
    it = dict(it)
    it.update({"category": cats[0], "categories": cats, "assets": rule_assets(it),
               "impact": rule_impact(it, cats), "sentiment": rule_sentiment(it),
               "ai_analysis": ""})
    return it


def overlay(it):
    """Livello AI su un item gia' passato dalle regole. Senza chiave (o con il
    modello in pausa) l'item torna esattamente com'e'."""
    key = _memo_key(it)
    a = _memo_load().get(key)
    if a is None:
        a = _ai_analyze(it)
        if a:
            _memo_put(key, a)
    if not a:
        return it
    cats = [c for c in (a.get("categories") or it["categories"]) if c in CATEGORIES] \
        or it["categories"]
    assets = a.get("assets") or it["assets"]
    impact = a.get("impact") if a.get("impact") in ("LOW", "MEDIUM", "HIGH", "CRITICAL") \
        else it["impact"]
    sent = it["sentiment"]
    if isinstance(a.get("sentiment_score"), int):
        s = max(0, min(100, a["sentiment_score"]))
        sent = {"score": s, "label": "bullish" if s >= 65
                else "bearish" if s <= 35 else "neutral"}
    it = dict(it)
    it.update({"category": cats[0], "categories": cats, "assets": assets,
               "impact": impact, "sentiment": sent,
               "ai_analysis": a.get("interpretation", "")})
    return it


def enrich(it):
    """Pipeline completa su una news: categorie, asset, impatto, sentiment.
    Ritorna il dict arricchito. 'ai_analysis' resta separato dal fatto."""
    return overlay(rules(it))


def norm_title(t):
    t = re.sub(r"[^a-z0-9 ]+", " ", t.lower())
    stop = {"the", "a", "an", "of", "to", "in", "on", "for", "and", "as", "at",
            "is", "are", "with", "by", "after", "over", "il", "lo", "la", "di"}
    return {w for w in t.split() if w not in stop and len(w) > 2}


def is_dup(a, b, thr=0.6):
    ta, tb = norm_title(a), norm_title(b)
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= thr


def dedup(items):
    """Raggruppa la stessa notizia da fonti diverse in un solo elemento,
    conservando tutte le fonti."""
    out = []
    for it in items:
        for kept in out:
            if is_dup(it["title"], kept["title"]):
                if it.get("source") not in kept["sources"]:
                    kept["sources"].append(it.get("source"))
                    kept.setdefault("extra_urls", []).append(it["url"])
                # tieni la versione con impatto piu' alto
                rank = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
                if rank[it["impact"]] > rank[kept["impact"]]:
                    kept.update({"impact": it["impact"], "sentiment": it["sentiment"],
                                 "category": it["category"]})
                break
        else:
            it = dict(it)
            it["sources"] = list(it.get("sources") or [it.get("source")])
            out.append(it)
    return out
