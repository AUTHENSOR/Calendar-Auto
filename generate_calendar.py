#!/usr/bin/env python3
"""
Generate .ics calendar files from Chicago AI/STEM events database.
Import the generated .ics into Google Calendar, Apple Calendar, or Outlook.
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
EVENTS_FILE = SCRIPT_DIR / "events.json"
OUTPUT_DIR = SCRIPT_DIR / "calendars"

# How many weeks into the future to generate recurring events
WEEKS_AHEAD = 26  # ~6 months


def load_events():
    with open(EVENTS_FILE) as f:
        return json.load(f)


DAY_MAP = {
    "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
    "Friday": 4, "Saturday": 5, "Sunday": 6
}


def ics_datetime(dt):
    return dt.strftime("%Y%m%dT%H%M%S")


def ics_date(dt):
    return dt.strftime("%Y%m%d")


def escape_ics(text):
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def make_vevent(uid, summary, dtstart, dtend, location, description, url, category=""):
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTART:{ics_datetime(dtstart)}",
        f"DTEND:{ics_datetime(dtend)}",
        f"SUMMARY:{escape_ics(summary)}",
    ]
    if location:
        lines.append(f"LOCATION:{escape_ics(location)}")
    if description:
        desc = description
        if url:
            desc += f"\\n\\nMore info: {url}"
        lines.append(f"DESCRIPTION:{escape_ics(desc)}")
    if url:
        lines.append(f"URL:{url}")
    if category:
        lines.append(f"CATEGORIES:{escape_ics(category)}")
    # 30 min reminder
    lines.extend([
        "BEGIN:VALARM",
        "TRIGGER:-PT30M",
        "ACTION:DISPLAY",
        f"DESCRIPTION:Reminder: {escape_ics(summary)} in 30 minutes",
        "END:VALARM",
        # Morning-of reminder
        "BEGIN:VALARM",
        "TRIGGER:-PT3H",
        "ACTION:DISPLAY",
        f"DESCRIPTION:Today: {escape_ics(summary)}",
        "END:VALARM",
        "END:VEVENT"
    ])
    return "\n".join(lines)


def next_weekday(start_date, weekday_num):
    """Find the next occurrence of a weekday from start_date."""
    days_ahead = weekday_num - start_date.weekday()
    if days_ahead < 0:
        days_ahead += 7
    return start_date + timedelta(days=days_ahead)


def nth_weekday_of_month(year, month, weekday_num, n):
    """Get the nth occurrence of a weekday in a month. n=-1 means last."""
    if n == -1:
        # Last occurrence: start from end of month
        if month == 12:
            last_day = datetime(year + 1, 1, 1) - timedelta(days=1)
        else:
            last_day = datetime(year, month + 1, 1) - timedelta(days=1)
        days_back = (last_day.weekday() - weekday_num) % 7
        return last_day - timedelta(days=days_back)
    else:
        first_day = datetime(year, month, 1)
        first_weekday = next_weekday(first_day, weekday_num)
        return first_weekday + timedelta(weeks=n - 1)


def generate_weekly_events(event, start_date, weeks):
    """Generate VEVENT blocks for a weekly recurring event."""
    vevents = []
    weekday = DAY_MAP[event["day"]]
    first = next_weekday(start_date, weekday)

    for i in range(weeks):
        dt = first + timedelta(weeks=i)
        hour, minute = map(int, event["time"].split(":"))
        dtstart = dt.replace(hour=hour, minute=minute)
        dtend = dtstart + timedelta(minutes=event["duration_min"])
        uid = f"{event['id']}-{ics_date(dt)}@chicago-ai-calendar"

        vevents.append(make_vevent(
            uid=uid,
            summary=event["name"],
            dtstart=dtstart,
            dtend=dtend,
            location=event.get("location", ""),
            description=event.get("description", ""),
            url=event.get("url", ""),
            category=event.get("category", "")
        ))
    return vevents


def generate_monthly_events(event, start_date, months=6):
    """Generate VEVENT blocks for a monthly recurring event."""
    vevents = []
    weekday = DAY_MAP[event["day"]]

    for m_offset in range(months):
        month = start_date.month + m_offset
        year = start_date.year + (month - 1) // 12
        month = ((month - 1) % 12) + 1

        try:
            dt = nth_weekday_of_month(year, month, weekday, event["week"])
        except Exception:
            continue

        if dt < start_date:
            continue

        hour, minute = map(int, event["time"].split(":"))
        dtstart = dt.replace(hour=hour, minute=minute)
        dtend = dtstart + timedelta(minutes=event["duration_min"])
        uid = f"{event['id']}-{ics_date(dt)}@chicago-ai-calendar"

        vevents.append(make_vevent(
            uid=uid,
            summary=event["name"],
            dtstart=dtstart,
            dtend=dtend,
            location=event.get("location", ""),
            description=event.get("description", ""),
            url=event.get("url", ""),
            category=event.get("category", "")
        ))
    return vevents


def generate_specific_events(event):
    """Generate VEVENT for a specific-date event."""
    dt = datetime.strptime(event["date"], "%Y-%m-%d")
    hour, minute = map(int, event["time"].split(":"))
    dtstart = dt.replace(hour=hour, minute=minute)
    dtend = dtstart + timedelta(minutes=event["duration_min"])
    uid = f"{event['id']}@chicago-ai-calendar"

    return make_vevent(
        uid=uid,
        summary=event["name"],
        dtstart=dtstart,
        dtend=dtend,
        location=event.get("location", ""),
        description=event.get("description", ""),
        url=event.get("url", ""),
        category=event.get("category", "")
    )


def wrap_ics(vevents, cal_name="Chicago AI/STEM Calendar"):
    header = "\n".join([
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Chicago AI Calendar//EN",
        f"X-WR-CALNAME:{cal_name}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH"
    ])
    footer = "END:VCALENDAR"
    return header + "\n" + "\n".join(vevents) + "\n" + footer


def main():
    events = load_events()
    OUTPUT_DIR.mkdir(exist_ok=True)
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    all_vevents = []

    # Weekly recurring
    for ev in events.get("recurring_weekly", []):
        all_vevents.extend(generate_weekly_events(ev, today, WEEKS_AHEAD))

    # Monthly recurring
    for ev in events.get("recurring_monthly", []):
        all_vevents.extend(generate_monthly_events(ev, today, months=6))

    # Quarterly/seasonal (generate for active periods)
    for ev in events.get("recurring_quarterly_seasonal", []):
        weekday = DAY_MAP[ev["day"]]
        for period in ev.get("active_periods", []):
            start_str, end_str = period.split("/")
            p_start = datetime.strptime(start_str, "%Y-%m-%d")
            p_end = datetime.strptime(end_str, "%Y-%m-%d")
            if p_end < today:
                continue
            effective_start = max(p_start, today)
            current = next_weekday(effective_start, weekday)
            while current <= p_end:
                hour, minute = map(int, ev["time"].split(":"))
                dtstart = current.replace(hour=hour, minute=minute)
                dtend = dtstart + timedelta(minutes=ev["duration_min"])
                uid = f"{ev['id']}-{ics_date(current)}@chicago-ai-calendar"
                all_vevents.append(make_vevent(
                    uid=uid,
                    summary=ev["name"],
                    dtstart=dtstart,
                    dtend=dtend,
                    location=ev.get("location", ""),
                    description=ev.get("description", ""),
                    url=ev.get("url", ""),
                    category=ev.get("category", "")
                ))
                current += timedelta(weeks=1)

    # Specific dates
    for ev in events.get("specific_dates", []):
        ev_date = datetime.strptime(ev["date"], "%Y-%m-%d")
        if ev_date >= today:
            all_vevents.append(generate_specific_events(ev))

    # Write combined calendar
    combined_path = OUTPUT_DIR / "chicago_ai_stem_all.ics"
    with open(combined_path, "w") as f:
        f.write(wrap_ics(all_vevents))
    print(f"Generated: {combined_path} ({len(all_vevents)} events)")

    # Also generate per-category calendars for selective import
    by_category = {}
    for ev in events.get("recurring_weekly", []) + events.get("recurring_monthly", []):
        cat = ev.get("category", "Other")
        by_category.setdefault(cat, []).append(ev)

    for cat, cat_events in by_category.items():
        cat_vevents = []
        for ev in cat_events:
            if "day" in ev and "week" not in ev:
                cat_vevents.extend(generate_weekly_events(ev, today, WEEKS_AHEAD))
            elif "week" in ev:
                cat_vevents.extend(generate_monthly_events(ev, today, months=6))
        if cat_vevents:
            safe_name = cat.lower().replace("/", "_").replace(" ", "_")
            cat_path = OUTPUT_DIR / f"chicago_{safe_name}.ics"
            with open(cat_path, "w") as f:
                f.write(wrap_ics(cat_vevents, f"Chicago {cat}"))
            print(f"Generated: {cat_path} ({len(cat_vevents)} events)")

    print(f"\n=== Import Instructions ===")
    print(f"Google Calendar: Go to Settings > Import & Export > Import > select the .ics file")
    print(f"Apple Calendar:  Double-click the .ics file, or File > Import")
    print(f"Outlook:         File > Open & Export > Import/Export > Import an iCalendar file")
    print(f"\nRecommended: Import '{combined_path.name}' for everything in one calendar.")
    print(f"Or import individual category files for separate color-coded calendars.")


if __name__ == "__main__":
    main()
