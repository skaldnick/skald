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
1. **GitHub Actions** (`generate.yml`) — scheduled 07:30 UK time, Mon–Fri (split into UTC-fixed BST/GMT cron lines since GitHub Actions cron has no timezone support), plus manual workflow_dispatch (used by the HuggingFace Space dashboard's "Trigger generation" button); runs `python -m generator.client`, commits draft to `output/payments/YYYY-MM-DD.yaml`.
2. **HuggingFace Space** (`nick385/skald`) — Gradio dashboard; checks for today's draft on load and reflects whether one is available, or the editor can click "Trigger generation" to dispatch the workflow manually, then "Load draft" once it completes. Reviews, edits, approves stories, and publishes to `site/content/briefings/YYYY-MM-DD.md` in `skaldnick/vikingmedia-site` via GitHub API commit.
3. **Cloudflare Pages** — watches `skaldnick/vikingmedia-site`; auto-deploys on push; runs `hugo --minify --source site`, serves from `public/`; live at vikingmedia.org/skald/

### Secrets and tokens
- `ANTHROPIC_API_KEY` — required in GitHub Actions only (not HF Space)
- `GITHUB_TOKEN` (PAT) — required in HF Space; needs `repo` and `workflow` scopes

### Components built
- ingester/fetcher.py — feed fetching, normalisation, recency filter (3 days), keyword filter; `resolve_display_sources()` cleans up Google Alert entries after keyword filtering (filtering still runs on the raw `Google Alert — <search term>` source names since that's what beats/payments_filters.yaml keys off): unwraps the `google.com/url` tracking redirect to the real article URL, strips the `<b>` tags Google bolds matched terms with, and derives a real publisher label (from a trailing ` - Publisher`/` | Publisher` in the title, falling back to the article URL's domain) to replace the `Google Alert — ...` placeholder. Only touches entries whose link is actually a Google redirect — regular feed entries (FCA, Finextra, PYMNTS, etc.) pass through untouched. `filter_already_covered()` drops entries whose title closely matches (difflib ratio ≥ 0.6) an already-covered or already-rejected headline, called from `generate_briefing()` before prompt assembly — a mechanical pre-filter for the case where an aggregator keeps yesterday's story inside the 3-day recency window; genuinely different articles about the same event under different wording still rely on the prompt-level "previously covered" instruction.
- generator/client.py — prompt assembly, Claude API call, draft output; loads style_rules.yaml and the full history of recently_covered.yaml and injects both into prompts; outputs a `title:` line at the top for the dashboard to parse; runs `resolve_display_sources()` after keyword filtering so both the prompt's `Source:` field and the final `sources` links use real publisher names/URLs, not Google Alert redirects; `generate_briefing()` runs `filter_already_covered()` (combined recently_covered + recently_rejected headlines) on entries before building the prompt. `_resolve_sources()` resolves each story's `source_ids` to real feed entries (guarantees a valid citation, not a correct one), dedupes a story's own `source_ids` against repeats (same id cited twice, or two ids resolving to the same URL) so its `sources` string never lists a duplicate link (confirmed 2026-07-17: a story cited the same source three times, producing a duplicate-source briefing that had to be fixed manually before this dedup existed), and also flags — via a pre-seeded `verification` warning — when two different stories in the same briefing resolve to the same cited URL, since that usually means the model reused a source_id from another story.
- generator/verify.py — secondary fact-check pass run after generation, before saving the draft; re-checks each story against live web search (Haiku + `web_search` tool) for currency/figure accuracy, true source recency, and unsupported claims; also takes `recently_covered` and asks the model to flag (deterministically, no search needed) whether the story reports the same underlying event as an already-published one under a reworded headline — this is a secondary catch for cases where the generation-time "Previously covered" instruction in story.yaml doesn't stop the model selecting a same-day reword of yesterday's story, though this LLM-based check is itself probabilistic per run (confirmed 2026-07-17: it caught a duplicate on one generation attempt but missed a near-identical regeneration minutes later — see `filter_already_covered()` above for the mechanical layer added because of this). The recency check applies only to the single core event a story reports (the news its headline/standfirst are about) — it must not flag incidental background/context details mentioned elsewhere in the body (eg, a cited pilot's completion date, a competitor's rollout) purely for staleness, since those naturally predate the story and aren't the news being reported (confirmed 2026-07-20: a people-move story got flagged as stale over two unrelated background mentions before this scoping was added). All checks attach to a single non-blocking `verification.warnings` list per story; `verify_briefing()` merges its warnings with any already on the story (eg, from `_resolve_sources()`'s shared-source check) rather than overwriting them. `verify_story()` retries up to 3 times with 5s/10s backoff on any failure (eg, transient API overload) before falling back to a non-blocking warning
- prompts/payments/system.yaml — voice, style, editorial stance
- prompts/payments/story.yaml — selection criteria, news recognition, output format; instructs Claude to produce a concise briefing title
- prompts/payments/style_rules.yaml — accumulated house style rules extracted from editorial feedback; injected into system prompt on every generation run
- data/proposed_style_rules.yaml — queue of style rules Claude has proposed from recent editorial diffs/notes but which haven't yet been reviewed; populated automatically (see extract_learning.yml below), cleared once reviewed in the dashboard
- data/recently_covered.yaml — approved and published story headlines by date; injected into user prompt in full (no day-window cutoff — aggregators resurface old stories under fresh publish dates, so any recency cutoff would let duplicates slip through) to prevent repeat coverage; committed to repo so GitHub Actions can access it
- dashboard/app.py — Gradio editorial interface (trigger generation, load draft, edit, save feedback, approve/reject, publish, post to X); checks for today's draft via `app.load` when the page opens, so the header reflects real state (draft available / not yet generated) without waiting for a manual "Load draft" click — safe now that `ssr_mode=False` (see `app.launch`) keeps this off the SSR path, unlike the pre-May-20 crash this previously caused; pre-fills briefing title and social post from AI draft; Re-generate button regenerates both from approved stories and embeds the real briefing URL (not a placeholder); social post box shows character count (current / 280); Post to X is a separate button from Publish so the editor can wait for Cloudflare to deploy before tweeting; surfaces verification warnings as a `⚠️ Verification flagged` line in each story's editorial note; "Proposed style rules" section loads data/proposed_style_rules.yaml into an editable textbox (one rule per line) — editing/deleting lines and clicking Save promotes the remainder into prompts/payments/style_rules.yaml and clears the pending queue. Re-generate also runs `_flag_unlisted_terms()`, a heuristic anti-hallucination check: capitalized words in the generated social post that don't appear in the approved headlines+standfirsts are surfaced as a `⚠️ Social post mentions terms not found...` warning (non-blocking, editor judgment call before posting). Matching is against headline+standfirst text (not headlines alone, which under-covers entity/company/country names trimmed out of the short headline) and treats country name/demonym pairs (`COUNTRY_DEMONYMS`, e.g. Greece/Greek) as equivalent. This check's status text is never persisted — no log of past warnings exists anywhere in the repo.
- dashboard/github_api.py — GitHub API helpers (read/write files, dispatch workflows); dashboard uses this when GITHUB_TOKEN set, local filesystem otherwise. Uses two repo env vars: GITHUB_REPO (vikingmedia-site, for publishing briefings) and GITHUB_PIPELINE_REPO (skald, for workflow dispatch and reading drafts)
- beats/payments.yaml — source config (11 sources: regulatory, Google Alerts, trade press)
- beats/payments_filters.yaml — keyword filter config (global + per-source include/exclude, passthrough)
- .github/workflows/generate.yml — scheduled 07:30 UK time Mon–Fri (two cron lines for BST/GMT, see workflow comments) plus manual workflow_dispatch
- .github/workflows/sync-hf-space.yml — syncs dashboard and source files to HuggingFace Space on push to main; also triggerable manually
- .github/workflows/extract_learning.yml — runs on every push to main touching data/feedback/ (also triggerable manually); diffs the push to find which feedback dates changed and runs tools/extract_learning.py --date for each, committing any newly proposed rules to data/proposed_style_rules.yaml
- tools/fetch_raw.py — fetch and cache raw feed snapshot for offline filter testing
- tools/test_filters.py — test filter configs against cached snapshots; shows per-source pass/cut
- tools/extract_learning.py — calls Claude to propose style rules from editorial diffs *and* the editor's own notes field (notes are treated as an authoritative statement of the rule, not just something to infer from a diff), then appends new proposals (deduped against accepted and already-pending rules) to data/proposed_style_rules.yaml for review in the dashboard. Runs automatically via extract_learning.yml; can also be run locally. Does not touch recently_covered.yaml/recently_rejected.yaml — those are updated by the dashboard on publish.
- tools/check_sync.sh — fetches origin and reports how many commits local is behind/ahead; run before starting local work, since the dashboard pushes to origin/main independently of any local clone

### Post-session workflow
Style rule extraction is now automatic: saving feedback in the dashboard commits to
data/feedback/, which triggers extract_learning.yml to propose new rules into
data/proposed_style_rules.yaml. The only manual step is reviewing them: open the
dashboard's "Proposed style rules" section, click **Load proposed rules**, edit or
delete lines you don't want, and click **Save reviewed rules** — accepted rules are
committed to prompts/payments/style_rules.yaml and the pending queue is cleared.

### Next priorities
- Design TL;DR/summary product — concise daily digest and/or teaser email, separate from the full briefing
- HF Space dashboard redesign — multi-tab layout:
  - **Today** tab: existing briefing workflow, unchanged
  - **Briefings** tab: list published briefings, click to view (read-only initially; editing deferred)
  - **Settings** tab: raw YAML editors for system prompt, story prompt, style rules, sources, and keyword filters — each as a textarea with a Save button
  - Navigation via `gr.Tab` inside `gr.Blocks`; no separate landing page needed
- Independent reporting / contextual research — pre-draft step where Claude identifies claims needing verification, queries a search API, and incorporates results before writing; even a lightweight version (fetching older relevant sources for context) would improve story quality
