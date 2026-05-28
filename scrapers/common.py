"""Shared types used across scrapers."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List


@dataclass
class Job:
    id: str           # Stable unique identifier across runs
    title: str
    company: str
    location: str
    url: str
    source: str       # "Greenhouse", "Lever", "Ashby", "Linkedin", "Indeed"
    posted_at: str    # Free-form date string, source-dependent
    description: str = ""  # JD body, used for enrichment (reports-to extraction)
    hiring_managers: List[str] = field(default_factory=list)  # populated post-fetch

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
