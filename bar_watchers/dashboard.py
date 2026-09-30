#!/usr/bin/env python3
"""Generate a static HTML dashboard from games.db.
Refresh by running periodically or via supervisor loop.
Open the output in a browser: file:///path/to/dashboard_out/index.html
"""
from __future__ import annotations
import html, json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from watchers_schema import connect
from config import load as load_cfg

HERE = Path(__file__).resolve().parent

TEMPLATE = """<!doctype html>
<html><head>
<meta charset="utf-8"><title>BAR watchers</title>
<meta http-equiv="refresh" content="30">
<style>
  body{{font-family:system-ui,-apple-system,sans-serif;margin:24px;background:#0f0f17;color:#e8e8f0}}
  h1{{margin:0 0 16px}} h2{{margin:24px 0 8px;color:#89e5ff}}
  table{{border-collapse:collapse;width:100%;margin-bottom:24px}}
  th,td{{padding:6px 10px;border-bottom:1px solid #2a2a3a;text-align:left;font-size:13px}}
  th{{color:#a0a0c0;background:#181828}}
  tr.running td{{color:#a0e0a0}} tr.ended td{{color:#807080}}
  .num{{text-align:right;font-variant-numeric:tabular-nums}}
  .meta{{color:#7080a0;font-size:11px;margin-top:24px}}
  .pill{{padding:2px 8px;border-radius:10px;font-size:11px;background:#282838}}
  .pill.hot{{background:#40202a;color:#ffb0b0}}
</style>
</head><body>
<h1>BAR watchers <span class="pill">{gen}</span></h1>

<h2>Active watchers ({n_active})</h2>
{active_table}

<h2>Recently ended ({n_recent})</h2>
{recent_table}

<h2>Summary</h2>
<ul>
  <li>Total games tracked: {n_games}</li>
  <li>Snapshots collected: {n_snap}</li>
  <li>Events recorded: {n_evt}</li>
  <li>Replays archived: {n_rep}</li>
</ul>
<div class="meta">config: {cfg_path} | db: {db_path}</div>
</body></html>"""

def _table(rows, cols):
    if not rows: return "<p><i>none</i></p>"
    # cols is a list of (key, header[, css_class]) tuples
    th = "".join(f"<th>{c[1]}</th>" for c in cols)
    trs = []
    for r in rows:
        cls = r.get("_cls","")
        tds = "".join(f'<td class="{c[2] if len(c)>2 else ""}">{html.escape(str(r.get(c[0], "")))}</td>' for c in cols)
        trs.append(f'<tr class="{cls}">{tds}</tr>')
    return f"<table><thead><tr>{th}</tr></thead><tbody>{''.join(trs)}</tbody></table>"

def main():
    cfg = load_cfg()
    conn = connect()
    now = time.time()

    active_rows_raw = conn.execute("""SELECT battle_id, title, map_name, founder,
                                             initial_avg_os, peak_avg_os,
                                             (last_seen - first_seen) as age_s
                                      FROM games WHERE watcher_status='running'
                                      ORDER BY peak_avg_os DESC LIMIT 40""").fetchall()
    active_rows = [{
        "battle": f"#{r[0]}", "title": (r[1] or "")[:30], "map": (r[2] or "")[:32],
        "founder": (r[3] or "")[:16], "avg": f"{r[4] or 0:.1f}",
        "peak": f"{r[5] or 0:.1f}", "age": f"{int(r[6] or 0)//60}m", "_cls": "running",
    } for r in active_rows_raw]

    ended_rows_raw = conn.execute("""SELECT battle_id, title, map_name, founder,
                                            peak_avg_os,
                                            (ended_at - first_seen) as dur_s
                                     FROM games
                                     WHERE ended_at IS NOT NULL
                                     ORDER BY ended_at DESC LIMIT 40""").fetchall()
    ended_rows = [{
        "battle": f"#{r[0]}", "title": (r[1] or "")[:30], "map": (r[2] or "")[:32],
        "founder": (r[3] or "")[:16], "peak": f"{r[4] or 0:.1f}",
        "dur": f"{int(r[5] or 0)//60}m", "_cls": "ended",
    } for r in ended_rows_raw]

    cols_active = [("battle","BATTLE"), ("title","TITLE"), ("map","MAP"), ("founder","FOUNDER"),
                   ("avg","AVG OS","num"), ("peak","PEAK","num"), ("age","AGE","num")]
    cols_ended = [("battle","BATTLE"), ("title","TITLE"), ("map","MAP"), ("founder","FOUNDER"),
                  ("peak","PEAK","num"), ("dur","DURATION","num")]

    ns = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    ne = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    ng = conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    nr = conn.execute("SELECT COUNT(*) FROM games WHERE replay_path IS NOT NULL AND replay_path!=''").fetchone()[0] if _has_col(conn) else 0

    html_out = TEMPLATE.format(
        gen=time.strftime("%Y-%m-%d %H:%M:%S"),
        n_active=len(active_rows),
        n_recent=len(ended_rows),
        active_table=_table(active_rows, cols_active),
        recent_table=_table(ended_rows, cols_ended),
        n_games=ng, n_snap=ns, n_evt=ne, n_rep=nr,
        cfg_path=html.escape(str(HERE / "config.json")),
        db_path=html.escape(str(HERE / "context" / "games.db")),
    )
    out = HERE / cfg["dashboard_html"]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_out, encoding="utf-8")
    print(f"[dashboard] wrote {out}  ({len(html_out)} chars)")

def _has_col(conn):
    return any(r[1]=="replay_path" for r in conn.execute("PRAGMA table_info(games)").fetchall())

if __name__ == "__main__":
    main()
