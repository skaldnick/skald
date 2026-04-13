"""
Fetch all feeds for a beat and save raw entries to data/raw/{beat}/{date}.json.
Run this once to cache a snapshot for keyword filter testing.

Usage:
    python tools/fetch_raw.py [beat]   # default: payments
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingester.fetcher import fetch_beat, filter_recent

BEAT = sys.argv[1] if len(sys.argv) > 1 else "payments"
OUT_DIR = Path(__file__).parent.parent / "data" / "raw" / BEAT
OUT_DIR.mkdir(parents=True, exist_ok=True)

date_str = datetime.now().strftime("%Y-%m-%d")
out_path = OUT_DIR / f"{date_str}.json"

print(f"Fetching all feeds for beat: {BEAT}")
all_entries = fetch_beat(BEAT)
print(f"  {len(all_entries)} total entries")

recent = filter_recent(all_entries)
print(f"  {len(recent)} after recency filter (3 days)")

# Serialise — drop published_dt (datetime, not JSON-serialisable)
records = [{k: v for k, v in e.items() if k != "published_dt"} for e in all_entries]

out_path.write_text(json.dumps({"beat": BEAT, "fetched_at": datetime.now(timezone.utc).isoformat(), "entries": records}, indent=2))
print(f"\nSaved {len(records)} entries to {out_path}")
