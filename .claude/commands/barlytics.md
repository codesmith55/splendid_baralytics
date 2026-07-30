Start the BAR live analytics server and enter passive monitoring mode.

1. From `splendid_baralytics/live/`, run `python ai_processes/capabilities.py` to print the capability list.
2. Start `bar_analytic_server.py --no-exit` in the background from `splendid_baralytics/live/`.
3. Set up a persistent Monitor on the server output file, filtering for lines matching: `game|session|tailing|state|team|error|Error|exit|new|end|start|waiting|watch`
4. Adopt passive observer mode for the rest of the session:
   - Report server events (game start, session info, game end) as brief notifications.
   - Do not open the browser, modify files, or take any autonomous action.
   - Only act if the user explicitly asks.

The dashboard will be live at http://localhost:8787 once a game is active.
