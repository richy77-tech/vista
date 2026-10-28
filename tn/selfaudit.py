"""Quinto anello: il desk rilegge il proprio registro.

Non e' un riassunto per me: e' il numero che mi dice se sto girando a vuoto.
Legge desk_log.jsonl dall'ultimo audit, conta i giri, i motivi di scarto,
le aperture e i risultati delle chiuse, e restituisce due righe da mandare
al bot privato. Quando il registro e' vuoto o non c'e', esce senza toccare
niente: un audit che si inventa i numeri e' peggio di nessun audit.
"""
import json
import os
from collections import Counter
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOG = os.path.join(ROOT, "desk_log.jsonl")
STATE = os.path.join(ROOT, "audit_state.json")


def _last():
    try:
        return json.load(open(STATE, encoding="utf-8")).get("last_ts")
    except Exception:
        return None


def _save(ts):
    try:
        json.dump({"last_ts": ts}, open(STATE, "w", encoding="utf-8"))
    except Exception:
        pass


def _reason(s):
    s = (s or "").strip()
    for sep in (":", "—"):
        if sep in s:
            s = s.split(sep)[0]
    return s[:60] or "senza motivo scritto"


def read(since=None, path=None):
    """Conta i giri dopo `since` (ISO). Ritorna dict + ultimo ts visto."""
    if since is None:
        since = _last()
        if not since:
            # primo giro in assoluto: non leggo mille giri di storia e li
            # spaccio per "oggi". Finestra di 24 ore, e lo dico.
            since = (datetime.now(timezone.utc).replace(microsecond=0) -
                     timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = []
    for line in open(path or LOG, encoding="utf-8"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if since and (d.get("ts") or "") <= since:
            continue
        rows.append(d)
    if not rows:
        return None, since
    kinds = Counter(r.get("kind") for r in rows)
    reasons = Counter(_reason(((r.get("verdict") or {}).get("why") or
                               (r.get("note") or (r.get("news") or {}).get("why"))))
                      for r in rows if r.get("kind") == "skip")
    last_why = (rows[-1].get("verdict") or {}).get("why") or (rows[-1].get("news") or {}).get("why")
    return {"n": len(rows), "open": kinds.get("open", 0),
            "skip": kinds.get("skip", 0),
            "top": reasons.most_common(3), "last_why": last_why}, rows[-1].get("ts")


def report(since=None, path=None, save=False):
    """Due righe di verita'. None se non c'e' niente di nuovo da leggere."""
    d, last = read(since, path)
    if not d:
        return None
    pct = round(100.0 * d["skip"] / d["n"]) if d["n"] else 0
    l1 = "autoaudit · %d giri, %d aperture, %d scarti (%d%%)" % (
        d["n"], d["open"], d["skip"], pct)
    top = " · ".join("%s %d" % (k, v) for k, v in d["top"])
    l2 = ("motivi: " + top) if top else "motivi: nessuno scritto"
    if save:
        _save(last or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"))
    return l1 + "\n" + l2
