"""La chiusura deve finire in desk_log.jsonl, non solo in paper_state.json.

Il buco trovato dall'esterno il 03/11: 3.182 rifiuti registrati, zero chiusure.
Chi leggeva il log vedeva tutti i no e mai il conto. Qui si verifica il gancio.
"""
import json
import os
import tempfile

from tn import desk3


def _with_temp(fn):
    d = tempfile.mkdtemp()
    old = desk3.TRAIN_LOG
    desk3.TRAIN_LOG = os.path.join(d, "desk_log.jsonl")
    try:
        fn(desk3.TRAIN_LOG)
    finally:
        desk3.TRAIN_LOG = old


def test_una_chiusura_scrive_una_riga():
    def body(path):
        desk3.log_close({"symbol": "SI=F", "side": "long", "entry": 10.0, "exit": 9.0,
                         "stop": 9.0, "target": 12.0, "bars": 3, "r": -1.0,
                         "exit_reason": "stop", "entry_ts": "2026-11-03T08:00Z",
                         "exit_ts": "2026-11-03T08:25Z", "headline": "x"})
        rows = [json.loads(l) for l in open(path, encoding="utf-8").read().splitlines()]
        assert len(rows) == 1
        r = rows[0]
        assert r["kind"] == "close" and r["opened"] is False
        assert r["close"]["r"] == -1.0 and r["close"]["why"] == "stop"
        assert "-1.00R" in r["note"]
    _with_temp(body)


def test_una_chiusura_senza_r_non_esplode():
    def body(path):
        desk3.log_close({"symbol": "X"})
        rows = [json.loads(l) for l in open(path, encoding="utf-8").read().splitlines()]
        assert rows[0]["close"]["sym"] == "X"
    _with_temp(body)
