#!/usr/bin/env python3
"""
Weekly event scraper for Chicago AI/STEM events.
Fetches iCal feeds, RSS feeds, and Meetup calendars. Merges into events.json.
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
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).parent
EVENTS_FILE = SCRIPT_DIR / "events.json"
LOG_FILE = SCRIPT_DIR / "logs" / "scraper.log"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

DELAY = 2  # polite delay between requests

# ══════════════════════════════════════════════════════════
# FEED REGISTRY — 67 feeds total
# ══════════════════════════════════════════════════════════

ICAL_FEEDS = {
    # ── Universities & Research Institutes ──
    "ttic": {
        "url": "https://calendar.google.com/calendar/ical/ttic.edu_cdv9cmkdu5g30llnce9ko5b2dc%40group.calendar.google.com/public/basic.ics",
        "category": "AI/CS Research",
        "location": "TTIC Room 530, 6045 S. Kenwood Ave, Chicago",
        "prefix": "TTIC",
    },
    "uchicago_dsi_ical": {
        "url": "https://datascience.uchicago.edu/?feed=eo-events",
        "category": "Data Science",
        "location": "UChicago Data Science Institute",
        "prefix": "UChicago DSI",
    },
    "uchicago_cs_ical": {
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
    "chicago_quantum": {
        "url": "https://calendar.google.com/calendar/ical/chiquantumx%40gmail.com/public/basic.ics",
        "category": "Quantum/Physics",
        "location": "Chicago (various)",
        "prefix": "Quantum",
    },
    "depaul": {
        "url": "https://events.depaul.edu/calendar/1.ics",
        "category": "University",
        "location": "DePaul University, Chicago",
        "prefix": "DePaul",
        "filter_keywords": ["artificial intelligence", "machine learning", "data science",
                           "computer science", "quantum", "hackathon", "neural network",
                           "robotics", "deep learning", "nlp", "llm", "cybersecurity",
                           "python programming", "ai research"],
    },

    # ── Meetup: AI / ML / Data Science ──
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
        "prefix": "Chicago AI",
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
    "meetup_ai_ml_cv": {
        "url": "https://www.meetup.com/chicago-ai-machine-learning-data-science/events/ical/",
        "category": "AI/ML",
        "location": "Chicago",
        "prefix": "Chicago AI/ML/CV",
    },
    "meetup_data_traders": {
        "url": "https://www.meetup.com/data-driven-traders-network/events/ical/",
        "category": "AI/Finance",
        "location": "Chicago",
        "prefix": "Data Traders",
    },
    "meetup_analytics_club": {
        "url": "https://www.meetup.com/ac-ord/events/ical/",
        "category": "Analytics/AI",
        "location": "Chicago",
        "prefix": "Analytics.Club",
    },
    "meetup_ai_professionals": {
        "url": "https://www.meetup.com/ai-professionals-chicago/events/ical/",
        "category": "AI/ML",
        "location": "Chicago",
        "prefix": "AI Professionals",
    },
    "meetup_odsc": {
        "url": "https://www.meetup.com/odsc-chicago-data-science/events/ical/",
        "category": "Data Science",
        "location": "Chicago",
        "prefix": "ODSC Chicago",
    },
    "meetup_ds_dojo": {
        "url": "https://www.meetup.com/data-science-dojo-chicago/events/ical/",
        "category": "AI/ML",
        "location": "Chicago",
        "prefix": "DS Dojo",
    },
    "meetup_ai_2030": {
        "url": "https://www.meetup.com/ai-2030-responsible-artificial-intelligence/events/ical/",
        "category": "AI/Ethics",
        "location": "Chicago",
        "prefix": "AI 2030",
    },
    "meetup_naperville_ml": {
        "url": "https://www.meetup.com/naperville-machine-learning-meetup-group/events/ical/",
        "category": "AI/ML",
        "location": "Naperville, IL",
        "prefix": "Naperville ML",
    },
    "meetup_analytics_cloud": {
        "url": "https://www.meetup.com/Chicago-Analytics-and-Data-Science-in-the-Cloud/events/ical/",
        "category": "Data Science",
        "location": "Chicago",
        "prefix": "Analytics Cloud",
    },

    # ── Meetup: Developer / Engineering ──
    "meetup_js_chi": {
        "url": "https://www.meetup.com/js-chi/events/ical/",
        "category": "Dev/JavaScript",
        "location": "Chicago",
        "prefix": "Chicago JS",
    },
    "meetup_dotnet": {
        "url": "https://www.meetup.com/chicagodevnet/events/ical/",
        "category": "Dev/.NET",
        "location": "Chicago",
        "prefix": "Chicago .NET",
    },
    "meetup_nscoder": {
        "url": "https://www.meetup.com/nscoder-chicago/events/ical/",
        "category": "Dev/Apple",
        "location": "Chicago",
        "prefix": "NSCoder Chicago",
    },
    "meetup_platform_eng": {
        "url": "https://www.meetup.com/platform-engineers-chicago/events/ical/",
        "category": "DevOps/Platform",
        "location": "Chicago",
        "prefix": "Platform Eng",
    },
    "meetup_pulumi": {
        "url": "https://www.meetup.com/chicago-pulumi-user-group/events/ical/",
        "category": "DevOps/IaC",
        "location": "Chicago",
        "prefix": "Pulumi Chicago",
    },
    "meetup_graphdb": {
        "url": "https://www.meetup.com/graphdb-midwest/events/ical/",
        "category": "Data/Graphs",
        "location": "Chicago",
        "prefix": "GraphDB Midwest",
    },

    # ── Meetup: Cloud / DevOps ──
    "meetup_aws": {
        "url": "https://www.meetup.com/aws-chicago/events/ical/",
        "category": "Cloud/AWS",
        "location": "Chicago",
        "prefix": "AWS Chicago",
    },
    "meetup_gdg_cloud": {
        "url": "https://www.meetup.com/google-developers-group-gdg-cloud-chicago/events/ical/",
        "category": "Cloud/GCP",
        "location": "Chicago",
        "prefix": "GDG Cloud",
    },
    "meetup_gdg": {
        "url": "https://www.meetup.com/google-developers-group-gdg-chicago/events/ical/",
        "category": "Dev/Google",
        "location": "Chicago",
        "prefix": "GDG Chicago",
    },
    "meetup_cloud_native_ai": {
        "url": "https://www.meetup.com/chicago-cloud-native-x-ai-tech-group/events/ical/",
        "category": "Cloud/AI",
        "location": "Chicago",
        "prefix": "Cloud Native AI",
    },
    "meetup_grafana": {
        "url": "https://www.meetup.com/grafana-and-friends-chicago/events/ical/",
        "category": "Observability",
        "location": "Chicago",
        "prefix": "Grafana Chicago",
    },

    # ── Meetup: Security / Blockchain ──
    "meetup_burbsec": {
        "url": "https://www.meetup.com/burbsec/events/ical/",
        "category": "Security",
        "location": "Chicago suburbs",
        "prefix": "BurbSec",
    },
    "meetup_ics_cyber": {
        "url": "https://www.meetup.com/Chicago-Cyber-Security-for-Control-Systems/events/ical/",
        "category": "Security/ICS",
        "location": "Chicago",
        "prefix": "ICS Cyber",
    },
    "meetup_devsecops": {
        "url": "https://www.meetup.com/chicago-devsecops/events/ical/",
        "category": "Security/DevSecOps",
        "location": "Chicago",
        "prefix": "DevSecOps",
    },
    "meetup_lfdt": {
        "url": "https://www.meetup.com/lfdt-chicago/events/ical/",
        "category": "Blockchain/AI",
        "location": "Chicago",
        "prefix": "LF Decentralized",
    },
    "meetup_bitcoin": {
        "url": "https://www.meetup.com/Bitcoin-Open-Blockchain-Community-Chicago/events/ical/",
        "category": "Blockchain",
        "location": "Chicago",
        "prefix": "Bitcoin Chicago",
    },
    "meetup_bitdevs": {
        "url": "https://www.meetup.com/chibitdevs/events/ical/",
        "category": "Blockchain/Dev",
        "location": "Chicago",
        "prefix": "ChiBitDevs",
    },
    "meetup_cyberyacht": {
        "url": "https://www.meetup.com/cyberyacht-wednesdays/events/ical/",
        "category": "Security/Networking",
        "location": "Chicago River",
        "prefix": "CyberYacht",
    },

    # ── Meetup: Startup / Networking ──
    "meetup_startup_grind": {
        "url": "https://www.meetup.com/startup-grind-chicago/events/ical/",
        "category": "Startup",
        "location": "Chicago",
        "prefix": "Startup Grind",
    },
    "meetup_techmixer": {
        "url": "https://www.meetup.com/chicagotechmixer/events/ical/",
        "category": "Tech Networking",
        "location": "Chicago",
        "prefix": "Tech Mixer",
    },
    "meetup_startup_council": {
        "url": "https://www.meetup.com/chicago-startup-founders/events/ical/",
        "category": "Startup",
        "location": "Chicago",
        "prefix": "StartupCouncil",
    },
    "meetup_founder_101": {
        "url": "https://www.meetup.com/chicago-startup-founder-101/events/ical/",
        "category": "Startup",
        "location": "Chicago",
        "prefix": "Founder 101",
    },
    "meetup_startup_oasis": {
        "url": "https://www.meetup.com/startup-oasis-chicago/events/ical/",
        "category": "Startup",
        "location": "Chicago",
        "prefix": "Startup Oasis",
    },
    "meetup_founders_therapy": {
        "url": "https://www.meetup.com/founders-therapy/events/ical/",
        "category": "Startup",
        "location": "Chicago",
        "prefix": "Founders Therapy",
    },
    "meetup_bootstrappers": {
        "url": "https://www.meetup.com/bootstrappers-breakfast-chicago/events/ical/",
        "category": "Startup",
        "location": "Chicago (virtual)",
        "prefix": "Bootstrappers",
    },
    "meetup_primewise": {
        "url": "https://www.meetup.com/primewise-founders-club-chicago-2/events/ical/",
        "category": "Startup/VC",
        "location": "Chicago",
        "prefix": "Primewise",
    },

    # ── Meetup: Currently empty but valid (will populate) ──
    "meetup_chicago_ml": {
        "url": "https://www.meetup.com/chicago-ml/events/ical/",
        "category": "AI/ML",
        "location": "Chicago",
        "prefix": "Chicago ML",
    },
    "meetup_ml_study": {
        "url": "https://www.meetup.com/chicago-machine-learning-study-group/events/ical/",
        "category": "AI/ML",
        "location": "Chicago",
        "prefix": "ML Study Group",
    },
    "meetup_big_data": {
        "url": "https://www.meetup.com/chicago-big-data-analytics-meetup/events/ical/",
        "category": "Data/Analytics",
        "location": "Chicago",
        "prefix": "Big Data Chicago",
    },
    "meetup_dataiku": {
        "url": "https://www.meetup.com/analytics-data-science-by-dataiku-chicago/events/ical/",
        "category": "AI Agents",
        "location": "Chicago",
        "prefix": "AI Agent Builders",
    },
    "meetup_pyladies": {
        "url": "https://www.meetup.com/Chicago-PyLadies/events/ical/",
        "category": "Python/Dev",
        "location": "Chicago",
        "prefix": "PyLadies Chicago",
    },
    "meetup_ai_llms": {
        "url": "https://www.meetup.com/chicago-ai-llms/events/ical/",
        "category": "AI/LLMs",
        "location": "Chicago",
        "prefix": "Chicago LLMs",
    },
    "meetup_acm": {
        "url": "https://www.meetup.com/acm-chicago/events/ical/",
        "category": "CS Professional",
        "location": "Chicago",
        "prefix": "ACM Chicago",
    },
    "meetup_r_users": {
        "url": "https://www.meetup.com/chicago-r-user-group/events/ical/",
        "category": "Data Science/R",
        "location": "Chicago",
        "prefix": "R Users Chicago",
    },
    "meetup_rust": {
        "url": "https://www.meetup.com/chicago-rust-meetup/events/ical/",
        "category": "Dev/Rust",
        "location": "Chicago",
        "prefix": "Rust Chicago",
    },
    "meetup_kotlin": {
        "url": "https://www.meetup.com/chicago-kotlin/events/ical/",
        "category": "Dev/Kotlin",
        "location": "Chicago",
        "prefix": "Kotlin Chicago",
    },
    "meetup_java": {
        "url": "https://www.meetup.com/chicago-java-users-group/events/ical/",
        "category": "Dev/Java",
        "location": "Chicago",
        "prefix": "Java Chicago",
    },
    "meetup_k8s": {
        "url": "https://www.meetup.com/kubernetes-chicago/events/ical/",
        "category": "DevOps/K8s",
        "location": "Chicago",
        "prefix": "K8s Chicago",
    },
    "meetup_data_eng": {
        "url": "https://www.meetup.com/chicago-data-engineering/events/ical/",
        "category": "Data Engineering",
        "location": "Chicago",
        "prefix": "Data Eng Chicago",
    },
    "meetup_nlp": {
        "url": "https://www.meetup.com/chicago-nlp/events/ical/",
        "category": "AI/NLP",
        "location": "Chicago",
        "prefix": "Chicago NLP",
    },
    "meetup_women_ai": {
        "url": "https://www.meetup.com/women-ai-innovation/events/ical/",
        "category": "AI/Diversity",
        "location": "Chicago",
        "prefix": "Women in AI",
    },
    "meetup_product": {
        "url": "https://www.meetup.com/chicago-product-management/events/ical/",
        "category": "Product",
        "location": "Chicago",
        "prefix": "Product School",
    },
}

# ── RSS feed URLs (UChicago LiveWhale + UIC) ──
RSS_FEEDS = {
    "uchicago_events": {
        "url": "https://events.uchicago.edu/live/rss/events/",
        "category": "University",
        "location": "UChicago campus",
        "prefix": "UChicago",
        "filter_keywords": ["artificial intelligence", "machine learning", "data science",
                           "computer science", "quantum", "hackathon", "algorithm",
                           "neural", "robotics", "deep learning", "nlp", "llm",
                           "cybersecurity", "blockchain"],
    },
    "uchicago_dsi_rss": {
        "url": "https://events.uchicago.edu/live/rss/events/group/Data%20Science%20Institute/",
        "category": "Data Science",
        "location": "UChicago DSI",
        "prefix": "UChicago DSI",
        "filter_keywords": None,  # Accept all from this feed
    },
    "uchicago_ai_tag": {
        "url": "https://events.uchicago.edu/live/rss/events/tag/AI/",
        "category": "AI Research",
        "location": "UChicago campus",
        "prefix": "UChicago AI",
        "filter_keywords": None,
    },
    "uchicago_ds_tag": {
        "url": "https://events.uchicago.edu/live/rss/events/tag/data%20science/",
        "category": "Data Science",
        "location": "UChicago campus",
        "prefix": "UChicago DS",
        "filter_keywords": None,
    },
    "uchicago_cs_tag": {
        "url": "https://events.uchicago.edu/live/rss/events/tag/computer%20science/",
        "category": "CS Research",
        "location": "UChicago campus",
        "prefix": "UChicago CS",
        "filter_keywords": None,
    },
    "uic_events": {
        "url": "https://today.uic.edu/events/feed/",
        "category": "University",
        "location": "UIC campus, Chicago",
        "prefix": "UIC",
        "filter_keywords": ["ai", "machine learning", "data", "computer", "science",
                           "research", "seminar", "lecture", "workshop", "stem",
                           "engineering", "technology", "quantum", "hackathon"],
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
# PhD AI Research Relevance Scorer (0–100)
# ══════════════════════════════════════════════════════════

# Sources known to produce PhD-level research content
SOURCE_SCORES = {
    "ttic": 95,              # Top-tier CS research institute
    "uchicago_cs_ical": 90,  # UChicago CS dept
    "uchicago_dsi_ical": 85, # UChicago Data Science Institute
    "chicago_quantum": 80,   # Quantum research consortium
    "fermilab": 70,          # National lab (physics-heavy, some AI)
    "uchicago_ai_tag": 90,
    "uchicago_cs_tag": 85,
    "uchicago_ds_tag": 80,
    "uchicago_dsi_rss": 80,
    "uchicago_events": 60,   # General UChicago (filtered)
    "depaul": 50,
    "uic_events": 55,
    # Meetups: AI-focused
    "meetup_aittg": 55,
    "meetup_aichicago": 50,
    "meetup_ai_ml_cv": 55,
    "meetup_ai_2030": 45,
    "meetup_ai_professionals": 40,
    "meetup_ai_llms": 55,
    "meetup_nlp": 60,
    "meetup_chicago_ml": 60,
    "meetup_ml_study": 65,    # Study group = deeper
    "meetup_naperville_ml": 45,
    "meetup_odsc": 50,
    "meetup_ds_dojo": 45,
    "meetup_women_ai": 50,
    "meetup_cloud_native_ai": 45,
    # Data science
    "meetup_pydata": 55,
    "meetup_datanight": 45,
    "meetup_data_traders": 40,
    "meetup_analytics_club": 35,
    "meetup_analytics_cloud": 35,
    "meetup_big_data": 40,
    "meetup_dataiku": 50,
    "meetup_data_eng": 40,
    # Dev communities
    "meetup_chipy": 45,
    "meetup_pyladies": 40,
    "meetup_graphdb": 45,
    "meetup_js_chi": 25,
    "meetup_dotnet": 20,
    "meetup_nscoder": 15,
    "meetup_rust": 30,
    "meetup_kotlin": 15,
    "meetup_java": 15,
    "meetup_product": 10,
    # Infra/DevOps
    "meetup_platform_eng": 25,
    "meetup_pulumi": 20,
    "meetup_aws": 25,
    "meetup_gdg_cloud": 30,
    "meetup_gdg": 30,
    "meetup_grafana": 20,
    "meetup_k8s": 20,
    # Security
    "meetup_burbsec": 20,
    "meetup_ics_cyber": 25,
    "meetup_devsecops": 20,
    "meetup_cyberyacht": 15,
    # Blockchain
    "meetup_lfdt": 30,
    "meetup_bitcoin": 15,
    "meetup_bitdevs": 20,
    # Startup/networking
    "meetup_startup_grind": 15,
    "meetup_techmixer": 10,
    "meetup_startup_council": 10,
    "meetup_founder_101": 10,
    "meetup_startup_oasis": 10,
    "meetup_founders_therapy": 5,
    "meetup_bootstrappers": 5,
    "meetup_primewise": 10,
    "meetup_r_users": 40,
    "meetup_acm": 50,
}

# Keywords that boost relevance to PhD AI research (and their weights)
RESEARCH_BOOST_KEYWORDS = {
    # Core AI/ML research terms (+15-25 each)
    "transformer": 20, "attention mechanism": 25, "diffusion model": 25,
    "reinforcement learning": 25, "generative model": 20, "foundation model": 20,
    "large language model": 20, "representation learning": 25,
    "graph neural": 20, "contrastive learning": 20, "self-supervised": 25,
    "few-shot": 20, "zero-shot": 20, "meta-learning": 25,
    "neural architecture": 20, "optimization": 15, "convex": 20,
    "variational": 20, "bayesian": 20, "gaussian process": 25,
    "kernel method": 20, "causal inference": 25, "causal discovery": 25,
    # Research activity terms (+10-15)
    "paper": 10, "arxiv": 15, "publication": 10, "thesis": 15,
    "dissertation": 15, "phd": 15, "doctoral": 15, "postdoc": 15,
    "faculty": 10, "professor": 10, "colloquium": 15, "seminar": 10,
    "lecture series": 10, "research talk": 15, "invited talk": 15,
    "peer review": 15, "proceedings": 10, "journal club": 15,
    # Specific research areas (+10-15)
    "nlp": 15, "natural language processing": 15, "computer vision": 15,
    "speech recognition": 10, "robotics": 10, "multi-agent": 15,
    "planning": 10, "reasoning": 15, "theorem proving": 20,
    "formal verification": 15, "interpretability": 20, "alignment": 15,
    "fairness": 10, "robustness": 15, "adversarial": 15,
    "federated learning": 15, "privacy": 10, "differential privacy": 20,
    "information theory": 20, "complexity theory": 20, "approximation": 15,
    "convergence": 15, "sample complexity": 20, "generalization": 15,
    "statistical learning": 20, "pac learning": 25,
    # Prestigious venue/org signals (+10)
    "neurips": 15, "icml": 15, "iclr": 15, "aaai": 15, "cvpr": 15,
    "acl ": 15, "emnlp": 15, "uai": 15, "colt": 15, "aistats": 15,
    "ttic": 10, "uchicago": 5, "argonne": 5, "fermilab": 5,
}

# Keywords that reduce relevance (networking, social, beginner)
RESEARCH_PENALTY_KEYWORDS = {
    "networking event": -15, "happy hour": -20, "mixer": -20,
    "social hour": -15, "career fair": -15, "job fair": -15,
    "beginner": -10, "intro to": -10, "101": -10,
    "pitch competition": -15, "fundraising": -20, "investor": -15,
    "cofounder matching": -20, "founder therapy": -20,
    "breakfast meetup": -10, "coffee chat": -10,
    "bootcamp": -10, "certification": -15,
}


def infer_source(event):
    """Infer source from event name/category when source field is missing."""
    name = event.get("name", "").lower()
    cat = event.get("category", "").lower()
    loc = event.get("location", "").lower()
    eid = event.get("id", "").lower()

    if "ttic" in name or "ttic" in eid:
        return "ttic"
    if "uchicago" in name or "uchicago" in loc:
        if "dsi" in name or "data science institute" in loc:
            return "uchicago_dsi_ical"
        if "theory" in name or "cs " in cat:
            return "uchicago_cs_ical"
        return "uchicago_events"
    if "fermilab" in name or "fermilab" in loc:
        return "fermilab"
    if "quantum" in name or "quantum" in cat:
        return "chicago_quantum"
    if "northwestern" in name or "nico" in name or "northwestern" in loc:
        return "uchicago_cs_ical"  # similar prestige
    if "chipy" in name or "chipy" in eid:
        return "meetup_chipy"
    if "pydata" in name:
        return "meetup_pydata"
    if "ai tinkerer" in name:
        return "meetup_aichicago"
    if "acm" in name or "acm" in eid:
        return "meetup_acm"
    if "chi hack" in name:
        return "meetup_chipy"  # similar tier
    if "analytics" in name:
        return "meetup_analytics_club"
    if "data night" in name:
        return "meetup_datanight"
    if "agent builder" in name:
        return "meetup_dataiku"
    if "aittg" in name or "ai developers" in name:
        return "meetup_aittg"
    return ""


def score_research_relevance(event):
    """Score an event 0-100 for PhD AI research relevance."""
    source = event.get("source", "") or infer_source(event)
    text = (event.get("name", "") + " " + event.get("description", "") + " " +
            event.get("category", "")).lower()

    # Start with source base score
    score = SOURCE_SCORES.get(source, 30)

    # Apply keyword boosts
    for keyword, boost in RESEARCH_BOOST_KEYWORDS.items():
        if keyword in text:
            score += boost

    # Apply penalties
    for keyword, penalty in RESEARCH_PENALTY_KEYWORDS.items():
        if keyword in text:
            score += penalty  # penalty is negative

    # Clamp to 0-100
    return max(0, min(100, score))


def relevance_tier(score):
    """Human-readable tier from score."""
    if score >= 80:
        return "essential"     # Don't miss these
    elif score >= 60:
        return "strong"        # Very relevant
    elif score >= 40:
        return "moderate"      # Worth attending if free
    elif score >= 20:
        return "tangential"    # Loosely related
    else:
        return "low"           # Not research-relevant


# ══════════════════════════════════════════════════════════
# iCal (.ics) parser
# ══════════════════════════════════════════════════════════

def parse_ics_datetime(val):
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
    return re.sub(r"\r?\n[ \t]", "", text)


def parse_ics_events(ics_text):
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
            key_part, _, val = line.partition(":")
            key = key_part.split(";")[0].upper()

            if key == "SUMMARY":
                current["summary"] = val.replace("\\,", ",").replace("\\n", " ").strip()
            elif key == "DTSTART":
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


def scrape_ical_feed(feed_key, feed_config):
    log(f"  Fetching {feed_config['prefix']}...")
    ics_text = fetch(feed_config["url"])
    if not ics_text:
        return []

    raw_events = parse_ics_events(ics_text)
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    keywords = feed_config.get("filter_keywords")
    results = []

    for ev in raw_events:
        if "dtstart" not in ev or "summary" not in ev:
            continue

        dt = ev["dtstart"]
        if dt < today or dt > today + timedelta(days=180):
            continue

        summary = ev["summary"]

        # Apply keyword filter if specified (for large general calendars)
        if keywords:
            text_lower = (summary + " " + ev.get("description", "") + " " + ev.get("location", "")).lower()
            if not any(kw in text_lower for kw in keywords):
                continue

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

    log(f"    → {len(results)} upcoming events")
    return results


# ══════════════════════════════════════════════════════════
# RSS parser
# ══════════════════════════════════════════════════════════

def parse_rss_date(date_str):
    """Parse RSS pubDate or other date formats."""
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except (ValueError, TypeError):
            continue
    return None


def scrape_rss_feed(feed_key, feed_config):
    log(f"  Fetching {feed_config['prefix']} RSS...")
    xml_text = fetch(feed_config["url"])
    if not xml_text:
        return []

    results = []
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    keywords = feed_config.get("filter_keywords")

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        log(f"    WARN: XML parse error: {e}")
        return []

    # Handle RSS 2.0
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        description = (item.findtext("description") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date = item.findtext("pubDate") or item.findtext("date") or ""

        if not title or len(title) < 5:
            continue

        # Apply keyword filter if specified
        if keywords:
            text_lower = (title + " " + description).lower()
            if not any(kw in text_lower for kw in keywords):
                continue

        dt = parse_rss_date(pub_date)
        if not dt:
            continue

        # Make timezone-naive for comparison
        if dt.tzinfo:
            dt = dt.replace(tzinfo=None)

        if dt < today or dt > today + timedelta(days=180):
            continue

        summary = title
        if not summary.startswith(feed_config["prefix"]):
            summary = f"{feed_config['prefix']}: {summary}"

        # Clean up HTML from description
        clean_desc = re.sub(r"<[^>]+>", "", description)[:200].strip()

        results.append({
            "name": summary,
            "date": dt.strftime("%Y-%m-%d"),
            "time": dt.strftime("%H:%M") if dt.hour > 0 else "12:00",
            "duration_min": 60,
            "location": feed_config["location"],
            "url": link,
            "description": clean_desc,
            "category": feed_config["category"],
            "source": feed_key,
        })

    log(f"    → {len(results)} upcoming events")
    return results


# ══════════════════════════════════════════════════════════
# Merge + Deploy
# ══════════════════════════════════════════════════════════

def merge_scraped(existing_data, scraped_events):
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

        # Fuzzy duplicate check
        is_dup = False
        for existing in existing_data["specific_dates"]:
            if existing["date"] == ev["date"]:
                existing_words = set(re.sub(r"[^a-z0-9 ]", "", existing["name"].lower()).split())
                new_words = set(re.sub(r"[^a-z0-9 ]", "", ev["name"].lower()).split())
                common = {"the", "a", "an", "and", "or", "of", "in", "at", "for", "to", "with", "chicago"}
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

        score = score_research_relevance(ev)
        existing_data["specific_dates"].append({
            "id": eid,
            "name": ev["name"],
            "date": ev["date"],
            "time": ev["time"],
            "duration_min": ev.get("duration_min", 60),
            "location": ev.get("location", ""),
            "url": ev.get("url", ""),
            "category": ev.get("category", ""),
            "relevance": score,
            "tier": relevance_tier(score),
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


def score_all_events(data):
    """Score/re-score all events in the database."""
    scored = 0
    for section in ("recurring_weekly", "recurring_monthly", "recurring_quarterly_seasonal", "specific_dates"):
        for ev in data.get(section, []):
            score = score_research_relevance(ev)
            ev["relevance"] = score
            ev["tier"] = relevance_tier(score)
            scored += 1
    log(f"Scored {scored} events for PhD AI research relevance")


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
    log("=" * 60)
    log(f"Starting weekly event scrape — {len(ICAL_FEEDS)} iCal + {len(RSS_FEEDS)} RSS feeds")

    data = load_events()
    prune_past_events(data)

    all_scraped = []
    errors = 0

    # iCal feeds
    log(f"── iCal feeds ({len(ICAL_FEEDS)}) ──")
    for key, config in ICAL_FEEDS.items():
        try:
            results = scrape_ical_feed(key, config)
            all_scraped.extend(results)
        except Exception as e:
            log(f"    ERROR {key}: {e}")
            errors += 1

    # RSS feeds
    log(f"── RSS feeds ({len(RSS_FEEDS)}) ──")
    for key, config in RSS_FEEDS.items():
        try:
            results = scrape_rss_feed(key, config)
            all_scraped.extend(results)
        except Exception as e:
            log(f"    ERROR {key}: {e}")
            errors += 1

    total_feeds = len(ICAL_FEEDS) + len(RSS_FEEDS)
    log(f"Total scraped: {len(all_scraped)} events from {total_feeds} feeds ({errors} errors)")

    added = merge_scraped(data, all_scraped)

    # Score everything for PhD AI research relevance
    score_all_events(data)

    save_events(data)
    regenerate_app_data()

    if added > 0:
        try:
            msg = f"Found {added} new events from {total_feeds} feeds"
            subprocess.run([
                "osascript", "-e",
                f'display notification "{msg}" with title "CHI AI Cal Update" sound name "Glass"'
            ], capture_output=True)
        except Exception:
            pass

    if "--no-push" not in sys.argv:
        git_push()

    log(f"Scrape complete. {added} new events added from {total_feeds} feeds.")
    log("=" * 60)


if __name__ == "__main__":
    main()
