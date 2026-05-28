"""Job Radar main entry point.

Pipeline:
  1. Load config + seen-jobs cache
  2. Run all configured scrapers (LinkedIn/Indeed via JobSpy, ATS APIs per company)
  3. Filter by title keywords, seniority, blocklist
  4. Dedupe against seen-jobs cache
  5. Notify on new matches
  6. Persist updated cache
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from typing import List, Set

import yaml

from scrapers.common import Job
from scrapers import greenhouse, lever, ashby, jobspy_scraper
from notifier import notify

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config" / "config.yaml"
SEEN_PATH = ROOT / "data" / "seen_jobs.json"
MAX_SEEN = 5000  # Cap the cache so it doesn't grow forever


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def load_seen() -> Set[str]:
    if not SEEN_PATH.exists():
        return set()
    try:
        with open(SEEN_PATH) as f:
            data = json.load(f)
            return set(data.get("ids", []))
    except (json.JSONDecodeError, OSError):
        return set()


def save_seen(seen: Set[str]) -> None:
    SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Keep only the most recent MAX_SEEN. Sets don't preserve order, so this
    # is best-effort: when we hit the cap, we trim arbitrarily. In practice
    # 5000 is enough headroom that this rarely triggers.
    trimmed = list(seen)[-MAX_SEEN:]
    with open(SEEN_PATH, "w") as f:
        json.dump({"ids": trimmed}, f, indent=2)


def matches_filter(job: Job, search_cfg: dict) -> bool:
    title = (job.title or "").lower()
    location = (job.location or "").lower()

    # Blocklist: hard reject
    for bad in search_cfg.get("title_blocklist", []):
        if bad.lower() in title:
            return False

    # Title keywords: at least one must match
    title_kws = [k.lower() for k in search_cfg.get("title_keywords", [])]
    if title_kws and not any(k in title for k in title_kws):
        return False

    # Optional seniority filter
    seniority_kws = [k.lower() for k in search_cfg.get("seniority_keywords", [])]
    if seniority_kws and not any(k in title for k in seniority_kws):
        return False

    # Location filter: at least one allowed substring must appear in the job's
    # location field. If the location is empty, we err on the side of keeping
    # the job (some ATS feeds omit location for remote roles).
    allowed = [a.lower() for a in search_cfg.get("allowed_locations", [])]
    if allowed and location and not any(a in location for a in allowed):
        return False

    return True


def run() -> int:
    cfg = load_config()
    seen = load_seen()
    print(f"Loaded {len(seen)} previously-seen job IDs")

    all_jobs: List[Job] = []

    # ATS scrapers (company career pages)
    for company in cfg.get("companies", []):
        name, ats, slug = company["name"], company["ats"], company["slug"]
        print(f"Fetching {name} ({ats})...")
        if ats == "greenhouse":
            all_jobs.extend(greenhouse.fetch(name, slug))
        elif ats == "lever":
            all_jobs.extend(lever.fetch(name, slug))
        elif ats == "ashby":
            all_jobs.extend(ashby.fetch(name, slug))
        else:
            print(f"  Unknown ATS '{ats}' for {name}")

    # JobSpy (LinkedIn + Indeed)
    js_cfg = cfg.get("jobspy", {})
    if js_cfg.get("enabled"):
        search_cfg = cfg["search"]
        # JobSpy takes a single search term, so we OR-join the most important
        # title keywords. Putting them in quotes makes JobSpy treat each as a phrase.
        # Indeed and LinkedIn both accept OR syntax.
        terms = search_cfg.get("title_keywords", [])[:5]  # cap to avoid query bloat
        search_term = " OR ".join(f'"{t}"' for t in terms) if terms else "marketing"
        print(f"Running JobSpy with search_term={search_term!r}")
        all_jobs.extend(jobspy_scraper.fetch(
            sites=js_cfg.get("sites", ["linkedin", "indeed"]),
            locations=search_cfg.get("locations", ["Austin, TX"]),
            search_term=search_term,
            hours_old=search_cfg.get("hours_old", 24),
            results_wanted=js_cfg.get("results_wanted", 50),
        ))

    print(f"Pulled {len(all_jobs)} total jobs across all sources")

    # Filter + dedupe
    search_cfg = cfg["search"]
    new_matches: List[Job] = []
    new_ids: Set[str] = set()
    for job in all_jobs:
        if job.id in seen or job.id in new_ids:
            continue
        if not matches_filter(job, search_cfg):
            # Still mark as seen so we don't re-filter it next run, but don't notify
            seen.add(job.id)
            continue
        new_matches.append(job)
        new_ids.add(job.id)

    print(f"{len(new_matches)} jobs matched filter and are new")

    # Enrichment: try to find hiring-manager candidates via Google Custom Search.
    # Silently no-ops if GOOGLE_API_KEY / GOOGLE_CSE_ID env vars aren't set.
    from enrichment.google_lookup import find_hiring_managers
    for job in new_matches:
        try:
            candidates = find_hiring_managers(
                company=job.company,
                job_title=job.title,
                jd_text=job.description,
                max_results=3,
            )
            job.hiring_managers = [c.display() for c in candidates]
            if candidates:
                print(f"  [enrich] {job.title} @ {job.company}: {len(candidates)} candidate(s)")
        except Exception as e:
            print(f"  [enrich] failed for {job.title} @ {job.company}: {e}")

    # Notify
    if new_matches:
        notify(new_matches, batch_size=cfg.get("notifications", {}).get("batch_size", 10))

    # Persist
    seen.update(new_ids)
    save_seen(seen)
    print(f"Saved {len(seen)} seen IDs")

    return 0


if __name__ == "__main__":
    sys.exit(run())
