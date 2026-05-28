# Job Radar

Monitors LinkedIn, Indeed, and a configurable list of company career pages
(Greenhouse, Lever, Ashby) for new postings that match your criteria, and pings
you on Discord within minutes of them going live. Runs on GitHub Actions, so no
laptop, no VPS, no cost.

## How it works

```
GitHub Actions cron (every 15 min)
        ↓
   main.py runs
        ↓
   scrapers/
     ├── greenhouse.py  ── public JSON API
     ├── lever.py       ── public JSON API
     ├── ashby.py       ── public JSON API
     └── jobspy_scraper ── LinkedIn + Indeed via JobSpy
        ↓
   filter by title keywords + seniority + blocklist
        ↓
   dedupe against data/seen_jobs.json
        ↓
   Discord webhook ── one embed per job
        ↓
   commit updated seen_jobs.json back to repo
```

## Setup (~10 minutes)

### 1. Create a Discord webhook

1. Create a Discord server (or use an existing one). A server just for yourself works fine.
2. Pick a channel. Settings (gear icon next to the channel name) → Integrations → Webhooks → New Webhook.
3. Name it "Job Radar" or whatever you want. Click "Copy Webhook URL". Keep this URL secret.

### 2. (Optional but recommended) Set up Google Custom Search for hiring-manager lookup

When new jobs are found, Job Radar can run Google searches against public LinkedIn
profile pages to surface likely hiring-manager candidates. Free, 100 queries/day.

1. Go to https://console.cloud.google.com → create a new project (or use an existing one)
2. Enable the "Custom Search API": APIs & Services → Library → search "Custom Search API" → Enable
3. Create an API key: APIs & Services → Credentials → Create Credentials → API key. Copy it.
4. Go to https://programmablesearchengine.google.com/controlpanel/create
5. Sites to search: leave it blank. Toggle ON "Search the entire web". Name it "Job Radar" or anything.
6. Click Create. On the next page, copy the "Search engine ID" (looks like `a1b2c3d4e5f6g7h8i`).

You'll add both as secrets in step 4 below.

### 3. Push this repo to GitHub

```bash
cd job-radar
git init
git add .
git commit -m "initial commit"
gh repo create job-radar --private --source=. --push
```

(Or create the repo on github.com and push manually if you don't have the `gh` CLI.)

### 4. Add secrets

On the repo page: Settings → Secrets and variables → Actions → New repository secret.

Add these one at a time:

- `DISCORD_WEBHOOK_URL` — the URL you copied from Discord
- `GOOGLE_API_KEY` — the API key from Google Cloud (optional, skip if you don't want hiring-manager lookup)
- `GOOGLE_CSE_ID` — the Search engine ID from Programmable Search Engine (optional, must be set if `GOOGLE_API_KEY` is)

### 5. Enable Actions

Go to the Actions tab. If prompted, enable workflows. The cron schedule
starts running automatically. To test immediately without waiting, click
"Job Radar" in the left sidebar then "Run workflow".

### 6. Tune the config

Edit `config/config.yaml` to match what you actually want:

- `title_keywords`: words that must appear in the job title
- `seniority_keywords`: optional second filter for seniority
- `title_blocklist`: words that disqualify a job
- `locations`: where to search on LinkedIn/Indeed
- `companies`: list of ATS career pages to poll directly

For the company list, find each company's slug from their public job board URL:

| ATS        | Pattern                          | Example                            | Slug         |
|------------|----------------------------------|------------------------------------|--------------|
| Greenhouse | `boards.greenhouse.io/<slug>`    | `boards.greenhouse.io/stripe`      | `stripe`     |
| Lever      | `jobs.lever.co/<slug>`           | `jobs.lever.co/netflix`            | `netflix`    |
| Ashby      | `jobs.ashbyhq.com/<slug>`        | `jobs.ashbyhq.com/notion`          | `notion`     |

## Caveats

**LinkedIn rate-limits scrapers.** JobSpy works most of the time but you'll get
periodic empty responses. The Greenhouse/Lever/Ashby APIs are reliable since
they're effectively public, so a targeted company watchlist is more dependable
than relying on LinkedIn.

**GitHub Actions cron is best-effort.** Scheduled workflows can be delayed by
several minutes under load. For most job searches this is fine. If you need
sub-minute latency, move to a VPS with systemd timers.

**The first run sends a lot of notifications.** Everything in your search criteria
that exists right now will look "new". After the first run the dedupe cache
takes over and you'll only get genuinely fresh postings. To suppress the first
flood, you can run `python main.py` locally once, commit the resulting
`data/seen_jobs.json`, and only then enable the workflow.

## Running locally

```bash
pip install -r requirements.txt
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
python main.py
```

## Tuning notification volume

If you're getting too many hits, tighten `seniority_keywords` or add more
`title_blocklist` entries. If you're getting too few, broaden `title_keywords`
or add more companies. The filter is keyword-only by design (cheap, predictable);
if you want semantic matching, that's a worthwhile v2.
