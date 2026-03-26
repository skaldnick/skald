import feedparser
import yaml
from datetime import datetime, timedelta, timezone
from pathlib import Path


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