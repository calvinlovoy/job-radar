"""LinkedIn + Indeed via the JobSpy library.

JobSpy abstracts the scraping pain (rotating user agents, parsing, etc).
It is not bulletproof: LinkedIn in particular may rate-limit, in which case
the function logs the error and returns an empty list so the rest of the
pipeline keeps working.
"""
from __future__ import annotations
import hashlib
from typing import Iterable, List
from .common import Job

try:
    from jobspy import scrape_jobs
    JOBSPY_AVAILABLE = True
except ImportError:
    JOBSPY_AVAILABLE = False


def _stable_id(site: str, url: str, title: str, company: str) -> str:
    # JobSpy doesn't always return a job_id. Hash a stable tuple instead.
    raw = f"{site}|{url}|{title}|{company}".lower()
    return f"{site}:{hashlib.sha1(raw.encode()).hexdigest()[:16]}"


def fetch(
    sites: List[str],
    locations: List[str],
    search_term: str,
    hours_old: int,
    results_wanted: int,
) -> Iterable[Job]:
    if not JOBSPY_AVAILABLE:
        print("  [jobspy] library not installed, skipping")
        return []

    out = []
    for loc in locations:
        try:
            df = scrape_jobs(
                site_name=sites,
                search_term=search_term,
                location=loc,
                results_wanted=results_wanted,
                hours_old=hours_old,
                country_indeed="USA",
            )
        except Exception as e:
            print(f"  [jobspy] {loc}: scrape failed ({e})")
            continue

        if df is None or len(df) == 0:
            continue

        for _, row in df.iterrows():
            site = str(row.get("site", "")).lower() or "unknown"
            url = str(row.get("job_url", "") or "")
            title = str(row.get("title", "") or "")
            company = str(row.get("company", "") or "")
            if not url or not title:
                continue
            out.append(Job(
                id=_stable_id(site, url, title, company),
                title=title,
                company=company,
                location=str(row.get("location", "") or ""),
                url=url,
                source=site.capitalize(),
                posted_at=str(row.get("date_posted", "") or ""),
            ))
    return out
