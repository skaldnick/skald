// REPL driver for the Skald Gradio editorial dashboard (dashboard/app.py).
// Run under plain Node (no xvfb needed — Chromium runs headless by default).
// Designed for agents: wrap in tmux, send-keys commands, capture-pane output.
//
// `start` launches the Python dashboard as a child process with GITHUB_TOKEN
// unset (so it falls back to local filesystem reads/writes instead of
// committing to the real GitHub repo) and opens a headless Chromium page
// against it. Everything after that is ordinary page automation.
import { chromium } from 'playwright';
import { spawn } from 'node:child_process';
import * as readline from 'node:readline';
import * as fs from 'node:fs';
import * as path from 'node:path';

const REPO_ROOT = path.resolve(import.meta.dirname, '../../..');
const PORT = process.env.SKALD_DASHBOARD_PORT || '7860';
const URL = `http://127.0.0.1:${PORT}`;
const SHOT_DIR = process.env.SCREENSHOT_DIR || '/tmp/shots';
fs.mkdirSync(SHOT_DIR, { recursive: true });

let serverProc = null;
let browser = null;
let page = null;
const pageErrors = [];

function waitForServer(timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const tryOnce = () => {
      fetch(URL).then(() => resolve()).catch(() => {
        if (Date.now() > deadline) reject(new Error('server did not come up in time'));
        else setTimeout(tryOnce, 500);
      });
    };
    tryOnce();
  });
}

const COMMANDS = {
  // Launch the Python dashboard (GITHUB_TOKEN stripped) and a headless
  // Chromium page pointed at it. Safe to call once per session.
  async start() {
    if (serverProc) return console.log('server already running');
    const env = { ...process.env };
    delete env.GITHUB_TOKEN; // force local-filesystem fallback, not a real GitHub write
    serverProc = spawn('python3', ['-m', 'dashboard.app'], {
      cwd: REPO_ROOT,
      env,
      stdio: ['ignore', fs.openSync('/tmp/skald-dashboard.log', 'a'), fs.openSync('/tmp/skald-dashboard.log', 'a')],
    });
    console.log('spawned dashboard, pid', serverProc.pid, '— waiting for', URL);
    try {
      await waitForServer();
    } catch (e) {
      console.log('ERROR:', e.message, '— check /tmp/skald-dashboard.log');
      return;
    }
    browser = await chromium.launch();
    page = await browser.newPage({ viewport: { width: 1400, height: 1200 } });
    page.on('pageerror', (e) => pageErrors.push(String(e)));
    page.on('console', (msg) => { if (msg.type() === 'error') pageErrors.push(msg.text()); });
    await page.goto(URL, { waitUntil: 'load' });
    await page.waitForSelector('text=Skald — Editorial Dashboard', { timeout: 20_000 });
    console.log('started. page loaded at', URL);
  },

  async ss(name) {
    if (!page) return console.log('ERROR: start first');
    const f = path.join(SHOT_DIR, (name || `ss-${Date.now()}`) + '.png');
    await page.screenshot({ path: f, fullPage: true });
    console.log('screenshot:', f);
  },

  // Switch tabs by their visible Gradio tab label, e.g. "Today", "Settings".
  async tab(name) {
    if (!page) return console.log('ERROR: start first');
    await page.getByRole('tab', { name }).click();
    console.log('switched to tab:', name);
  },

  // Click the Nth (1-based) button whose visible text matches exactly —
  // Gradio reuses generic labels ("Load", "Save") across repeated groups
  // (one per Settings file), so index is how you pick a specific one.
  async 'click-nth'(args) {
    if (!page) return console.log('ERROR: start first');
    const [text, nStr] = args.split(/\s+/);
    const n = parseInt(nStr || '1', 10);
    const buttons = await page.getByRole('button', { name: text, exact: true }).all();
    if (buttons.length < n) return console.log(`ERROR: only ${buttons.length} button(s) named "${text}"`);
    await buttons[n - 1].click();
    console.log(`clicked button "${text}" #${n} (of ${buttons.length})`);
  },

  async click(text) {
    if (!page) return console.log('ERROR: start first');
    await page.getByRole('button', { name: text }).first().click();
    console.log('clicked:', text);
  },

  async wait(selector) {
    if (!page) return console.log('ERROR: start first');
    try { await page.waitForSelector(selector, { timeout: 10_000 }); console.log('found:', selector); }
    catch { console.log('TIMEOUT:', selector); }
  },

  async text(selector) {
    if (!page) return console.log('ERROR: start first');
    console.log(await page.evaluate(
      (s) => (s ? document.querySelector(s) : document.body)?.innerText ?? '(null)',
      selector || null,
    ));
  },

  errors() {
    console.log(pageErrors.length ? JSON.stringify(pageErrors) : 'no console/page errors observed');
  },

  async stop() {
    if (browser) await browser.close().catch(() => {});
    if (serverProc) serverProc.kill();
    browser = null; page = null; serverProc = null;
    console.log('stopped');
  },

  help() { console.log('commands:', Object.keys(COMMANDS).join(', ')); },
};

const stdin = fs.createReadStream(null, { fd: fs.openSync('/dev/stdin', 'r') });
const rl = readline.createInterface({ input: stdin, output: process.stdout, prompt: 'driver> ' });

// Piped stdin (a heredoc, or send-keys firing in quick succession) delivers
// every buffered line's 'line' event before an earlier async handler
// finishes — readline does not serialize on its own. Chain each command
// onto a queue so "start" (which takes several seconds) always completes
// before the next command runs, even when every line arrives at once.
let queue = Promise.resolve();
rl.on('line', (line) => {
  queue = queue.then(async () => {
    const [cmd, ...rest] = line.trim().split(/\s+/);
    if (!cmd) return rl.prompt();
    const fn = COMMANDS[cmd];
    if (!fn) { console.log('unknown:', cmd, '— try: help'); return rl.prompt(); }
    try { await fn(rest.join(' ')); } catch (e) { console.log('ERROR:', e.message); }
    if (cmd === 'stop') { rl.close(); process.exit(0); return; }
    rl.prompt();
  });
});
rl.on('close', async () => { await queue; await COMMANDS.stop(); process.exit(0); });

console.log('skald-dashboard driver — "help" for commands, "start" to launch');
rl.prompt();
