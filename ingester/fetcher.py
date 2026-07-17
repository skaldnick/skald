import difflib
import html
import re

import feedparser
import yaml
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs


def load_beat(beat_name: str) -> dict:
    """Load a beat config from /beats/{beat_name}.yaml"""
    beat_path = Path(__file__).parent.parent / "beats" / f"{beat_name}.yaml"
    with open(beat_path) as f:
        return yaml.safe_load(f)


def fetch_feed(url: str, source_name: str) -> list[dict]:
    """Fetch and normalise entries from a single RSS/Atom feed."""
    try:
        feed = feedparser.parse(url)
        entries = []
        for entry in feed.entries:
            published_parsed = entry.get("published_parsed")
            if published_parsed:
                published_dt = datetime(*published_parsed[:6], tzinfo=timezone.utc)
            else:
                published_dt = None
            entries.append({
                "source": source_name,
                "title": entry.get("title", "").strip(),
                "url": entry.get("link", ""),
                "summary": entry.get("summary", "").strip(),
                "published": entry.get("published", ""),
                "published_dt": published_dt,
            })
        return entries
    except Exception as e:
        print(f"Error fetching {source_name}: {e}")
        return []


def _strip_html(text: str) -> str:
    """Google Alerts bolds matched search terms with <b> tags in both title and
    summary — strip markup and unescape entities so it doesn't leak into the briefing."""
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def _unwrap_google_redirect(url: str) -> str:
    """Google Alerts links point at a google.com/url tracking redirect, not the
    article — unwrap it so downstream code can link and dedupe on the real URL."""
    parsed = urlparse(url)
    if parsed.netloc in ("www.google.com", "google.com") and parsed.path == "/url":
        real = parse_qs(parsed.query).get("url", [None])[0]
        if real:
            return real
    return url


def _split_title_publisher(title: str) -> tuple[str, str | None]:
    """Google Alert titles often end with ' - Publisher' or ' | Publisher' (the
    actual publication name, supplied by Google). Split it off if present."""
    for sep in (" | ", " - "):
        if sep in title:
            head, _, tail = title.rpartition(sep)
            if head and tail and len(tail.split()) <= 5 and not tail.endswith((".", "?", "!")):
                return head.strip(), tail.strip()
    return title, None


def _domain_label(url: str) -> str:
    """Fallback publisher label derived from the article URL when the title
    doesn't carry one — e.g. https://www.pymnts.com/... -> 'Pymnts'."""
    netloc = re.sub(r"^www\.", "", urlparse(url).netloc)
    return netloc.split(".")[0].capitalize() if netloc else "Unknown source"


def resolve_display_sources(entries: list[dict]) -> list[dict]:
    """Replace Google Alert entries' title/url/source with the real article title,
    URL, and publisher — the raw feed data is a google.com/url tracking redirect
    and a 'Google Alert — <search term>' label, neither of which is what a reader
    should see cited as the source. Run this after filter_keywords, since keyword
    filtering matches against the original 'Google Alert — ...' source names in
    beats/payments_filters.yaml."""
    for entry in entries:
        real_url = _unwrap_google_redirect(entry["url"])
        if real_url == entry["url"]:
            continue  # not a Google Alert redirect — leave as-is
        clean_title, publisher = _split_title_publisher(_strip_html(entry["title"]))
        entry["url"] = real_url
        entry["title"] = clean_title
        entry["source"] = publisher or _domain_label(real_url)
        entry["summary"] = _strip_html(entry["summary"])
    return entries


def filter_recent(entries: list[dict], days: int = 3) -> list[dict]:
    """Filter entries to those published within the last N days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    recent, undated = [], []
    for entry in entries:
        dt = entry.get("published_dt")
        if dt is None:
            undated.append(entry)
        elif dt >= cutoff:
            recent.append(entry)
    if undated:
        print(f"  ({len(undated)} entries had no parseable date and were dropped)")
    return recent


def filter_already_covered(entries: list[dict], covered_headlines: list[str], threshold: float = 0.6) -> list[dict]:
    """Drop entries whose title closely matches an already-covered or
    editorially-rejected headline, so a still-recent aggregator republish of
    an old story doesn't reach the model looking like fresh news. This is a
    blunt title-similarity filter, not semantic dedup — a genuinely different
    article reporting the same underlying event under distinct wording will
    still get through, and relies on the 'previously covered' / 'editorially
    rejected' prompt instructions to be judged there instead."""
    def norm(s: str) -> str:
        return re.sub(r"[^a-z0-9 ]", "", s.lower())
    normalized = [norm(h) for h in covered_headlines]
    if not normalized:
        return entries
    kept = []
    for entry in entries:
        title = norm(entry.get("title", ""))
        if any(difflib.SequenceMatcher(None, title, c).ratio() >= threshold for c in normalized):
            continue
        kept.append(entry)
    return kept


def filter_keywords(entries: list[dict], beat_name: str) -> list[dict]:
    """Apply keyword include/exclude filters from beats/{beat_name}_filters.yaml.
    Returns entries that pass. Sources marked passthrough skip filtering."""
    filters_path = Path(__file__).parent.parent / "beats" / f"{beat_name}_filters.yaml"
    if not filters_path.exists():
        return entries

    with open(filters_path) as f:
        config = yaml.safe_load(f)

    global_keywords = [kw.lower() for kw in config.get("global", {}).get("keywords", [])]
    global_exclude = [kw.lower() for kw in config.get("global", {}).get("exclude", [])]
    source_configs = config.get("sources", {})

    passed = []
    for entry in entries:
        src_cfg = source_configs.get(entry["source"], {})

        if src_cfg.get("passthrough"):
            passed.append(entry)
            continue

        extra_include = [kw.lower() for kw in src_cfg.get("keywords", [])]
        keywords = global_keywords + extra_include
        include_pattern = re.compile("|".join(re.escape(kw) for kw in keywords), re.IGNORECASE) if keywords else None

        extra_exclude = [kw.lower() for kw in src_cfg.get("exclude", [])]
        all_exclude = global_exclude + extra_exclude
        exclude_pattern = re.compile("|".join(re.escape(kw) for kw in all_exclude), re.IGNORECASE) if all_exclude else None

        text = f"{entry['title']} {entry['summary']}"
        if include_pattern and not include_pattern.search(text):
            continue
        if exclude_pattern and exclude_pattern.search(text):
            continue
        passed.append(entry)

    print(f"  Keyword filter: {len(passed)} passed, {len(entries) - len(passed)} cut")
    return passed


def fetch_beat(beat_name: str) -> list[dict]:
    """Fetch all feeds for a beat and return normalised entries."""
    beat = load_beat(beat_name)
    all_entries = []
    for source in beat["sources"]:
        print(f"Fetching {source['name']}...")
        entries = fetch_feed(source["url"], source["name"])
        print(f"  {len(entries)} entries")
        all_entries.extend(entries)
    return all_entries


if __name__ == "__main__":
    entries = fetch_beat("payments")
    print(f"\nTotal entries: {len(entries)}")
    recent = filter_recent(entries)
    print(f"Recent entries (last 3 days): {len(recent)}")
    if recent:
        print("\nFirst entry:")
        for k, v in recent[0].items():
            if k != "published_dt":
                print(f"  {k}: {v[:80] if isinstance(v, str) else v}")