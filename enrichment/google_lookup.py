"""Google Custom Search enrichment.

For each new job, we run targeted Google queries against public LinkedIn profile
pages and parse the results. We never load LinkedIn directly — Google indexes
the public snippets and that's all we need.

Free tier: 100 queries/day via Google Custom Search JSON API.
At ~2 queries per job (one for "reports to" role, one fallback), this comfortably
covers up to ~50 new matched jobs per day, which is well above what your filter
will produce.

If Google returns a quota error, we set a module-level flag and stop calling
the API for the rest of the run. Job notifications still go out, just without
the hiring-manager field.
"""
from __future__ import annotations
import os
import re
import time
import requests
from dataclasses import dataclass
from typing import List, Optional

API = "https://www.googleapis.com/customsearch/v1"

# Module-level kill switch. Once Google tells us we're out of quota or rate-
# limited, we stop trying for the rest of the process lifetime (one workflow run).
_quota_exhausted = False


def _is_quota_error(response: requests.Response) -> bool:
    """Detect Google's various flavors of 'you're done for the day' responses."""
    if response.status_code == 429:
        return True
    if response.status_code == 403:
        # Google returns 403 with a quota reason in the body
        try:
            body = response.json()
            reasons = [e.get("reason", "") for e in body.get("error", {}).get("errors", [])]
            return any("quota" in r.lower() or "rateLimitExceeded" in r for r in reasons)
        except (ValueError, AttributeError):
            return False
    return False

# Phrases that frequently precede the hiring-manager role in JDs.
# Order matters: more specific phrases first.
REPORTS_TO_PATTERNS = [
    r"reports?\s+(?:directly\s+)?to\s+(?:the\s+|our\s+)?([A-Z][A-Za-z,\s&/\-]{3,60}?)(?:\.|,|\n|;| and | who )",
    r"reporting\s+(?:directly\s+)?to\s+(?:the\s+|our\s+)?([A-Z][A-Za-z,\s&/\-]{3,60}?)(?:\.|,|\n|;| and | who )",
    r"this role reports to\s+(?:the\s+|our\s+)?([A-Z][A-Za-z,\s&/\-]{3,60}?)(?:\.|,|\n|;)",
    r"you'?ll report to\s+(?:the\s+|our\s+)?([A-Z][A-Za-z,\s&/\-]{3,60}?)(?:\.|,|\n|;)",
]

# Fallback role guesses when no "reports to" hint exists in the JD.
# These are searched as alternatives if the JD doesn't tell us who the manager is.
FALLBACK_ROLES_BY_KEYWORD = {
    "paid search":          ["head of paid", "director of paid", "VP marketing", "head of growth"],
    "paid media":           ["head of paid", "director of paid", "VP marketing", "head of growth"],
    "performance marketing":["head of growth", "VP growth", "director of performance marketing"],
    "growth marketing":     ["head of growth", "VP growth", "VP marketing"],
    "digital marketing":    ["director of marketing", "VP marketing", "head of marketing"],
    "marketing manager":    ["director of marketing", "VP marketing", "head of marketing"],
    "search marketing":     ["head of paid", "director of paid", "VP marketing"],
}


@dataclass
class HiringManagerCandidate:
    name: str
    headline: str  # The job title snippet Google shows
    profile_url: str

    def display(self) -> str:
        # For Discord embed: "Name (Headline)"
        return f"[{self.name}]({self.profile_url}) — {self.headline}"[:200]


def extract_reports_to(jd_text: str) -> Optional[str]:
    """Pull out 'reports to X' phrase from a JD if present."""
    if not jd_text:
        return None
    for pattern in REPORTS_TO_PATTERNS:
        m = re.search(pattern, jd_text, re.IGNORECASE)
        if m:
            role = m.group(1).strip().rstrip(",.")
            # Sanity check: the captured role shouldn't be absurdly long or contain newlines
            if 3 < len(role) < 80 and "\n" not in role:
                return role
    return None


def _fallback_role_for_title(job_title: str) -> Optional[str]:
    """Pick a reasonable hiring-manager role to search for, based on the job title."""
    t = (job_title or "").lower()
    for kw, roles in FALLBACK_ROLES_BY_KEYWORD.items():
        if kw in t:
            return roles[0]  # use the most likely one
    return None


def _google_search(query: str, num_results: int = 5) -> List[dict]:
    """One Google Custom Search call. Returns raw items list."""
    global _quota_exhausted
    if _quota_exhausted:
        return []

    api_key = os.environ.get("GOOGLE_API_KEY")
    cx = os.environ.get("GOOGLE_CSE_ID")
    if not api_key or not cx:
        return []

    params = {
        "key": api_key,
        "cx": cx,
        "q": query,
        "num": num_results,
    }
    try:
        r = requests.get(API, params=params, timeout=10)
        if _is_quota_error(r):
            print("  [google] daily quota exhausted, disabling enrichment for this run")
            _quota_exhausted = True
            return []
        r.raise_for_status()
        return r.json().get("items", []) or []
    except requests.Timeout:
        # Treat timeouts as a transient soft-fail; don't kill enrichment for the run
        print(f"  [google] timeout on query: {query!r}")
        return []
    except requests.RequestException as e:
        print(f"  [google] query failed ({e}): {query!r}")
        return []


def _parse_linkedin_result(item: dict) -> Optional[HiringManagerCandidate]:
    """Turn a Google result into a candidate. Returns None if it's not a LinkedIn profile."""
    link = item.get("link", "")
    if "linkedin.com/in/" not in link:
        return None

    # Google's title field for LinkedIn profiles is typically "Name - Headline - Company | LinkedIn"
    title = item.get("title", "")
    # Strip " | LinkedIn" and " - LinkedIn" suffixes
    title = re.sub(r"\s*[|\-]\s*LinkedIn\s*$", "", title).strip()

    # Try to split "Name - Headline"
    parts = title.split(" - ", 1)
    if len(parts) == 2:
        name, headline = parts[0].strip(), parts[1].strip()
    else:
        name, headline = title, item.get("snippet", "")[:120]

    # Sanity: a real name is usually 2 to 4 words, no weird chars
    if not name or len(name) > 60 or len(name.split()) > 5:
        return None

    return HiringManagerCandidate(name=name, headline=headline, profile_url=link)


def find_hiring_managers(
    company: str,
    job_title: str,
    jd_text: str = "",
    max_results: int = 3,
) -> List[HiringManagerCandidate]:
    """Main entry point. Returns up to `max_results` candidate profiles.

    Returns an empty list (silently) if:
    - GOOGLE_API_KEY / GOOGLE_CSE_ID are not set
    - The daily quota was already exhausted earlier in this run
    - No candidates were found
    """
    if not company or _quota_exhausted:
        return []

    api_key = os.environ.get("GOOGLE_API_KEY")
    cx = os.environ.get("GOOGLE_CSE_ID")
    if not api_key or not cx:
        # Silent skip — feature is opt-in via env vars
        return []

    # Strategy: try the JD's "reports to" hint first. If absent, fall back to
    # a role guess based on the job title.
    candidates: List[HiringManagerCandidate] = []
    seen_urls = set()
    queries_run = 0
    MAX_QUERIES = 2  # cap per job to stay well under the daily quota

    target_role = extract_reports_to(jd_text) or _fallback_role_for_title(job_title)

    if target_role:
        query = f'site:linkedin.com/in "{company}" "{target_role}"'
        for item in _google_search(query, num_results=5):
            c = _parse_linkedin_result(item)
            if c and c.profile_url not in seen_urls:
                candidates.append(c)
                seen_urls.add(c.profile_url)
        queries_run += 1

    # If we got nothing, try a broader fallback
    if not candidates and queries_run < MAX_QUERIES:
        query = f'site:linkedin.com/in "{company}" marketing'
        for item in _google_search(query, num_results=5):
            c = _parse_linkedin_result(item)
            if c and c.profile_url not in seen_urls:
                candidates.append(c)
                seen_urls.add(c.profile_url)
        queries_run += 1

    # Brief sleep avoids hitting Google's per-second rate limit on big batches
    time.sleep(0.2)

    return candidates[:max_results]
