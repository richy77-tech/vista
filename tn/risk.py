"""AGENTE RISK MANAGER: l'unico veto che nessun altro ruolo puo' scavalcare.

Perche' un modulo e non un prompt: un limite di rischio deve essere un numero
che si controlla prima di aprire, non un'opinione scritta dopo. Il modello qui
non decide niente. Decide l'aritmetica.

Limiti (tutti in tn/tunables.py, cosi' si cambiano in un posto solo):
  risk_per_trade_pct  quanto si rischia per operazione
  max_total_risk_pct  rischio aperto totale, tutte le posizioni insieme
  max_open            quante posizioni aperte insieme
  max_dd_r            perdita cumulata massima, in multipli del rischio unitario
  min_rr              rapporto rischio/rendimento minimo accettato
  max_corr            correlazione massima ammessa con una posizione aperta
  corr_window         barre usate per la correlazione (default 60)

Il veto risponde sempre con una lista di controlli: cosi' nel registro resta
scritto non solo "bloccato", ma quale numero lo ha bloccato.
"""
from . import paper
from . import tunables as T

LIMITS = {
    "risk_per_trade_pct": T.p("risk_per_trade_pct", 1.0),
    "max_total_risk_pct": T.p("max_total_risk_pct", 5.0),
    "max_open": T.p("max_open", 3),
    "max_dd_r": T.p("max_dd_r", 10.0),
    "min_rr": T.p("min_rr", 1.5),
    "max_corr": T.p("max_corr", 0.80),
    "corr_window": T.p("corr_window", 60),
    "cooldown_h": T.p("cooldown_h", 6.0),
}


def _rr(entry, stop, target, side):
    risk = abs(entry - stop)
    reward = abs(target - entry) if target is not None else 0.0
    return (reward / risk) if risk > 0 else 0.0


def _corr(a, b):
    n = min(len(a), len(b))
    if n < 20:
        return None
    a, b = a[-n:], b[-n:]
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((x - mb) ** 2 for x in b)
    if va <= 0 or vb <= 0:
        return None
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    return cov / (va ** 0.5 * vb ** 0.5)


def open_risk_pct(st, limits=None):
    """Rischio aperto in % di capitale: ogni posizione rischia 1 unita' finche'
    lo stop non e' colpito. Non e' un mark-to-market, e' il caso peggiore."""
    L = limits or LIMITS
    return len(st.get("open") or {}) * L["risk_per_trade_pct"]


def drawdown_r(st, limits=None):
    """Somma degli R chiusi. Negativa = stai perdendo in multipli del rischio."""
    L = limits or LIMITS
    rs = [t.get("r") or 0.0 for t in (st.get("closed") or [])]
    return sum(rs[-200:]) if rs else 0.0


def _hours_since(ts):
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
    except Exception:
        return None


def veto_after_exit(st, sym, limits=None):
    """Dopo un'uscita lo stesso asset resta chiuso per un po'. Senza questa
    pausa il desk riapre la stessa idea ogni giro e produce churn a 0R:
    successo davvero il 21/10, decine di aperture e chiusure in due minuti."""
    L = limits or LIMITS
    for t in reversed(st.get("closed") or []):
        if t.get("symbol") == sym:
            h = _hours_since(t.get("exit_ts"))
            if h is not None and h < L["cooldown_h"]:
                return f"{sym} uscita {h:.1f}h fa, cooldown {L['cooldown_h']:.0f}h"
            return None
    return None


def vet(st, cand, closes=None, limits=None):
    """Controls a candidate BEFORE any role opens it.

    cand: {"sym","side","entry","stop","target"}
    closes: {sym: [chiusure]} for correlation. Missing data = the check is
    declared as not verifiable, never silently passed.
    Ritorna {"action":"allow"|"block","why":...,"checks":[{...}]}
    """
    L = limits or LIMITS
    checks = []
    blocked = None

    def add(name, ok, detail):
        nonlocal blocked
        checks.append({"check": name, "ok": ok, "detail": detail})
        if not ok and blocked is None:
            blocked = f"{name}: {detail}"

    entry, stop = cand.get("entry"), cand.get("stop")
    tgt = cand.get("target")
    if entry is None or stop is None:
        add("numeri", False, "entry o stop mancanti")
        return {"action": "block", "why": blocked, "checks": checks}

    rr = _rr(entry, stop, tgt, cand.get("side"))
    add("rr", rr >= L["min_rr"], f"R/R {rr:.2f} vs minimo {L['min_rr']:.2f}")

    n_open = len(st.get("open") or {})
    add("posizioni", n_open < L["max_open"], f"{n_open} aperte vs max {L['max_open']}")

    used = open_risk_pct(st, L)
    add("rischio_totale", used + L["risk_per_trade_pct"] <= L["max_total_risk_pct"],
        f"aperto {used:.1f}% + nuovo {L['risk_per_trade_pct']:.1f}% "
        f"vs max {L['max_total_risk_pct']:.1f}%")

    dd = drawdown_r(st, L)
    add("drawdown", dd > -L["max_dd_r"],
        f"cumulato {dd:+.2f}R vs limite {-L['max_dd_r']:.1f}R")

    sym = cand.get("sym")
    if sym in (st.get("open") or {}):
        add("doppione", False, f"{sym} gia' aperta")
    cold = veto_after_exit(st, sym, L)
    if cold:
        add("cooldown", False, cold)

    worst = None
    corr_checked = corr_missing = 0
    for s2, pos in (st.get("open") or {}).items():
        if s2 == sym:
            continue
        duo = None
        if closes and closes.get(sym) and closes.get(s2):
            duo = _corr(closes[sym][-L["corr_window"]:], closes[s2][-L["corr_window"]:])
        if duo is None:
            corr_missing += 1
            continue
        corr_checked += 1
        same_side = pos.get("side") == cand.get("side")
        eff = duo if same_side else -duo
        if worst is None or eff > worst[1]:
            worst = (s2, eff)
    if worst is not None:
        add("correlazione", worst[1] < L["max_corr"],
            f"{sym} vs {worst[0]} {worst[1]:+.2f} vs max {L['max_corr']:.2f} (stesso verso)")
    else:
        add("correlazione", True,
            f"non verificabile ({corr_missing} posizioni senza serie)" if corr_missing
            else "nessuna posizione aperta")

    why = blocked if blocked else (
        f"ok: R/R {rr:.2f}, {n_open} aperte, rischio {used + L['risk_per_trade_pct']:.1f}%"
        f", dd {dd:+.2f}R")
    return {"action": "block" if blocked else "allow", "why": why, "checks": checks}


def summary(st, limits=None):
    """Riga di stato del risk manager, per il registro e per il bot."""
    L = limits or LIMITS
    dd = drawdown_r(st, L)
    return {"open": len(st.get("open") or {}), "risk_pct": open_risk_pct(st, L),
            "dd_r": round(dd, 3), "limits": L,
            "status": "bloccato" if dd <= -L["max_dd_r"] else "operativo"}
