"""GATE DI INGRESSO: chi puo' aprire, e su quale mercato.

Perche' un file e non un'opinione scritta dopo: lo stato di una regola deve
essere leggibile prima dell'ingresso, non raccontato dopo la perdita.

Tre stati, uno solo ammette soldi veri:
  off    non apre niente, nemmeno in paper
  paper  apre solo in simulazione (default: nessuna prova fuori campione)
  live   ammesso con capitale reale

Il default e' 'paper' per scelta: una regola non dimostrata si puo' osservare,
non pagare. Se il file manca o una voce manca, il verdetto e' 'paper' e la
ragione lo dichiara. Non si passa mai a 'live' per silenzio.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FILE = os.path.join(ROOT, "entry_gates.json")

STATES = ("off", "paper", "live")


def load():
    try:
        with open(FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d.get("rules") or {}
    except Exception:
        return {}


def gate(rule, sym, data=None):
    """Lo stato dichiarato per (regola, simbolo), con la sua ragione."""
    rules = data if data is not None else load()
    r = rules.get(rule) or {}
    entry = r.get(sym) or r.get("default") or {}
    status = entry.get("status")
    if status not in STATES:
        return {"status": "paper",
                "why": "stato non dichiarato: resta in paper finche' qualcuno non lo prova"}
    return {"status": status, "why": entry.get("why", "")}


def allow(rule, sym, live=False, data=None):
    """(bool, ragione). live=True significa che l'ordine tocca capitale reale."""
    g = gate(rule, sym, data)
    if g["status"] == "off":
        return False, f"gate off: {g['why']}"
    if live and g["status"] != "live":
        return False, f"gate {g['status']}: {g['why']} (serve 'live')"
    return True, f"gate {g['status']}"