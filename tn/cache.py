"""Cache su file per i dati di mercato.

Serve per una ragione sola: lo stratega guarda piu' timeframe, e ogni timeframe
e' una chiamata a Yahoo. Senza cache un giro costerebbe 2 chiamate per simbolo
invece di 1. La cache e' un file committato dallo stesso workflow che scrive lo
stato, cosi' la chiamata si fa una volta ogni TTL, non a ogni ciclo.
"""
import json
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "strat_cache.json")


def _load():
    try:
        with open(PATH, "r") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def get(key, ttl, fn):
    """Valore fresco se c'e', altrimenti chiama fn() e lo salva. None se fn fallisce."""
    d = _load()
    row = d.get(key) or {}
    if row.get("ts") and (time.time() - row["ts"]) < ttl:
        return row.get("v")
    v = None
    try:
        v = fn()
    except Exception:
        v = None
    if v is not None:
        d[key] = {"ts": time.time(), "v": v}
        try:
            with open(PATH, "w") as f:
                json.dump(d, f)
        except Exception:
            pass
    return v