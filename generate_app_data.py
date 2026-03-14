#!/usr/bin/env python3
"""Generate events.js for the PWA from events.json."""
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
events_path = SCRIPT_DIR / "events.json"
output_path = SCRIPT_DIR / "app" / "events.js"

with open(events_path) as f:
    data = json.load(f)

js = f"const EVENTS = {json.dumps(data, indent=2)};\n"
with open(output_path, "w") as f:
    f.write(js)

print(f"Generated {output_path} ({len(js)} bytes)")
