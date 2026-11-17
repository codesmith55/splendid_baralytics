#!/usr/bin/env python3
"""Scan for NEW games that just appeared and match user-watchlist criteria.
Dispatches to configured channels: toast (Windows), discord webhook, file.

Called by lobby_monitor after each pass, or run independently on the same DB.
"""
from __future__ import annotations
import json, sqlite3, subprocess, sys, time, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from watchers_schema import connect
from config import load as load_cfg

# per-run marker file so we don't re-alert on the same games
STATE_PATH = Path(__file__).resolve().parent / "context" / "alerter_state.json"

def _load_state():
    if STATE_PATH.exists():
        try: return json.loads(STATE_PATH.read_text())
        except Exception: pass
    return {"alerted_ids": []}

def _save_state(s):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(s))

def _dispatch(channel: str, subject: str, body: str):
    try:
        if channel == "toast":
            _toast(subject, body)
        elif channel.startswith("discord:"):
            _discord_webhook(channel[len("discord:"):], subject, body)
        elif channel.startswith("file:"):
            path = channel[len("file:"):]
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {subject}\n  {body}\n")
        else:
            print(f"[alerter] unknown channel: {channel}")
    except Exception as e:
        print(f"[alerter] dispatch error on {channel}: {e}")

def _toast(title: str, body: str):
    """Windows 10/11 toast via PowerShell BurntToast if available, else msg."""
    ps = f"""
$ErrorActionPreference = 'SilentlyContinue'
if (Get-Module -ListAvailable BurntToast) {{
    Import-Module BurntToast
    New-BurntToastNotification -Text '{title.replace("'", "''")}', '{body.replace("'", "''")}'
}} else {{
    # fallback: Windows Forms popup
    [void][System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms')
    [System.Windows.Forms.MessageBox]::Show('{body.replace("'", "''")}', '{title.replace("'", "''")}')
}}
"""
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], timeout=10, check=False)

def _discord_webhook(url: str, subject: str, body: str):
    payload = json.dumps({"content": f"**{subject}**\n{body}"}).encode()
    req = urllib.request.Request(url, data=payload,
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10).read()

def main():
    cfg = load_cfg()
    if not cfg["alerts"]["enabled"]:
        print("[alerter] disabled in config"); return

    conn = connect()
    state = _load_state()
    already = set(state.get("alerted_ids", []))
    watchlist = [u.lower() for u in cfg["alerts"]["watchlist_usernames"]]

    new_games = conn.execute("""SELECT battle_id, title, map_name, founder,
                                       initial_avg_os, peak_avg_os, first_seen
                                FROM games WHERE watcher_status='running'
                                ORDER BY first_seen DESC LIMIT 100""").fetchall()

    fired = 0
    for bid, title, m, f, ios, pos, fs in new_games:
        if bid in already: continue
        # only match if watchlist empty (alert all) OR any player matches
        matched_users = []
        if watchlist:
            row = conn.execute("""SELECT players_json FROM snapshots
                                  WHERE battle_id=? ORDER BY ts DESC LIMIT 1""",
                              (bid,)).fetchone()
            if row:
                try: players = json.loads(row[0])
                except Exception: players = []
                names = [p.get("username", "").lower() for p in players if isinstance(p, dict)]
                for u in watchlist:
                    matched_users += [n for n in names if u in n]
        if watchlist and not matched_users: continue
        subject = f"BAR #{bid}: {title[:40]}"
        body = (f"map: {m}  |  founder: {f}\n"
                f"avg OS: {ios:.1f}  peak: {pos:.1f}\n"
                f"first seen: {time.strftime('%H:%M:%S', time.localtime(fs))}")
        if matched_users: body += f"\nwatchlist match: {sorted(set(matched_users))}"
        for ch in cfg["alerts"]["channels"]:
            _dispatch(ch, subject, body)
        already.add(bid); fired += 1

    state["alerted_ids"] = list(already)[-1000:]
    _save_state(state)
    print(f"[alerter] fired: {fired}")

if __name__ == "__main__":
    main()
