"""Discord webhook notifier.

Posts an embed per job, batched into messages of N embeds each (Discord caps at 10
embeds per message). Source color-codes the embed so you can eyeball at a glance.
"""
from __future__ import annotations
import os
import time
import requests
from typing import List
from scrapers.common import Job

SOURCE_COLORS = {
    "Greenhouse": 0x22C55E,  # green
    "Lever":      0xA855F7,  # purple
    "Ashby":      0x3B82F6,  # blue
    "Linkedin":   0x0A66C2,  # LinkedIn blue
    "Indeed":     0x2164F3,  # Indeed blue
}


def _embed(job: Job) -> dict:
    fields = [
        {"name": "Company",  "value": job.company  or "—", "inline": True},
        {"name": "Location", "value": job.location or "—", "inline": True},
        {"name": "Source",   "value": job.source   or "—", "inline": True},
    ]
    if job.hiring_managers:
        # Discord field values cap at 1024 chars; join with newlines
        value = "\n".join(job.hiring_managers)[:1024]
        fields.append({
            "name": "Possible hiring managers",
            "value": value,
            "inline": False,
        })
    return {
        "title": job.title[:256],  # Discord limit
        "url": job.url,
        "color": SOURCE_COLORS.get(job.source, 0x9CA3AF),
        "fields": fields,
        "footer": {"text": f"Posted {job.posted_at}" if job.posted_at else "New posting"},
    }


def notify(new_jobs: List[Job], batch_size: int = 10) -> None:
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook:
        print("DISCORD_WEBHOOK_URL not set, skipping notification")
        return
    if not new_jobs:
        print("No new jobs to notify")
        return

    print(f"Notifying about {len(new_jobs)} new jobs via Discord")

    # Discord allows up to 10 embeds per message
    chunk_size = min(batch_size, 10)
    for i in range(0, len(new_jobs), chunk_size):
        chunk = new_jobs[i:i + chunk_size]
        payload = {
            "username": "Job Radar",
            "content": f"**{len(chunk)} new job{'s' if len(chunk) != 1 else ''} matched your criteria**",
            "embeds": [_embed(j) for j in chunk],
        }
        try:
            r = requests.post(webhook, json=payload, timeout=10)
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"  Discord post failed: {e}")
        time.sleep(1)  # avoid hitting webhook rate limits on big batches
