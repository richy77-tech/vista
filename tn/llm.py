"""Benzina del modello, senza chiave dell'utente.

Due strade, in quest'ordine:
  1. endpoint OpenAI-compatibile con AI_API_KEY (Groq e simili), se c'e' e non e' in pausa
  2. Pollinations (text.pollinations.ai): nessuna chiave, nessun account, gratis.
     Ripiego vero, non un giocattolo: se cade, si torna alle regole.

Non inventa numeri: chi chiama decide cosa farne. Se nessuna strada risponde,
si restituisce None e il chiamante usa le regole.
"""
import json
import os
import time
import urllib.parse

# Pollinations non ha chiavi da revocare: il suo freno e' solo il mio.
_P_FAILS = 0
_P_UNTIL = 0.0
P_URL = "https://text.pollinations.ai/"


def _p_blocked():
    return time.time() < _P_UNTIL


def _p_note(ok):
    global _P_FAILS, _P_UNTIL
    if ok:
        _P_FAILS, _P_UNTIL = 0, 0.0
    else:
        _P_FAILS += 1
        if _P_FAILS >= 3:
            _P_FAILS, _P_UNTIL = 0, time.time() + 600


# quale strada ha risposto per ultima: serve a capire nei log se parla il
# modello o le regole, senza doverlo dedurre dal testo.
LAST_ROUTE = ""


def routes():
    """Le chiavi si provano in ordine, la prima che risponde vince.

    AI_API_KEY e' la principale; _2 e _3 sono riserve con endpoint e modello
    propri (es. OpenRouter davanti, Groq dietro). Una quota finita non deve
    far cadere il desk sulle regole quando esiste una seconda porta.
    """
    out = []
    for suf in ("", "_2", "_3"):
        key = os.environ.get("AI_API_KEY" + suf)
        if not key:
            continue
        base = os.environ.get("AI_BASE_URL" + suf, "https://api.openai.com/v1").rstrip("/")
        model = os.environ.get("AI_MODEL" + suf, "gpt-4o-mini")
        out.append((key, base, model))
    return out


def _one(key, base, model, system, user, json_mode, timeout):
    payload = {"model": model, "temperature": 0,
               "messages": [{"role": "system", "content": system},
                            {"role": "user", "content": user}]}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    try:
        from .http import post_json
        d = post_json(base + "/chat/completions", payload,
                      headers={"Authorization": "Bearer " + key},
                      timeout=timeout, tries=1 if len(routes()) > 1 else 2)
        return d["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def _keyed(system, user, json_mode, timeout):
    global LAST_ROUTE
    for key, base, model in routes():
        out = _one(key, base, model, system, user, json_mode, timeout)
        if _usable(out, json_mode):
            LAST_ROUTE = model
            return out
    return None


def _pollinations(system, user, json_mode, timeout):
    if _p_blocked():
        return None
    prompt = user if not system else (system + "\n\n" + user)
    models = [os.environ.get("POLL_MODEL", "openai"), "openai-fast"]
    from .http import fetch
    for model in models:
        q = {"model": model}
        if json_mode:
            q["json"] = "true"
        url = P_URL + urllib.parse.quote(prompt) + "?" + urllib.parse.urlencode(q)
        try:
            raw = fetch(url, timeout=timeout, tries=2).decode("utf-8", "replace").strip()
        except Exception:
            raw = ""
        if not raw:
            continue
        # la stessa porta a volte incapsula il JSON in una recinzione markdown
        if json_mode and raw.startswith("```"):
            raw = raw.strip("`")
            raw = raw[raw.find("{"):raw.rfind("}") + 1]
        _p_note(True)
        return raw
    _p_note(False)
    return None


def _usable(out, json_mode):
    """Un endpoint morto puo' rispondere 'OK' con un 200. Non e' una risposta."""
    if not out:
        return False
    if len(out.strip()) < 8 and out.strip().upper() in ("OK", "OKAY", "TRUE"):
        return False
    if json_mode and not out.lstrip().startswith("{"):
        return False
    return True


def chat(system, user, json_mode=False, timeout=45):
    global LAST_ROUTE
    out = _keyed(system, user, json_mode, timeout)
    if _usable(out, json_mode):
        return out
    out = _pollinations(system, user, json_mode, timeout)
    LAST_ROUTE = "pollinations" if _usable(out, json_mode) else "rules"
    return out
