#!/usr/bin/env python3
"""
Weekly event scraper for Chicago AI/STEM events.
Fetches iCal feeds and Meetup calendars, merges new events into events.json.
Run via launchd every Sunday at 3:15am, or manually: python3 scrape_events.py

After scraping, automatically:
1. Updates events.json with new specific-date events
2. Regenerates docs/events.js for the PWA
3. Commits and pushes to GitHub (updates the live app)
"""

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).parent
EVENTS_FILE = SCRIPT_DIR / "events.json"
LOG_FILE = SCRIPT_DIR / "logs" / "scraper.log"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

DELAY = 3  # polite delay between requests

# ── iCal feed URLs (confirmed working) ──
ICAL_FEEDS = {
    "ttic": {
        "url": "https://calendar.google.com/calendar/ical/ttic.edu_cdv9cmkdu5g30llnce9ko5b2dc%40group.calendar.google.com/public/basic.ics",
        "category": "AI/CS Research",
        "location": "TTIC Room 530, 6045 S. Kenwood Ave, Chicago",
        "prefix": "TTIC",
    },
    "uchicago_dsi": {
        "url": "https://datascience.uchicago.edu/?feed=eo-events",
        "category": "Data Science",
        "location": "UChicago Data Science Institute",
        "prefix": "UChicago DSI",
    },
    "uchicago_cs": {
        "url": "https://computerscience.uchicago.edu/?feed=eo-events",
        "category": "CS Research",
        "location": "UChicago CS Department",
        "prefix": "UChicago CS",
    },
    "fermilab": {
        "url": "https://events.fnal.gov/?feed=eo-events",
        "category": "Physics/Science",
        "location": "Fermilab, Batavia, IL",
        "prefix": "Fermilab",
    },
    # Meetup iCal feeds
    "meetup_aittg": {
        "url": "https://www.meetup.com/aittg-chicago/events/ical/",
        "category": "AI/ML",
        "location": "Chicago",
        "prefix": "AITTG",
    },
    "meetup_aichicago": {
        "url": "https://www.meetup.com/aichicago/events/ical/",
        "category": "AI/ML",
        "location": "Downtown Chicago",
        "prefix": "Chicago AI Meetup",
    },
    "meetup_pydata": {
        "url": "https://www.meetup.com/pydatachi/events/ical/",
        "category": "Data Science",
        "location": "Chicago",
        "prefix": "PyData Chicago",
    },
    "meetup_chipy": {
        "url": "https://www.meetup.com/_chipy_/events/ical/",
        "category": "Python/Dev",
        "location": "Chicago",
        "prefix": "ChiPy",
    },
    "meetup_datanight": {
        "url": "https://www.meetup.com/chicago-data-night/events/ical/",
        "category": "Data Science",
        "location": "Chicago",
        "prefix": "Data Night",
    },
}


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    LOG_FILE.parent.mkdir(exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def fetch(url):
    time.sleep(DELAY)
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        return r.text
    except Exception as e:
        log(f"  WARN: Failed to fetch {url}: {e}")
        return None


def load_events():
    with open(EVENTS_FILE) as f:
        return json.load(f)


def save_events(data):
    with open(EVENTS_FILE, "w") as f:
        json.dump(data, f, indent=2)
    log(f"Saved {EVENTS_FILE}")


def existing_ids(data):
    ids = set()
    for key in ("recurring_weekly", "recurring_monthly", "recurring_quarterly_seasonal", "specific_dates"):
        for ev in data.get(key, []):
            ids.add(ev["id"])
    return ids


def make_id(name, date_str):
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40]
    return f"scraped-{slug}-{date_str}"


# ══════════════════════════════════════════════════════════
# iCal (.ics) parser — lightweight, no external dependency
# ══════════════════════════════════════════════════════════

def parse_ics_datetime(val):
    """Parse an iCal DTSTART/DTEND value into a datetime."""
    # Strip any TZID parameter prefix like "TZID=America/Chicago:"
    if ":" in val and not val.startswith("20"):
        val = val.split(":")[-1]
    val = val.strip().rstrip("Z")

    for fmt in ("%Y%m%dT%H%M%S", "%Y%m%d"):
        try:
            return datetime.strptime(val, fmt)
        except ValueError:
            continue
    return None


def unfold_ics(text):
    """Unfold ICS continuation lines (lines starting with space/tab)."""
    return re.sub(r"\r?\n[ \t]", "", text)


def parse_ics_events(ics_text):
    """Parse VEVENT blocks from raw ICS text. Returns list of dicts."""
    ics_text = unfold_ics(ics_text)
    events = []
    in_event = False
    current = {}

    for line in ics_text.split("\n"):
        line = line.strip()
        if line == "BEGIN:VEVENT":
            in_event = True
            current = {}
        elif line == "END:VEVENT":
            in_event = False
            if current:
                events.append(current)
            current = {}
        elif in_event and ":" in line:
            # Handle properties like DTSTART;TZID=America/Chicago:20260315T113000
            key_part, _, val = line.partition(":")
            key = key_part.split(";")[0].upper()

            if key == "SUMMARY":
                current["summary"] = val.replace("\\,", ",").replace("\\n", " ").strip()
            elif key == "DTSTART":
                full_val = key_part.split(":", 1)[-1] if ":" in key_part else ""
                dt = parse_ics_datetime(val)
                if dt:
                    current["dtstart"] = dt
            elif key == "DTEND":
                dt = parse_ics_datetime(val)
                if dt:
                    current["dtend"] = dt
            elif key == "LOCATION":
                current["location"] = val.replace("\\,", ",").replace("\\n", ", ").strip()
            elif key == "DESCRIPTION":
                current["description"] = val.replace("\\n", " ").replace("\\,", ",").strip()[:200]
            elif key == "URL":
                current["url"] = val.strip()

    return events


# ══════════════════════════════════════════════════════════
# Feed scraper
# ══════════════════════════════════════════════════════════

def scrape_ical_feed(feed_key, feed_config):
    """Fetch and parse a single iCal feed."""
    log(f"Fetching {feed_config['prefix']} feed...")
    ics_text = fetch(feed_config["url"])
    if not ics_text:
        return []

    raw_events = parse_ics_events(ics_text)
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    results = []

    for ev in raw_events:
        if "dtstart" not in ev or "summary" not in ev:
            continue

        dt = ev["dtstart"]
        # Skip past events
        if dt < today:
            continue
        # Skip events more than 6 months out
        if dt > today + timedelta(days=180):
            continue

        summary = ev["summary"]
        # Add prefix if not already present
        if not summary.startswith(feed_config["prefix"]):
            summary = f"{feed_config['prefix']}: {summary}"

        duration = 60
        if "dtend" in ev:
            diff = (ev["dtend"] - dt).total_seconds() / 60
            if 15 <= diff <= 480:
                duration = int(diff)

        results.append({
            "name": summary,
            "date": dt.strftime("%Y-%m-%d"),
            "time": dt.strftime("%H:%M"),
            "duration_min": duration,
            "location": ev.get("location", feed_config["location"]),
            "url": ev.get("url", ""),
            "description": ev.get("description", ""),
            "category": feed_config["category"],
            "source": feed_key,
        })

    log(f"  Found {len(results)} upcoming events from {feed_config['prefix']}")
    return results


# ══════════════════════════════════════════════════════════
# Merge + Deploy
# ══════════════════════════════════════════════════════════

def merge_scraped(existing_data, scraped_events):
    """Merge newly scraped events into existing data, avoiding duplicates."""
    ids = existing_ids(existing_data)
    today = datetime.now().strftime("%Y-%m-%d")
    added = 0
    skipped_past = 0
    skipped_dup = 0

    for ev in scraped_events:
        if ev["date"] < today:
            skipped_past += 1
            continue

        eid = make_id(ev["name"], ev["date"])

        if eid in ids:
            skipped_dup += 1
            continue

        # Fuzzy duplicate check: same date + similar name
        is_dup = False
        for existing in existing_data["specific_dates"]:
            if existing["date"] == ev["date"]:
                existing_words = set(re.sub(r"[^a-z0-9 ]", "", existing["name"].lower()).split())
                new_words = set(re.sub(r"[^a-z0-9 ]", "", ev["name"].lower()).split())
                # Remove very common words
                common = {"the", "a", "an", "and", "or", "of", "in", "at", "for", "to", "with"}
                existing_words -= common
                new_words -= common
                if existing_words and new_words:
                    overlap = len(existing_words & new_words) / min(len(existing_words), len(new_words))
                    if overlap >= 0.5:
                        is_dup = True
                        break
        if is_dup:
            skipped_dup += 1
            continue

        existing_data["specific_dates"].append({
            "id": eid,
            "name": ev["name"],
            "date": ev["date"],
            "time": ev["time"],
            "duration_min": ev.get("duration_min", 60),
            "location": ev.get("location", ""),
            "url": ev.get("url", ""),
            "category": ev.get("category", ""),
        })
        ids.add(eid)
        added += 1

    existing_data["specific_dates"].sort(key=lambda e: e["date"])
    log(f"Merge: +{added} new, {skipped_dup} duplicates skipped, {skipped_past} past events skipped")
    return added


def prune_past_events(data):
    today = datetime.now().strftime("%Y-%m-%d")
    before = len(data["specific_dates"])
    data["specific_dates"] = [e for e in data["specific_dates"] if e["date"] >= today]
    pruned = before - len(data["specific_dates"])
    if pruned:
        log(f"Pruned {pruned} past events")


def regenerate_app_data():
    with open(EVENTS_FILE) as f:
        data = json.load(f)
    js = f"const EVENTS = {json.dumps(data, indent=2)};\n"
    output = SCRIPT_DIR / "docs" / "events.js"
    with open(output, "w") as f:
        f.write(js)
    log(f"Regenerated {output}")


def git_push():
    os.chdir(SCRIPT_DIR)
    status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
    if not status.stdout.strip():
        log("No changes to commit")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    subprocess.run(["git", "add", "events.json", "docs/events.js"], check=True)
    subprocess.run(
        ["git", "commit", "-m", f"Auto-update events ({today})"],
        check=True
    )
    result = subprocess.run(["git", "push"], capture_output=True, text=True)
    if result.returncode == 0:
        log("Pushed to GitHub — app will update automatically")
    else:
        log(f"Push failed: {result.stderr}")


def main():
    log("=" * 50)
    log("Starting weekly event scrape")

    data = load_events()
    prune_past_events(data)

    # Fetch all iCal feeds
    all_scraped = []
    for key, config in ICAL_FEEDS.items():
        try:
            results = scrape_ical_feed(key, config)
            all_scraped.extend(results)
        except Exception as e:
            log(f"  ERROR in {key}: {e}")

    log(f"Total scraped: {len(all_scraped)} events from {len(ICAL_FEEDS)} feeds")

    # Merge
    added = merge_scraped(data, all_scraped)

    # Save + regenerate + push
    save_events(data)
    regenerate_app_data()

    if added > 0:
        try:
            msg = f"Found {added} new events from weekly scan"
            subprocess.run([
                "osascript", "-e",
                f'display notification "{msg}" with title "CHI AI Cal Update" sound name "Glass"'
            ], capture_output=True)
        except Exception:
            pass

    if "--no-push" not in sys.argv:
        git_push()

    log(f"Scrape complete. {added} new events added.")
    log("=" * 50)


if __name__ == "__main__":
    main()
