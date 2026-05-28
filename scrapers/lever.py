"""Lever public API scraper.

Lever returns plain-text descriptions in `descriptionPlain` so no HTML stripping needed.
"""
from __future__ import annotations
import requests
from typing import Iterable
from .common import Job

API = "https://api.lever.co/v0/postings/{slug}?mode=json"


def fetch(company_name: str, slug: str) -> Iterable[Job]:
    url = API.format(slug=slug)
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"  [lever] {company_name}: request failed ({e})")
        return []

    out = []
    for j in r.json():
        cats = j.get("categories") or {}
        out.append(Job(
            id=f"lever:{slug}:{j['id']}",
            title=j.get("text", ""),
            company=company_name,
            location=cats.get("location", ""),
            url=j.get("hostedUrl", ""),
            source="Lever",
            posted_at=str(j.get("createdAt", "")),
            description=j.get("descriptionPlain", "") or j.get("description", ""),
        ))
    return out
