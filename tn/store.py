"""Storico locale su SQLite: news, alert, eventi macro, snapshot di mercato.

ATTENZIONE: la sandbox e' effimera. Il file DB sopravvive tra un heartbeat e
l'altro solo finche' la sandbox resta viva; per una persistenza vera serve un
host sempre acceso (VPS). Il DB serve a deduplicare e a tenere lo storico
consultabile, non e' un archivio garantito. Per non perdere l'essenziale si
esporta anche un JSON leggero in data/.
"""
import json
import os
import sqlite3
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("VISTA_DB", os.path.join(HERE, "..", "data", "history.db"))
SNAP = os.path.join(HERE, "..", "data", "news_history.json")

SCHEMA = """
CREATE TABLE IF NOT EXISTS news (
  id TEXT PRIMARY KEY, ts TEXT, source TEXT, title TEXT, url TEXT,
  summary TEXT, category TEXT, assets TEXT, impact TEXT, sentiment TEXT,
  ai_analysis TEXT, published INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, kind TEXT, symbol TEXT,
  detail TEXT
);
CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY, ts TEXT, country TEXT, title TEXT, impact TEXT,
  forecast TEXT, previous TEXT, actual TEXT
);
CREATE TABLE IF NOT EXISTS market (
  ts TEXT, symbol TEXT, price REAL, change_pct REAL, extra TEXT
);
"""


def conn():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB)
    c.executescript(SCHEMA)
    return c


def _now():
    return datetime.now(timezone.utc).isoformat()


def save_news(items):
    """items: lista di dict dal news engine. Ignora i duplicati per id."""
    c = conn()
    n = 0
    for it in items:
        try:
            c.execute(
                "INSERT OR IGNORE INTO news (id,ts,source,title,url,summary,category,"
                "assets,impact,sentiment,ai_analysis,published) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (it["id"], it.get("ts") or _now(), it.get("source"), it["title"], it["url"],
                 it.get("summary", ""), it.get("category", ""), json.dumps(it.get("assets", [])),
                 it.get("impact", "LOW"), json.dumps(it.get("sentiment", {})),
                 it.get("ai_analysis", ""), 1 if it.get("published") else 0))
            n += c.total_changes and 1
        except Exception:
            pass
    c.commit()
    c.close()
    return n


def seen_ids():
    try:
        c = conn()
        rows = {r[0] for r in c.execute("SELECT id FROM news")}
        c.close()
        return rows
    except Exception:
        return set()


def save_alerts(rows):
    c = conn()
    for kind, symbol, detail in rows:
        c.execute("INSERT INTO alerts (ts,kind,symbol,detail) VALUES (?,?,?,?)",
                  (_now(), kind, symbol, detail))
    c.commit()
    c.close()


def save_events(events):
    c = conn()
    for e in events:
        c.execute("INSERT OR REPLACE INTO events (id,ts,country,title,impact,forecast,previous,actual)"
                  " VALUES (?,?,?,?,?,?,?,?)",
                  (e["id"], e["ts"], e["country"], e["title"], e["impact"],
                   e.get("forecast", ""), e.get("previous", ""), e.get("actual", "")))
    c.commit()
    c.close()


def save_market(snapshot):
    """snapshot: lista di (symbol, price, change_pct, extra)."""
    c = conn()
    ts = _now()
    for sym, price, ch, extra in snapshot:
        c.execute("INSERT INTO market (ts,symbol,price,change_pct,extra) VALUES (?,?,?,?,?)",
                  (ts, sym, price, ch, json.dumps(extra or {})))
    c.commit()
    c.close()


def export_snapshot(limit=300):
    """JSON leggero, pensato per essere committato su GitHub: cosi' lo storico
    delle news sopravvive alla sandbox."""
    try:
        c = conn()
        rows = c.execute(
            "SELECT ts,source,title,url,category,assets,impact,sentiment FROM news"
            " ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        c.close()
        out = []
        for ts, source, title, url, cat, assets, impact, sent in rows:
            out.append({"ts": ts, "source": source, "title": title, "url": url,
                        "category": cat, "assets": json.loads(assets or "[]"),
                        "impact": impact, "sentiment": json.loads(sent or "{}")})
        os.makedirs(os.path.dirname(SNAP), exist_ok=True)
        with open(SNAP, "w") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        return len(out)
    except Exception:
        return 0
