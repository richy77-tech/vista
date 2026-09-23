"""Motore di analisi delle news.

Due livelli, tenuti separati e dichiarati come tali:
  FACT / MARKET DATA  -> cio' che la fonte dice (titolo, link, numeri)
  AI INTERPRETATION   -> categoria, impatto, sentiment (mai presentati come fatto)

Se e' configurata una chiave AI (AI_API_KEY, endpoint OpenAI-compatibile) si usa
il modello; altrimenti si usa il classificatore a regole, che funziona sempre e
non inventa nulla. L'interpretazione AI non e' mai una previsione di prezzo.
"""
import json
import os
import re

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


def _ai_analyze(it):
    """Hook LLM opzionale, endpoint OpenAI-compatibile. Non testato senza chiave:
    se manca o fallisce, si torna alle regole. Non inventa numeri."""
    key = os.environ.get("AI_API_KEY")
    if not key:
        return None
    base = os.environ.get("AI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("AI_MODEL", "gpt-4o-mini")
    prompt = (
        "Sei un analista di mercati. Rispondi SOLO con JSON valido con chiavi: "
        "categories (lista tra BREAKING,BTC,CRYPTO,GOLD,SILVER,FOREX,STOCKS,INDICES,"
        "MACRO,CENTRAL BANKS,ENERGY,GEOPOLITICS,ETF,REGULATION), assets (lista), "
        "impact (LOW|MEDIUM|HIGH|CRITICAL), sentiment_score (0-100), "
        "interpretation (una frase, mai un consiglio di acquisto/vendita).\n\n"
        f"Titolo: {it.get('title','')}\nSommario: {it.get('summary','')[:400]}"
    )
    body = json.dumps({
        "model": model, "temperature": 0,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
    }).encode()
    try:
        from .http import fetch
        raw = fetch(base + "/chat/completions", headers={
            "Content-Type": "application/json", "Authorization": "Bearer " + key},
            timeout=40, tries=2)
        data = json.loads(raw)["choices"][0]["message"]["content"]
        return json.loads(data)
    except Exception:
        return None


def enrich(it):
    """Pipeline completa su una news: categorie, asset, impatto, sentiment.
    Ritorna il dict arricchito. 'ai_analysis' resta separato dal fatto."""
    cats = rule_categories(it)
    assets = rule_assets(it)
    impact = rule_impact(it, cats)
    sent = rule_sentiment(it)
    ai = _ai_analyze(it)
    analysis = ""
    if ai:
        cats = [c for c in (ai.get("categories") or cats) if c in CATEGORIES] or cats
        assets = ai.get("assets") or assets
        impact = ai.get("impact") if ai.get("impact") in ("LOW", "MEDIUM", "HIGH", "CRITICAL") else impact
        if isinstance(ai.get("sentiment_score"), int):
            sent = {"score": max(0, min(100, ai["sentiment_score"])),
                    "label": "bullish" if ai["sentiment_score"] >= 65
                    else "bearish" if ai["sentiment_score"] <= 35 else "neutral"}
        analysis = ai.get("interpretation", "")
    it = dict(it)
    it.update({"category": cats[0], "categories": cats, "assets": assets,
               "impact": impact, "sentiment": sent, "ai_analysis": analysis})
    return it


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
            it["sources"] = [it.get("source")]
            out.append(it)
    return out
