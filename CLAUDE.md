# Skald — Claude Code Context

## What this project is
Skald is an AI-driven content pipeline producing daily European payments 
and open banking briefings. It ingests free news feeds, generates drafts 
via the Claude API, routes them through a Gradio editorial dashboard for 
human review and editing, and publishes to vikingmedia.org.

Built as a portfolio demonstration of prompt engineering discipline, 
editorial feedback loops, and the transition from human-edited to 
automated publication.

## Directory structure
```
/beats/          Beat config YAML files (one per topic)
/prompts/        System and story prompts (versioned YAML, one dir per beat)
/ingester/       Feed fetching and normalisation
/generator/      Claude API calls and draft production
/dashboard/      Gradio editorial interface
/output/         Generated drafts (YAML) — committed to origin/main, not gitignored
/data/feedback/  Edit diffs and quality scores — committed to origin/main, not gitignored
/docs/           Project documentation
```

Note: the Hugo site source (`site/`) and Cloudflare Pages web root (`public/`) have moved
to the separate `skaldnick/vikingmedia-site` repo. Skald is pipeline-only.

## Key conventions
- Beat configs are YAML; schema defined in /beats/README.md
- Prompts are YAML files, never hardcoded in Python
- Every free-text field in a prompt's requested YAML output (headline, standfirst,
  editorial_note, sources, title, social_post — anywhere the model writes its own
  prose, not a fixed enum) must be specified as a literal block scalar (`|`), never
  a double-quoted string. Model-generated text routinely contains quote marks or
  colons, both of which break quoted/unquoted YAML scalars; block scalars need no
  escaping. See prompts/payments/story.yaml's output_format for the pattern.
- Writing convention (docs, style_rules.yaml, prose written on the user's behalf):
  no full stops in "eg"/"ie" or other abbreviations/initialisms, comma directly
  after "eg,"/"ie,", and double quotes (not single) for quoted example phrases.
  Normalised across prompts/payments/style_rules.yaml 2026-07-21.
- All Claude API calls go through generator/client.py — no direct API 
  calls elsewhere
- API keys via environment variables only (.env, never committed)
- /output/ and /data/feedback/ ARE committed to origin/main (not gitignored).
  The HF Space filesystem is ephemeral and there's no database, so git is the
  pipeline's only persistence layer: `generate.yml` commits each draft to
  `output/payments/YYYY-MM-DD.yaml`, and the dashboard's Content-API writes
  commit `data/feedback/YYYY-MM-DD.json` on every "Save feedback". Same pattern
  as `data/recently_covered.yaml` / `data/recently_rejected.yaml`. Don't
  reintroduce a gitignore entry for either path — it'll just fight the `git add`
  in `generate.yml` and the API writes will bypass it anyway.
- Commit messages: describe what was built and why, not just what changed
- The dashboard commits to origin/main via the GitHub Content API on its own
  schedule (drafts, feedback, recently_covered/rejected) — a local clone never
  sees these and can silently drift days behind. Run `bash tools/check_sync.sh`
  before starting local work; if it reports you're behind, `git pull --rebase
  origin main` rather than assuming a plain fast-forward will work.
- `.claude/` is gitignored except `.claude/skills/` (2026-07-29) — skills are
  shared project tooling (e.g. run-skald-dashboard below) and belong in the
  repo; `settings.local.json`, `launch.json`, and `worktrees/` stay machine-local
  and ignored. A skill's own `node_modules/`/`package-lock.json` are ignored via
  a `.claude/skills/**/` pattern rather than a per-skill entry, so this doesn't
  need updating as more skills are added.

## APIs and services
- Claude API (Anthropic) — content generation
- feedparser — RSS ingestion
- Gradio — dashboard UI (deployed to HuggingFace Spaces)
- Hugo — static site generation
- GitHub Actions — scheduling and deployment
- Cloudflare Pages — site hosting (vikingmedia.org)

## Docs
- /docs/brief.md — project purpose, audience, owner background
- /docs/decisions.md — architectural decisions and rationale
- /docs/sources.md — feed source registry for the payments beat

## Directory structure (additional)
```
/.github/        GitHub Actions workflows
/hf-readme.md    HuggingFace Space card (README synced to Space on deploy)
/.claude/skills/ Claude Code skills (tracked despite .claude/ being otherwise
                 gitignored — see "Key conventions"); run-skald-dashboard
                 drives the Gradio dashboard headlessly, see below
```

## HuggingFace Space sync
The HuggingFace Space is kept in sync automatically via `.github/workflows/sync-hf-space.yml`.
Any push to main that touches `dashboard/`, `generator/`, `ingester/`, `prompts/`, `beats/`,
`requirements.txt`, or `hf-readme.md` triggers the workflow, which clones the Space,
replaces its contents, and pushes. The workflow can also be triggered manually from the
Actions tab. There is no separate local `hf-space/` repo to maintain.

## Current status
Full cloud pipeline operational. First briefing published April 13, 2026.

### Cloud architecture
1. **GitHub Actions** (`generate.yml`) — scheduled 07:30 UK time, Mon–Fri (split into UTC-fixed BST/GMT cron lines since GitHub Actions cron has no timezone support), plus manual workflow_dispatch (used by the HuggingFace Space dashboard's "Trigger generation" button); runs `python -m generator.client`, which chains generate → style-check → verify → revise (see Components built below) before committing the draft to `output/payments/YYYY-MM-DD.yaml`.
2. **HuggingFace Space** (`nick385/skald`) — Gradio dashboard; checks for today's draft on load and reflects whether one is available, or the editor can click "Trigger generation" to dispatch the workflow manually, then "Load draft" once it completes. Reviews, edits, approves stories, and publishes to `site/content/briefings/YYYY-MM-DD.md` in `skaldnick/vikingmedia-site` via GitHub API commit.
3. **Cloudflare Pages** — watches `skaldnick/vikingmedia-site`; auto-deploys on push; runs `hugo --minify --source site`, serves from `public/`; live at vikingmedia.org/skald/

### Secrets and tokens
- `ANTHROPIC_API_KEY` — required in GitHub Actions only (not HF Space)
- `GITHUB_TOKEN` (PAT) — required in HF Space; needs `repo` and `workflow` scopes

### Components built
- ingester/fetcher.py — feed fetching, normalisation, recency filter (3 days), keyword filter; `resolve_display_sources()` cleans up Google Alert entries after keyword filtering (filtering still runs on the raw `Google Alert — <search term>` source names since that's what beats/payments_filters.yaml keys off): unwraps the `google.com/url` tracking redirect to the real article URL, strips the `<b>` tags Google bolds matched terms with, and derives a real publisher label (from a trailing ` - Publisher`/` | Publisher` in the title, falling back to the article URL's domain) to replace the `Google Alert — ...` placeholder. Only touches entries whose link is actually a Google redirect — regular feed entries (FCA, Finextra, PYMNTS, etc.) pass through untouched. `filter_already_covered()` drops entries whose title closely matches (difflib ratio ≥ 0.6) an already-covered or already-rejected headline, called from `generate_briefing()` before prompt assembly — a mechanical pre-filter for the case where an aggregator keeps yesterday's story inside the 3-day recency window; genuinely different articles about the same event under different wording still rely on the prompt-level "previously covered" instruction. `filter_keywords()` matches against HTML-stripped title+summary text (2026-07-27): Google Alerts sometimes bolds matched words individually (`<b>open</b> <b>banking</b>`), which silently defeated multi-word include keywords, and entities like `&amp;` broke keywords containing `&` — source *names* stay raw since the per-source filter configs key off them.
- generator/client.py — prompt assembly, Claude API call, draft output; loads style_rules.yaml and the full history of recently_covered.yaml and injects both into prompts; outputs a `title:` line at the top for the dashboard to parse; runs `resolve_display_sources()` after keyword filtering so both the prompt's `Source:` field and the final `sources` links use real publisher names/URLs, not Google Alert redirects; `generate_briefing()` runs `filter_already_covered()` (combined recently_covered + recently_rejected headlines) on entries before building the prompt. `_resolve_sources()` resolves each story's `source_ids` to real feed entries (guarantees a valid citation, not a correct one), dedupes a story's own `source_ids` against repeats (same id cited twice, or two ids resolving to the same URL) so its `sources` string never lists a duplicate link (confirmed 2026-07-17: a story cited the same source three times, producing a duplicate-source briefing that had to be fixed manually before this dedup existed), and also flags — via a pre-seeded `verification` warning — when two different stories in the same briefing resolve to the same cited URL, since that usually means the model reused a source_id from another story. `generate_briefing()` returns `(briefing, filtered_entries)` — the second element is the already-covered-filtered entry list actually shown to the model (and thus what its `source_ids` index into), needed by generator/revise.py to work out which entries are unused. `_covered_section()`/`_rejected_section()`/`_build_source_links()` were factored out of `build_user_prompt()`/`_resolve_sources()` so revise.py can reuse the same wording and resolution logic rather than re-deriving it. `generate_briefing()` raises if the response hit the max_tokens cap (2026-07-27) — YAML truncated mid-block-scalar usually still parses cleanly, so a capped response would otherwise save a briefing with stories or fields silently missing. `load_recently_rejected()`'s 28-day window is deliberately asymmetric with the covered list's no-cutoff: rejection is a time-bound judgment, coverage is permanent (see docstring).
- generator/verify.py — secondary fact-check pass run after generation, before saving the draft; re-checks each story against live web search (Haiku + `web_search` tool) for currency/figure accuracy, true source recency, and unsupported claims; also takes `recently_covered` and asks the model to flag (deterministically, no search needed) whether the story reports the same underlying event as an already-published one under a reworded headline — this is a secondary catch for cases where the generation-time "Previously covered" instruction in story.yaml doesn't stop the model selecting a same-day reword of yesterday's story, though this LLM-based check is itself probabilistic per run (confirmed 2026-07-17: it caught a duplicate on one generation attempt but missed a near-identical regeneration minutes later — see `filter_already_covered()` above for the mechanical layer added because of this). The recency check applies only to the single core event a story reports (the news its headline/standfirst are about) — it must not flag incidental background/context details mentioned elsewhere in the body (eg, a cited pilot's completion date, a competitor's rollout) purely for staleness, since those naturally predate the story and aren't the news being reported (confirmed 2026-07-20: a people-move story got flagged as stale over two unrelated background mentions before this scoping was added). The response JSON carries explicit `stale`/`duplicate` booleans (set when the recency/duplicate-coverage checks above fire) alongside `verified`/`warnings`, so `generator/revise.py` can act on them without pattern-matching warning text (added 2026-07-23). All checks attach to a single non-blocking `verification.warnings` list per story; `verify_briefing()` merges its warnings with any already on the story (eg, from `_resolve_sources()`'s shared-source check) rather than overwriting them. `verify_story()` retries up to 3 times with 5s/10s backoff on any failure (eg, transient API overload) before falling back to a non-blocking warning. Confirmed 2026-07-29: a same-day source wasn't indexed yet by web search, and rather than reporting that as inconclusive, the model asserted a specific contradicting claim (the story's "H1 2026" framing was "not yet available") built from unrelated search hits — which revise.py then treated as a confirmed correction and used to rewrite otherwise-correct text (see generator/revise.py note below). Items 2 and 3 of the fact-check prompt now distinguish a contradiction the search actually evidences from merely failing to locate/corroborate the cited source, require the latter to be prefixed `"Could not independently verify:"`, and call out that a search result describing an event as "scheduled" for a date that has already arrived doesn't prove the event hasn't happened
- generator/style_check.py — house-style compliance pass run after generation, parallel to verify.py but a pure text check (Haiku, no web search) against prompts/payments/style_rules.yaml; attaches `story["style_check"] = {compliant, warnings}`, quoting the offending text and naming the broken rule. Fails *open* (compliant, no warnings) on an API error, unlike verify.py's fail-closed — an unactionable "check failed to run" warning would otherwise waste a rewrite call in the revise pass below. Added 2026-07-23 because style_rules.yaml was only ever injected into the *generation* prompt, never independently checked afterward, so breaches kept reaching the editor. Cap raised 512→1024 and a max_tokens truncation now also fails open with a printed warning (2026-07-27) — warnings quote offending text so several breaches ran long, and truncated JSON otherwise surfaced as a bogus "could not be parsed" warning.
- generator/revise.py — fix/replace pass, runs after style_check and verify, before save; added 2026-07-23 so recurring style/factual issues get corrected automatically instead of left for the editor. For each story: if `verification` flags `stale` or `duplicate`, the story is dropped and `generate_replacement()` tries to draft a substitute from feed entries not cited by any other story in the same briefing (an Opus call scoped to `story.yaml`'s selection_criteria, told why the previous pick was rejected) — if no unused candidate exists or generation fails, the original story is kept with a `revision` note saying so rather than shrinking the briefing below its normal story count. Otherwise, if there are any actionable verification/style warnings, `revise_story()` (Opus) rewrites only what's needed to address them, using the correction already surfaced by the flagging pass — deliberately not re-verified with a second web search, to control cost and avoid a fix-verify loop. Every touched story gets `story["revision"] = {replaced, summary}`, a short list of what changed and why, which dashboard/app.py shows instead of the raw warning. `_actionable()` filters out warnings that are just pipeline failure markers ("failed to run", "could not be parsed") before handing them to the model, so a transient API hiccup in an earlier pass is never treated as a real issue to fix. Also filters out verify.py's "could not independently verify" warnings (2026-07-29) — inconclusive search, not a confirmed contradiction, so these reach the editor as a flag but no longer trigger an automatic rewrite (see generator/verify.py note above for the incident this fixed). The fix prompt itself also now refuses to substitute a specific fact (date, quarter, figure) based on a warning that only expresses uncertainty, as defence in depth for a hedged warning that slips through without the marker phrase. `generate_briefing()` in client.py now returns `(briefing, filtered_entries)` (not just `briefing`) specifically so this pass can compute which entries went unused — the filtered list's 1-based ordering is what the model's `source_ids` refer to, and that list previously wasn't handed back to the caller. `generate_replacement()` resolves the model's cited `source_ids` only against the unused candidates, not the full entry list (2026-07-27) — the model is *told* to cite candidate IDs only, but a cited already-used ID must fail resolution (falling back to keep-with-note) rather than recreate the duplicate-source problem this pass exists to fix; the now-redundant `entries` parameter was dropped from its signature.
- prompts/payments/system.yaml — voice, style, editorial stance
- prompts/payments/story.yaml — selection criteria, news recognition, output format; instructs Claude to produce a concise briefing title
- prompts/payments/style_rules.yaml — accumulated house style rules extracted from editorial feedback; injected into system prompt on every generation run. Each rule has a stable `id` (added 2026-07-29, backfilled 1-35 across all rules at the time) so a later proposal can name a specific rule to revise instead of only ever appending — see `supersedes` below. Only `date`/`rule` are read when building the prompt, so `id` is otherwise inert there.
- data/proposed_style_rules.yaml — queue of style rules Claude has proposed from recent editorial diffs/notes but which haven't yet been reviewed; populated automatically (see extract_learning.yml below), cleared once reviewed in the dashboard. A proposal may carry `supersedes: <id>` (2026-07-29) when it's meant to replace an existing rule's guidance rather than add a new one; promoting it in the dashboard overwrites that rule in place (same id, new date/text) instead of appending a second, possibly-conflicting entry. This exists because the append-only queue had no way to handle the editor changing their mind about, or finding a weakness in, a rule already in style_rules.yaml — that previously required a manual, unreviewed hand-edit that could drift from what extract_learning.py independently proposed from the same feedback.
- data/recently_covered.yaml — approved and published story headlines by date; injected into user prompt in full (no day-window cutoff — aggregators resurface old stories under fresh publish dates, so any recency cutoff would let duplicates slip through) to prevent repeat coverage; committed to repo so GitHub Actions can access it
- dashboard/app.py — Gradio editorial interface (trigger generation, load draft, edit, save feedback, approve/reject, publish, post to X); checks for today's draft via `app.load` when the page opens, so the header reflects real state (draft available / not yet generated) without waiting for a manual "Load draft" click — safe now that `ssr_mode=False` (see `app.launch`) keeps this off the SSR path, unlike the pre-May-20 crash this previously caused; pre-fills briefing title and social post from AI draft; Re-generate button regenerates both from approved stories and embeds the real briefing URL (not a placeholder); social post box shows character count (current / 280); Post to X is a separate button from Publish so the editor can wait for Cloudflare to deploy before tweeting; surfaces verification warnings as a `⚠️ Verification flagged` line in each story's editorial note, unless the story has a `revision` field (see generator/revise.py), in which case that field's `summary` is shown instead as `✓ Auto-corrected` lines — a fixed/replaced story shows what changed, not the now-stale complaint; "Proposed style rules" section loads data/proposed_style_rules.yaml into an editable textbox (one rule per line) — editing/deleting lines and clicking Save promotes the remainder into prompts/payments/style_rules.yaml and clears the pending queue. Re-generate also runs `_flag_unlisted_terms()`, a heuristic anti-hallucination check: capitalized words in the generated social post that don't appear in the approved headlines+standfirsts are surfaced as a `⚠️ Social post mentions terms not found...` warning (non-blocking, editor judgment call before posting). Matching is against headline+standfirst text (not headlines alone, which under-covers entity/company/country names trimmed out of the short headline) and treats country name/demonym pairs (`COUNTRY_DEMONYMS`, e.g. Greece/Greek) as equivalent. This check's status text is never persisted — no log of past warnings exists anywhere in the repo. Changes 2026-07-27: Hugo front matter is built with `yaml.dump`, never an f-string (a title containing a quote or colon broke hand-quoted front matter — same failure class as the block-scalar prompt convention); a same-day republish *merges* new approved headlines into the existing `recently_covered` entry (union, never removing — un-approving on republish must not delete a headline genuinely published earlier that day) and skips the commit when nothing's new; Publish auto-saves feedback via the shared `_save_feedback()` helper, but the Save feedback button is not redundant: `on_publish()` returns early — before calling `_save_feedback()` — both when no story is approved (nothing to publish) and when the GitHub write fails, so rejecting everything or hitting a publish error still needs a manual Save feedback click to record notes/decisions for that session; `⚠️ Style flagged` lines now surface `style_check` warnings alongside verification ones for stories with no `revision` field; empty `title:`/`social_post:` keys (YAML → None) no longer crash draft loading. Changes 2026-07-29: the "Proposed style rules" textbox now renders a pending line as `[date supersedes #N: "<current wording of rule N>"] <proposed rule>` when the proposal carries a `supersedes` id, so the editor can see what they'd be replacing without cross-referencing style_rules.yaml — the quoted snippet is just display context and is discarded again on save. `on_save_reviewed_rules()` parses that tag: a line with a valid `supersedes #N` overwrites rule N in place (same id, new date/text); everything else — including a line the editor types by hand rather than one that came from a proposal — is appended as a new rule with a freshly assigned id. A `supersedes` id that no longer matches any rule (already replaced, or hallucinated) falls back to being appended as a new rule rather than silently dropped or applied to the wrong entry. Changes 2026-07-29: added a "Settings" tab alongside the existing page (now "Today"), wrapping both in `gr.Tabs` — a pure layout change, existing event bindings untouched. Settings exposes system.yaml, story.yaml, style_rules.yaml, beats/payments.yaml, and beats/payments_filters.yaml as raw-text editors via new `_read_repo_text()`/`_write_repo_text()` helpers and `on_load_setting()`/`on_save_setting()` handlers. Unlike the list-based helpers (`_read_repo_yaml_list`/`_write_repo_yaml_list`, which round-trip through `yaml.safe_load`/`yaml.dump`), these read/write the file's raw text verbatim — `yaml.safe_load` is used only to validate before saving, never to reconstruct the file — because a dump/reload cycle reformats away the literal block scalars the prompts and style rules depend on (confirmed: this already happened once, to style_rules.yaml, via the dashboard's own proposed-rules write path). Verified end-to-end in a real browser via the new `.claude/skills/run-skald-dashboard/` skill (see below).
- dashboard/github_api.py — GitHub API helpers (read/write files, dispatch workflows); dashboard uses this when GITHUB_TOKEN set, local filesystem otherwise. Uses two repo env vars: GITHUB_REPO (vikingmedia-site, for publishing briefings) and GITHUB_PIPELINE_REPO (skald, for workflow dispatch and reading drafts)
- beats/payments.yaml — source config (11 sources: regulatory, Google Alerts, trade press)
- beats/payments_filters.yaml — keyword filter config (global + per-source include/exclude, passthrough)
- .github/workflows/generate.yml — scheduled 07:30 UK time Mon–Fri (two cron lines for BST/GMT, see workflow comments) plus manual workflow_dispatch
- .github/workflows/sync-hf-space.yml — syncs dashboard and source files to HuggingFace Space on push to main; also triggerable manually
- .github/workflows/extract_learning.yml — runs on every push to main touching data/feedback/ (also triggerable manually); diffs the push to find which feedback dates changed and runs tools/extract_learning.py --date for each, committing any newly proposed rules to data/proposed_style_rules.yaml. Guards against the zero SHA `github.event.before` carries on branch-create/force-push, and `--diff-filter=d` excludes deleted feedback files (2026-07-27)
- tools/fetch_raw.py — fetch and cache raw feed snapshot for offline filter testing
- tools/test_filters.py — test filter configs against cached snapshots; shows per-source pass/cut
- tools/extract_learning.py — calls Claude to propose style rules from editorial diffs *and* the editor's own notes field (notes are treated as an authoritative statement of the rule, not just something to infer from a diff), then appends new proposals (deduped against accepted and already-pending rules) to data/proposed_style_rules.yaml for review in the dashboard. Runs automatically via extract_learning.yml; can also be run locally. Does not touch recently_covered.yaml/recently_rejected.yaml — those are updated by the dashboard on publish. Changes 2026-07-27: the prompt requests block-scalar `rule:` fields per the prompts convention (a rule containing a quote/colon previously broke the quoted-YAML output and lost the whole batch; parsed rules are `.strip()`ed since block scalars carry a trailing newline); notes on *rejected* stories are now included, tagged as likely story-selection rules (diffs still come only from approved stories — edits to a story that was rejected anyway aren't reliable style signal). Changes 2026-07-29: existing rules are now shown to Claude with their id (`- [12] <rule text>`), and the prompt asks it to attach `supersedes: <id>` when a diff/note reveals the editor narrowing, widening, reversing, or replacing an existing rule's guidance, rather than treating that as either a fresh unrelated rule or a duplicate to ignore. `append_proposed_rules()` validates a proposed `supersedes` id against the current accepted rules before queuing it (an id that doesn't exist — hallucinated, or already superseded — is dropped, so the proposal falls back to a plain new-rule addition instead of pointing at the wrong entry, or nothing, once promoted).
- tools/check_sync.sh — fetches origin and reports how many commits local is behind/ahead; run before starting local work, since the dashboard pushes to origin/main independently of any local clone
- .claude/skills/run-skald-dashboard/ — Claude Code skill for launching and driving the Gradio dashboard headlessly (no `chromium-cli` or xvfb needed; Chromium runs headless by default). `driver.mjs` is a Playwright REPL (`start`/`tab`/`click-nth`/`ss`/`text`/`errors`/`stop`, fed via stdin) that spawns `python3 -m dashboard.app` with `GITHUB_TOKEN` stripped from the child env — forcing the local-filesystem fallback in dashboard/github_api.py instead of committing to the real repo — then opens a headless page against it. Piped stdin delivers every command's `line` event before an earlier async handler (like `start`, which takes a couple of seconds) finishes, so commands are chained onto a promise queue rather than relying on readline to serialize them; without that fix, `ss` right after `start` screenshots a page that hasn't loaded yet. Has its own `package.json` (Playwright) — `node_modules/`/`package-lock.json` stay untracked (see "Key conventions").

### Post-session workflow
Style rule extraction is now automatic: saving feedback in the dashboard commits to
data/feedback/, which triggers extract_learning.yml to propose new rules into
data/proposed_style_rules.yaml. The only manual step is reviewing them: open the
dashboard's "Proposed style rules" section, click **Load proposed rules**, edit or
delete lines you don't want, and click **Save reviewed rules** — accepted rules are
committed to prompts/payments/style_rules.yaml and the pending queue is cleared.

### Known minor issues (from 2026-07-27 code review, judged not worth fixing)
No URL-dedup of entries across feeds before prompting; X char budget assumes the
literal 45-char URL though t.co counts any URL as 23; `%-d` strftime is
Linux/macOS-only; generate.yml has no concurrency group (manual dispatch can race the
schedule); on_regenerate has no try/except around its two API calls. The gradio line
in requirements.txt stays deliberately unpinned — the Space's Gradio version is
governed by `sdk_version` in hf-readme.md (currently 6.12.0); a requirements.txt pin
conflicts with HF's own install and broke the build on 2026-05-21 (pinned in 4d5875e,
reverted in 99d11d8). The briefing title has no feedback-diff path (2026-07-27):
`_save_feedback()` in dashboard/app.py only tracks headline/standfirst/body/sources
per story, so an editor's title correction never reaches extract_learning.py and
can't become a learned style rule automatically — noted, not yet implemented.

### Next priorities
- Design TL;DR/summary product — concise daily digest and/or teaser email, separate from the full briefing
- HF Space dashboard redesign — multi-tab layout via `gr.Tab` inside `gr.Blocks`; no separate landing page needed:
  - **Today** tab: existing briefing workflow, unchanged — done
  - **Settings** tab: raw YAML editors for system prompt, story prompt, style rules, sources, and keyword filters — **done 2026-07-29**, see dashboard/app.py above
  - **Briefings** tab: list published briefings, click to view (read-only initially; editing deferred) — **not yet built**, the only remaining piece
- Independent reporting / contextual research — pre-draft step where Claude identifies claims needing verification, queries a search API, and incorporates results before writing; even a lightweight version (fetching older relevant sources for context) would improve story quality
