"""Greenhouse public API scraper. No auth, no scraping tricks needed.

Note: The list endpoint /v1/boards/{slug}/jobs omits full descriptions by default.
We add ?content=true which returns descriptions inline (slightly larger payload
but one request instead of N+1).
"""
from __future__ import annotations
import html
import re
import requests
from typing import Iterable
from .common import Job

API = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"


def _strip_html(s: str) -> str:
    """Crude HTML-to-text. Good enough for regex-based 'reports to' extraction."""
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
        r = requests.get(url, timeout=20)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"  [greenhouse] {company_name}: request failed ({e})")
        return []

    payload = r.json()
    jobs = payload.get("jobs", [])
    out = []
    for j in jobs:
        out.append(Job(
            id=f"greenhouse:{slug}:{j['id']}",
            title=j.get("title", ""),
            company=company_name,
            location=(j.get("location") or {}).get("name", ""),
            url=j.get("absolute_url", ""),
            source="Greenhouse",
            posted_at=j.get("updated_at", ""),
            description=_strip_html(j.get("content", "")),
        ))
    return out
