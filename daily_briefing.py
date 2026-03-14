#!/usr/bin/env python3
"""
Daily briefing script for Chicago AI/STEM events.
Run via cron every morning to get notified about today's events.
Also supports: --week, --tomorrow, --upcoming flags.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
EVENTS_FILE = SCRIPT_DIR / "events.json"

DAY_MAP = {
    "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
    "Friday": 4, "Saturday": 5, "Sunday": 6
}
DAY_NAMES = {v: k for k, v in DAY_MAP.items()}


def load_events():
    with open(EVENTS_FILE) as f:
        return json.load(f)


def nth_weekday_of_month(year, month, weekday_num, n):
    if n == -1:
        if month == 12:
            last_day = datetime(year + 1, 1, 1) - timedelta(days=1)
        else:
            last_day = datetime(year, month + 1, 1) - timedelta(days=1)
        days_back = (last_day.weekday() - weekday_num) % 7
        return last_day - timedelta(days=days_back)
    else:
        first_day = datetime(year, month, 1)
        days_ahead = weekday_num - first_day.weekday()
        if days_ahead < 0:
            days_ahead += 7
        first_weekday = first_day + timedelta(days=days_ahead)
        return first_weekday + timedelta(weeks=n - 1)


def get_events_for_date(events, target_date):
    """Return all events happening on target_date."""
    day_name = DAY_NAMES[target_date.weekday()]
    found = []

    # Weekly recurring
    for ev in events.get("recurring_weekly", []):
        if ev["day"] == day_name:
            found.append({
                "name": ev["name"],
                "time": ev["time"],
                "location": ev.get("location", ""),
                "url": ev.get("url", ""),
                "description": ev.get("description", ""),
                "category": ev.get("category", ""),
                "priority": ev.get("priority", "medium"),
                "type": "weekly"
            })

    # Monthly recurring
    for ev in events.get("recurring_monthly", []):
        if ev["day"] == day_name:
            weekday = DAY_MAP[ev["day"]]
            try:
                expected = nth_weekday_of_month(
                    target_date.year, target_date.month, weekday, ev["week"]
                )
                if expected.date() == target_date.date():
                    found.append({
                        "name": ev["name"],
                        "time": ev["time"],
                        "location": ev.get("location", ""),
                        "url": ev.get("url", ""),
                        "description": ev.get("description", ""),
                        "category": ev.get("category", ""),
                        "priority": ev.get("priority", "medium"),
                        "type": "monthly"
                    })
            except Exception:
                pass

    # Quarterly/seasonal
    for ev in events.get("recurring_quarterly_seasonal", []):
        if ev["day"] == day_name:
            for period in ev.get("active_periods", []):
                start_str, end_str = period.split("/")
                p_start = datetime.strptime(start_str, "%Y-%m-%d").date()
                p_end = datetime.strptime(end_str, "%Y-%m-%d").date()
                if p_start <= target_date.date() <= p_end:
                    found.append({
                        "name": ev["name"],
                        "time": ev["time"],
                        "location": ev.get("location", ""),
                        "url": ev.get("url", ""),
                        "description": ev.get("description", ""),
                        "category": ev.get("category", ""),
                        "priority": ev.get("priority", "medium"),
                        "type": "seasonal"
                    })

    # Specific dates
    for ev in events.get("specific_dates", []):
        if ev["date"] == target_date.strftime("%Y-%m-%d"):
            found.append({
                "name": ev["name"],
                "time": ev["time"],
                "location": ev.get("location", ""),
                "url": ev.get("url", ""),
                "description": ev.get("description", ""),
                "category": ev.get("category", ""),
                "priority": "high",
                "type": "special"
            })

    # Sort by time
    found.sort(key=lambda e: e["time"])
    return found


def format_time(time_str):
    h, m = map(int, time_str.split(":"))
    period = "AM" if h < 12 else "PM"
    display_h = h if h <= 12 else h - 12
    if display_h == 0:
        display_h = 12
    return f"{display_h}:{m:02d} {period}"


def format_event(ev, verbose=True):
    priority_marker = {"high": "★", "medium": "●", "low": "○"}.get(ev["priority"], "●")
    type_tag = {"weekly": "", "monthly": " [monthly]", "seasonal": " [seasonal]", "special": " [SPECIAL]"}.get(ev["type"], "")

    lines = [f"  {priority_marker} {format_time(ev['time'])} — {ev['name']}{type_tag}"]
    if verbose:
        if ev["location"]:
            lines.append(f"    📍 {ev['location']}")
        if ev["description"]:
            lines.append(f"    → {ev['description']}")
        if ev["url"]:
            lines.append(f"    🔗 {ev['url']}")
    return "\n".join(lines)


def send_notification(title, message):
    """Send a macOS notification."""
    try:
        script = f'display notification "{message}" with title "{title}" sound name "Glass"'
        subprocess.run(["osascript", "-e", script], capture_output=True)
    except Exception:
        pass


def print_day(target_date, events_data, verbose=True):
    day_events = get_events_for_date(events_data, target_date)
    day_name = target_date.strftime("%A, %B %d, %Y")

    if not day_events:
        print(f"\n📅 {day_name}")
        print("  No scheduled events. Check 1871 (https://1871.com/events/) or")
        print("  Meetup.com (https://www.meetup.com/find/us--il--chicago/ai/) for pop-up events.")
        print("  Or use this as a study/reading day to prep for upcoming talks.")
        return 0

    print(f"\n📅 {day_name} — {len(day_events)} event(s)")
    print("  " + "─" * 50)
    for ev in day_events:
        print(format_event(ev, verbose))
        print()

    return len(day_events)


def main():
    events = load_events()
    today = datetime.now()

    if "--tomorrow" in sys.argv:
        target = today + timedelta(days=1)
        print_day(target, events)
        return

    if "--week" in sys.argv:
        print("=" * 60)
        print(f"  WEEKLY BRIEFING — Week of {today.strftime('%B %d, %Y')}")
        print("=" * 60)
        total = 0
        for i in range(7):
            day = today + timedelta(days=i)
            total += print_day(day, events)
        print(f"\n{'=' * 60}")
        print(f"  Total: {total} events this week")
        print(f"{'=' * 60}")
        return

    if "--upcoming" in sys.argv:
        days = 14
        if "--days" in sys.argv:
            idx = sys.argv.index("--days")
            if idx + 1 < len(sys.argv):
                days = int(sys.argv[idx + 1])
        print(f"Next {days} days of events:")
        total = 0
        for i in range(days):
            day = today + timedelta(days=i)
            count = print_day(day, events, verbose=False)
            total += count
        print(f"\nTotal: {total} events in next {days} days")
        return

    if "--notify" in sys.argv:
        # Cron mode: send macOS notification + print brief
        day_events = get_events_for_date(events, today)
        if day_events:
            names = ", ".join(ev["name"] for ev in day_events[:3])
            send_notification(
                f"📅 {len(day_events)} events today",
                names
            )
        print_day(today, events, verbose=True)
        return

    # Default: today's briefing
    print("=" * 60)
    print("  CHICAGO AI/STEM DAILY BRIEFING")
    print("=" * 60)
    print_day(today, events)

    # Also show tomorrow
    tomorrow = today + timedelta(days=1)
    tmrw_events = get_events_for_date(events, tomorrow)
    if tmrw_events:
        print(f"\n  ⏭  Tomorrow ({tomorrow.strftime('%A')}): {len(tmrw_events)} event(s)")
        for ev in tmrw_events:
            print(f"     • {format_time(ev['time'])} — {ev['name']}")

    print(f"\n{'=' * 60}")
    print("  Quick links:")
    print("  • TTIC Calendar:  https://www.ttic.edu/calendar/")
    print("  • 1871 Events:    https://1871.com/events/")
    print("  • CHI IRL texts:  Text 'hi' to (312) 847-2515")
    print("  • Meetup Chicago: https://www.meetup.com/find/us--il--chicago/ai/")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
