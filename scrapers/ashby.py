"""Ashby public job board scraper. Uses the same endpoint the public board calls."""
from __future__ import annotations
import html
import re
import requests
from typing import Iterable
from .common import Job

API = "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"


def _strip_html(s: str) -> str:
    if not s:
        return ""
    s = html.unescape(s)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"</p>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def fetch(company_name: str, slug: str) -> Iterable[Job]:
    url = API.format(slug=slug)
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"  [ashby] {company_name}: request failed ({e})")
        return []

    payload = r.json()
    jobs = payload.get("jobs", [])
    out = []
    for j in jobs:
        # Ashby returns descriptionHtml and descriptionPlain
        desc = j.get("descriptionPlain") or _strip_html(j.get("descriptionHtml", ""))
        out.append(Job(
            id=f"ashby:{slug}:{j['id']}",
            title=j.get("title", ""),
            company=company_name,
            location=j.get("location", ""),
            url=j.get("jobUrl", ""),
            source="Ashby",
            posted_at=j.get("publishedAt", ""),
            description=desc,
        ))
    return out
