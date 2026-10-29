"""Build desk.html: one screen, the real desk, nothing invented.

Reads paper_state.json + desk_log.jsonl + private_cfg.json, bakes a snapshot
into a single self-contained page. Paper only, no broker, no money.
"""
import json
import os
import datetime as dt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name, default):
    p = os.path.join(ROOT, name)
    if not os.path.exists(p):
        return default
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def last_cycle(rows):
    """The most recent row that actually saw news; falls back to the last row."""
    fallback = rows[-1] if rows else {}
    for r in reversed(rows):
        if r.get("news") and r["news"].get("sym"):
            return r
    return fallback


def curve(closed, n=80):
    pts = [float(c.get("r") or 0) for c in closed[-n:]]
    tot, out = 0.0, []
    for r in pts:
        tot += r
        out.append(round(tot, 3))
    return out


def stats(closed, n=0):
    rows = [float(c.get("r") or 0) for c in (closed[-n:] if n else closed)]
    if not rows:
        return {"n": 0, "win": 0, "wr": 0, "avg": 0, "total": 0, "flat": 0}
    moved = [r for r in rows if r != 0]
    wins = sum(1 for r in moved if r > 0)
    return {
        "n": len(rows),
        "win": wins,
        "wr": round(100.0 * wins / len(moved)) if moved else 0,
        "avg": round(sum(moved) / len(moved), 3) if moved else 0,
        "total": round(sum(rows), 1),
        "flat": len(rows) - len(moved),
    }


def exit_counts(closed):
    same = sum(1 for c in closed if c.get("entry_ts") == c.get("exit_ts"))
    killed = sum(1 for c in closed if "invalidata" in (c.get("reason") or ""))
    return {"same": same, "killed": killed}


def spark(pts, w=560, h=110):
    if len(pts) < 2:
        return "<div class=empty>ancora nessuna chiusura</div>"
    lo, hi = min(min(pts), 0), max(max(pts), 0)
    span = (hi - lo) or 1.0
    step = w / (len(pts) - 1)
    xy = []
    for i, v in enumerate(pts):
        x = i * step
        y = h - (v - lo) / span * h
        xy.append("%.1f,%.1f" % (x, y))
    zero = h - (0 - lo) / span * h
    colour = "#3ddc84" if pts[-1] >= 0 else "#ff5d5d"
    return (
        '<svg viewBox="0 0 %d %d" preserveAspectRatio="none" class=chart>'
        '<line x1=0 y1="%.1f" x2="%d" y2="%.1f" stroke="#333" stroke-width=1/>'
        '<polyline points="%s" fill=none stroke="%s" stroke-width=2/>'
        "</svg>" % (w, h, zero, w, zero, " ".join(xy), colour)
    )


def esc(s):
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def build():
    paper = _load("paper_state.json", {"open": {}, "closed": []})
    rows = []
    p = os.path.join(ROOT, "desk_log.jsonl")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        pass
    cyc = last_cycle(rows)
    news = cyc.get("news") or {}
    chart = cyc.get("chart") or {}
    verdict = cyc.get("verdict") or {}
    risk = cyc.get("risk") or {}
    opened = paper.get("open") or {}
    closed = paper.get("closed") or []
    st = stats(closed)
    rec = stats(closed, 200)
    ex = exit_counts(closed)
    pts = curve(closed)
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def role(name, sym, side, body, gate):
        cls = "ok" if gate else "no"
        tag = "PASSA" if gate else "BLOCCA"
        return (
            '<div class="role %s"><div class=rhead><span class=rname>%s</span>'
            '<span class=tag>%s</span></div>'
            '<div class=asset>%s%s</div><div class=why>%s</div></div>'
            % (
                cls,
                name,
                tag,
                esc(sym or "nessun asset"),
                (" <b>" + esc(side) + "</b>") if side else "",
                esc(body or "niente da dire"),
            )
        )

    roles = "".join([
        role("SCANNER", news.get("sym"), news.get("side"), news.get("why"), bool(news.get("sym"))),
        role("CHART", news.get("sym"), news.get("side"), chart.get("why"), bool(chart.get("confirm"))),
        role("VALIDATOR", news.get("sym"), news.get("side"), verdict.get("why") or "aspetta il modello", bool(verdict.get("action"))),
        role("RISK", news.get("sym"), news.get("side"), risk.get("why") or "nessun ordine da vetare", bool(risk.get("action")) or not risk.get("why")),
    ])

    pos = []
    for sym, t in list(opened.items()):
        pos.append(
            "<tr><td>%s</td><td class=%s>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td class=why>%s</td></tr>"
            % (
                esc(sym),
                "long" if t.get("side") == "long" else "short",
                esc(t.get("side")),
                esc("%.4g" % float(t.get("entry") or 0)),
                esc("%.4g" % float(t.get("stop") or 0)),
                esc("%.4g" % float(t.get("target") or 0)),
                esc(t.get("entry_ts", "")[5:16]),
                esc(t.get("reason", "")),
            )
        )
    if not pos:
        pos.append('<tr><td colspan=7 class=empty>nessuna posizione aperta</td></tr>')

    html = """<!doctype html><html lang=it><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>trading desk</title>
<style>
:root{--bg:#0b0d10;--card:#12161b;--line:#1f2630;--fg:#d8dee6;--dim:#7d8794;
--ok:#3ddc84;--no:#ff5d5d;--amb:#f0b429}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace;padding:14px}
h1{font-size:15px;margin:0;letter-spacing:.14em}
.top{display:flex;justify-content:space-between;align-items:baseline;
border-bottom:1px solid var(--line);padding-bottom:8px;margin-bottom:12px}
.meta{color:var(--dim);font-size:11px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:8px}
.role{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--no);
padding:9px 10px;min-height:96px}
.role.ok{border-left-color:var(--ok)}
.rhead{display:flex;justify-content:space-between;font-size:11px;color:var(--dim);
letter-spacing:.1em;margin-bottom:6px}
.tag{color:var(--no)}.role.ok .tag{color:var(--ok)}
.asset{font-size:15px;margin-bottom:3px}
.why{color:var(--dim);font-size:12px;line-height:1.35}
h2{font-size:11px;letter-spacing:.14em;color:var(--dim);margin:20px 0 8px;
border-bottom:1px solid var(--line);padding-bottom:5px}
table{width:100%%;border-collapse:collapse;font-size:12px}
th,td{text-align:left;padding:5px 6px;border-bottom:1px solid var(--line);
vertical-align:top}
th{color:var(--dim);font-weight:400;font-size:10px;letter-spacing:.1em}
td.long{color:var(--ok)}td.short{color:var(--amb)}
.chart{width:100%%;height:110px;display:block}
.kpi{display:flex;gap:16px;flex-wrap:wrap;margin:8px 0 2px;font-size:12px;color:var(--dim)}
.kpi b{color:var(--fg)}
.empty{color:var(--dim);font-size:12px}
.foot{margin-top:18px;color:var(--dim);font-size:11px;line-height:1.5}
a{color:var(--fg)}
</style>
<div class=top><h1>TRADING DESK</h1>
<div class=meta>snapshot %(now)s &middot; paper, soldi finti &middot; %(cycles)d cicli registrati</div></div>
<div class=grid>%(roles)s</div>

<h2>VERDETTO DEL DESK, SENZA TRUCCARE NIENTE</h2>
<div class=kpi>
<span>chiuse <b>%(n)d</b></span>
<span>media <b>%(avg)s R</b> sulle %(moved)d che si sono mosse</span>
<span>vinte <b>%(wr)d%%</b></span>
<span>ferme a zero <b>%(flat)d</b></span>
<span>ultime 200: <b>%(raw)s R</b> (media %(ravg)s)</span>
</div>
<div class=why style="margin-top:6px">%(killed)d chiuse su "tesi invalidata", %(same)d chiuse
sulla stessa candela dell'apertura. Due numeri che spiegano il resto meglio di
qualsiasi commento: il desk apre e poi si smentisce subito.</div>

<h2>REGISTRO OPERAZIONI APERTE</h2>
<table><tr><th>asset</th><th>lato</th><th>entrata</th><th>stop</th>
<th>target</th><th>aperta</th><th>ragione</th></tr>%(pos)s</table>

<h2>CURVA IN R (ultime %(npts)d chiuse)</h2>
%(spark)s
<div class=kpi><span>totale sulle ultime 80: <b>%(total)s R</b></span></div>

<div class=foot>Ogni riga viene dal registro paper del bot, su prezzi e notizie reali.
Nessun broker collegato, nessun soldo vero. Un R = una unita di rischio,
la distanza fra entrata e stop. Il desk e' euristico dichiarato: dove non
arriva il modello decide una regola, e lo scrive.</div>
""" % dict(
        now=now, cycles=len(rows), roles=roles, pos="".join(pos), npts=len(pts),
        spark=spark(pts), n=st["n"], win=st["win"], wr=st["wr"], avg=st["avg"],
        total=st["total"], flat=st["flat"], moved=st["n"] - st["flat"],
        ravg=rec["avg"], raw=rec["total"], made=rec["n"],
        killed=ex["killed"], same=ex["same"],
    )

    out = os.path.join(ROOT, "desk.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    return out, {"open": len(opened), "closed": st["n"], "cycles": len(rows), "snapshot": now}


if __name__ == "__main__":
    path, info = build()
    print(path, info)