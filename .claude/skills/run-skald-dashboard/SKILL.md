---
name: run-skald-dashboard
description: Build, run, and drive the Skald editorial Gradio dashboard (dashboard/app.py). Use when asked to start the dashboard, take a screenshot of it, test a dashboard change, or interact with its Today/Settings UI.
---

The Skald dashboard is a Gradio 6 web app (`dashboard/app.py`) served on
`http://127.0.0.1:7860`. For agent/automated use, drive it via the Playwright
REPL at `.claude/skills/run-skald-dashboard/driver.mjs` — no `chromium-cli` or
xvfb needed; Chromium runs headless by default on both Linux and macOS. The
driver launches the Python server itself, so no separate step is required.

All paths below are relative to the repo root (`skald/`).

## Prerequisites

```bash
# Python deps (repo already has a venv/ at root — activate it, or use your own)
source venv/bin/activate
pip install -r requirements.txt

# Node deps for the driver, + its own Chromium (shares Playwright's global
# browser cache — a no-op if some other project already installed it)
cd .claude/skills/run-skald-dashboard
npm install
npx playwright install chromium
cd ../../..
```

Env vars:

```bash
# required in .env at repo root — dashboard imports anthropic.Anthropic() at
# call time for generation/regeneration actions
ANTHROPIC_API_KEY=...

# must NOT be set for a local run — its presence makes dashboard/github_api.py
# write real commits to the GitHub repo instead of the local filesystem. The
# driver's `start` command strips it from the child process env regardless,
# but don't export it in your own shell before running the human path below.
# GITHUB_TOKEN=
```

## Build

No build step — Gradio serves `dashboard/app.py` directly.

## Run (agent path)

The driver launches the dashboard for you — don't start it separately. Pipe
commands to it over stdin:

```bash
node .claude/skills/run-skald-dashboard/driver.mjs <<'EOF'
start
ss 01-today
tab Settings
ss 02-settings
click-nth Load 3
ss 03-style-rules-loaded
errors
stop
EOF
```

Verified output (pid will differ run to run):

```
skald-dashboard driver — "help" for commands, "start" to launch
driver> spawned dashboard, pid 67800 — waiting for http://127.0.0.1:7860
started. page loaded at http://127.0.0.1:7860
driver> screenshot: /tmp/shots/01-today.png
driver> switched to tab: Settings
driver> screenshot: /tmp/shots/02-settings.png
driver> clicked button "Load" #3 (of 5)
driver> screenshot: /tmp/shots/03-style-rules-loaded.png
driver> no console/page errors observed
driver> stopped
```

For iterative use (issue one command, look at the result, issue the next)
instead of a fixed heredoc, wrap it in tmux if available:

```bash
tmux new-session -d -s dash -x 200 -y 50
tmux send-keys -t dash 'node .claude/skills/run-skald-dashboard/driver.mjs' Enter
timeout 10 bash -c 'until tmux capture-pane -t dash -p | grep -q "driver>"; do sleep 0.2; done'
tmux send-keys -t dash 'start' Enter
timeout 30 bash -c 'until tmux capture-pane -t dash -p | grep -q "started\."; do sleep 0.2; done'
tmux send-keys -t dash 'ss landing' Enter
tmux capture-pane -t dash -p
```

tmux was not available in the environment this skill was authored in — the
stdin-heredoc form above was verified instead and works everywhere Node does.

Screenshots land in `/tmp/shots/` (override: `SCREENSHOT_DIR`). Dashboard
server logs go to `/tmp/skald-dashboard.log`.

### Commands

| command | what it does |
|---|---|
| `start` | spawn `python3 -m dashboard.app` (GITHUB_TOKEN stripped) and open a headless Chromium page against it |
| `ss [name]` | full-page screenshot → `/tmp/shots/<name>.png` |
| `tab <label>` | switch Gradio tab by visible label, e.g. `tab Settings`, `tab Today` |
| `click <text>` | click the first button with this visible text |
| `click-nth <text> <n>` | click the Nth (1-based) button with this exact text — needed because the Settings tab repeats "Load"/"Save" once per file |
| `wait <css-selector>` | wait up to 10s for a selector |
| `text [css-selector]` | print `innerText` of a selector (or `document.body`) |
| `errors` | print any console/page errors observed since `start` |
| `stop` | close the browser and kill the dashboard process |

## Run (human path)

```bash
source venv/bin/activate
python3 -m dashboard.app   # serves http://127.0.0.1:7860 — Ctrl-C to stop
```

Open `http://127.0.0.1:7860` in a real browser. Useless in a headless
container — use the agent path above there.

## Gotchas

- **Piped stdin fires all `line` events before earlier async commands
  finish.** A heredoc delivers every line to Node's readline at once;
  without explicit serialization, `ss 01-today` right after `start` would
  run against a page that hasn't loaded yet (`start` takes ~1-2s: spawn +
  poll port + launch Chromium + goto). The driver chains each command onto
  a promise queue for this reason — do the same if you extend it, rather
  than assuming readline processes lines one at a time on its own.
- **Gradio reuses generic button labels across repeated groups.** The
  Settings tab has one "Load" and one "Save" button per file (5 files) —
  `page.getByRole('button', { name: 'Load' })` matches all 5. Use
  `click-nth <text> <n>` and count from the file's position in
  `SETTINGS_FILES` in `dashboard/app.py` (System prompt, Story prompt,
  Style rules, Sources, Keyword filters = 1..5).
- **`GITHUB_TOKEN` silently changes what a save does.** If it's set in your
  shell's environment, `dashboard/github_api.available()` returns true and
  every write (Settings Save, feedback, publish) becomes a real GitHub API
  commit against the configured repo, not a local file write. The driver's
  `start` strips it from the spawned process regardless of your shell.

## Troubleshooting

- **`ERROR: start first` on every subsequent command:** `start` hadn't
  finished before later commands ran — usually means the queue fix above
  was reverted, or you're driving the process some other way that doesn't
  await `start`'s promise before sending the next command.
- **Port 7860 already in use / driver hangs on `start`:** a previous run's
  server is still up. `lsof -ti:7860 -sTCP:LISTEN | xargs -r kill`, then
  retry.
- **Blank/error screenshot:** check `/tmp/skald-dashboard.log` — most
  commonly a missing `ANTHROPIC_API_KEY` in `.env`, or Python deps not
  installed in the active venv.
