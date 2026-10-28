"""Esecuzione: un solo tubo, piu' adapter.

Non entra una chiave finche' una regola non tiene fuori campione. Fino a quel
momento l'unico adapter che puo' rispondere senza alzare un errore e' 'paper'.

Guardie (tutte e tre servono perche' un adapter reale risponda):
  1. EXEC_KILLSWITCH != "1"   -> se e' 1, tutto si ferma
  2. EXEC_LIVE == "1"         -> default spento: resta in paper
  3. le chiavi dell'owner presenti nell'ambiente
  4. il gate di ingresso dice 'live' per quella regola su quel mercato
Le chiavi non vivono qui e non vivono nel sandbox: stanno come secret del repo,
dell'owner, mai in custodia mia.

Cosa e' scritto e cosa no, per non raccontarsela:
- gli adapter reali (binance, coinbase, alpaca) hanno la forma e le guardie
- la chiamata firmata all'exchange NON e' ancora scritta: si scrive quando
  c'e' una chiave e una regola che ha tenuto fuori campione. Non spedisco
  codice che muove soldi senza averlo potuto provare.
"""
import os


class Rejected(Exception):
    """Un ordine che non deve partire. Non e' un errore tecnico, e' una scelta."""


KILL = os.environ.get("EXEC_KILLSWITCH", "0") == "1"


class PaperAdapter:
    """Nessun ordine vero. Registra l'intento, nient'altro."""
    name = "paper"

    def place(self, symbol, side, qty, stop=None, target=None, meta=None):
        return {"adapter": self.name, "dry": True, "symbol": symbol, "side": side,
                "qty": qty, "stop": stop, "target": target, "status": "recorded"}

    def close(self, symbol, qty=None):
        return {"adapter": self.name, "dry": True, "symbol": symbol,
                "qty": qty, "status": "recorded"}


class LiveAdapter:
    """Base degli adapter reali. Senza le tre guardie non risponde: solleva."""
    name = "live"
    requires = ()

    def armed(self):
        if KILL:
            raise Rejected("kill switch attivo")
        if os.environ.get("EXEC_LIVE") != "1":
            raise Rejected("EXEC_LIVE non attivo: resta in paper")
        missing = [e for e in self.requires if not os.environ.get(e)]
        if missing:
            raise Rejected("chiavi mancanti: " + ",".join(missing))
        return True

    def place(self, symbol, side, qty, stop=None, target=None, meta=None):
        self.armed()
        # quarta guardia: la regola deve avere il gate 'live' su QUESTO mercato.
        # Nessuna chiave, nessun killswitch spento, nessuna regola dimostrata
        # fuori campione = nessun ordine vero.
        from . import gates
        rule = (meta or {}).get("rule") or (meta or {}).get("reason") or "rottura"
        ok, why = gates.allow(rule, symbol, live=True)
        if not ok:
            raise Rejected(why)
        raise NotImplementedError(
            "firma exchange non ancora scritta: si scrive con una chiave vera "
            "e una regola che ha tenuto fuori campione")

    def close(self, symbol, qty=None):
        self.armed()
        raise NotImplementedError("firma exchange non ancora scritta")


class BinanceAdapter(LiveAdapter):
    name = "binance"
    requires = ("BINANCE_API_KEY", "BINANCE_API_SECRET")


class CoinbaseAdapter(LiveAdapter):
    name = "coinbase"
    requires = ("COINBASE_API_KEY", "COINBASE_API_SECRET")


class AlpacaAdapter(LiveAdapter):
    name = "alpaca"
    requires = ("ALPACA_KEY_ID", "ALPACA_SECRET")


ADAPTERS = {"paper": PaperAdapter, "binance": BinanceAdapter,
            "coinbase": CoinbaseAdapter, "alpaca": AlpacaAdapter}


def get(name=None):
    """Adapter attivo. Default 'paper', sempre, se nessuno dice altro."""
    name = name or os.environ.get("EXEC_ADAPTER", "paper")
    return ADAPTERS.get(name, PaperAdapter)()


def status():
    cur = os.environ.get("EXEC_ADAPTER", "paper")
    return {"adapter": cur, "killswitch": KILL,
            "live_armed": os.environ.get("EXEC_LIVE") == "1",
            "available": sorted(ADAPTERS)}
