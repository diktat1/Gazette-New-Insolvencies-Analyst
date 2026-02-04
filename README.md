# UK Gazette Insolvency Analyst

Automated daily monitor for UK Gazette insolvency notices. Identifies companies entering administration, liquidation, or receivership where there may be assets or a viable business to acquire. Enriches each notice with Companies House data and website checks, scores the opportunity, and sends a daily email digest.

## What it does

1. **Fetches** new insolvency notices from The London Gazette's Atom feed
2. **Parses** each notice to extract: company name, registration number, registered address, court details, and insolvency practitioner contact info
3. **Looks up** the company on Companies House to get: status, SIC codes, accounts type, charges (secured debt), officers
4. **Checks** whether the company has a live website (suggests recent trading activity)
5. **Scores** each notice 0–100 for acquisition potential based on notice type, company substance, industry, assets signals
6. **Emails** a categorised daily report (HIGH / MEDIUM / LOW potential) with direct links and IP contact details

## Notice types covered

| Category | What it means | Why it matters |
|----------|---------------|----------------|
| Winding-up petitions | Creditor has filed a court petition | Very early stage – business may still be trading |
| Winding-up orders | Court has ordered liquidation | Liquidator will be selling assets |
| Creditors' voluntary liquidation | Directors have resolved to wind up | Assets will be sold to pay creditors |
| Administration orders | Company under court protection | Administrator often sells business as going concern |
| Appointment of administrators | Formal IP appointment | Contact the administrator directly |
| Appointment of receivers | Secured creditor enforcing charge | Receiver sells charged assets |
| Meetings of creditors | Creditors being called to vote | Early stage – opportunity to engage |
| Voluntary arrangements | Company proposing deal with creditors | May need investment/buyer |

## Opportunity scoring

Each notice gets a score from 0–100:

- **HIGH (65+)**: Administration/receivership + substantial company + asset-rich industry + website live
- **MEDIUM (40–64)**: Some positive signals but unclear substance
- **LOW (20–39)**: Likely a shell, micro-entity, or members' voluntary winding up
- **SKIP (<20)**: Already dissolved or no signals of substance

Scoring factors include: notice type, Companies House accounts quality, secured charges, SIC codes (manufacturing, retail, property, hospitality score higher), website existence, company status.

## Setup

### Prerequisites

- Python 3.10+
- A **Companies House API key** (free): register at https://developer.company-information.service.gov.uk/
- SMTP email credentials (e.g., Gmail with an App Password)

### Installation

```bash
# Clone the repo
git clone <repo-url>
cd Gazette-New-Insolvencies-Analyst

# Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your API key and email settings
```

### Configuration (.env)

```
COMPANIES_HOUSE_API_KEY=your_key_here
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=your_app_password
EMAIL_FROM=you@gmail.com
EMAIL_TO=recipient@example.com
DAILY_SEND_TIME=08:00
LOOKBACK_DAYS=1
MIN_OPPORTUNITY_SCORE=0
```

For Gmail, you need an **App Password** (not your normal password): Google Account > Security > 2-Step Verification > App Passwords.

## Usage

```bash
# Run once – analyse today's notices and send email
python main.py

# Run without sending email (print to stdout)
python main.py --no-email

# Look back 7 days
python main.py --days 7

# Save HTML report to a file
python main.py --output report.html --no-email

# Run on a daily schedule (stays running)
python main.py --schedule

# Verbose debug logging
python main.py -v --no-email
```

## Project structure

```
main.py                          # Entry point + CLI
src/
  config.py                      # Configuration from .env
  db.py                          # SQLite tracker (skip already-processed notices)
  gazette_feed.py                # Fetch + parse Gazette Atom feed
  notice_parser.py               # Extract structured data from notice HTML
  companies_house.py             # Companies House API integration
  website_finder.py              # Domain guessing + liveness check
  opportunity_scorer.py          # Heuristic scoring engine
  email_report.py                # Email generation + SMTP sending
  analyser.py                    # Orchestrator (full pipeline)
templates/
  email_report.html              # Jinja2 email template
  notice_card.html               # Individual notice card partial
data/
  gazette_tracker.db             # SQLite database (auto-created, gitignored)
```

## Known pitfalls and limitations

1. **Gazette feed availability**: The Gazette may rate-limit or block requests. The system retries with backoff, but extended downtime will cause missed notices.

2. **Notice parsing is fuzzy**: Gazette notices are semi-structured HTML, not a clean API. Company names, practitioner details, and addresses are extracted via regex/heuristics. Some notices will parse imperfectly.

3. **Company number extraction**: Not all notices include a Companies House registration number. The system falls back to name search, which may match the wrong company (common names like "ABC Services Ltd").

4. **Website detection is best-effort**: Many insolvent companies have already taken down their websites, or the domain may be parked. The domain-guessing approach (companyname.co.uk) won't find companies with creative domain names.

5. **No financial data**: Companies House public API doesn't include balance sheet figures. The "accounts type" (full, micro-entity, dormant) is a proxy for company substance but not a substitute for reading the actual filings.

6. **Personal insolvency excluded**: The current category codes focus on corporate insolvency. Individuals going bankrupt with business assets aren't captured.

7. **Timing matters**: By the time a notice appears in the Gazette, the insolvency process may already be well advanced. Administration appointments in particular may have been marketed beforehand.

8. **Members' voluntary liquidation**: These are solvent wind-downs where the shareholders get the proceeds. The system de-scores these, but they still appear in the feed since the category codes overlap.

9. **Scottish and NI companies**: Company number formats differ (SC/NI prefix). The system handles these but Companies House data coverage may vary.

10. **Rate limits**: Companies House allows 600 requests per 5 minutes. With a large batch of notices, the system may hit this limit. It backs off automatically but processing will be slower.

## Gazette RSS feed notes

Your original feed URL uses the long-form category codes (G305010100 etc.) with duplicates. The system uses the same codes, deduplicated. The Gazette also supports:
- Short 2-digit category codes: `categorycode=24` (all corporate insolvency)
- The `/insolvency/notice/data.feed` endpoint which pre-filters to insolvency
- Date filtering via `start-publish-date` and `end-publish-date`

The system uses date-filtered queries rather than relying on "latest 100" to ensure nothing is missed.

## Running in production

### GitHub Actions (recommended)

The repo includes a GitHub Actions workflow that runs daily at 7:00 UTC. To enable:

1. Go to your repo on GitHub → **Settings** → **Secrets and variables** → **Actions**
2. Add these **Repository secrets**:

| Secret | Description |
|--------|-------------|
| `COMPANIES_HOUSE_API_KEY` | Your Companies House API key |
| `SMTP_USER` | Your email address (e.g., you@yourdomain.com) |
| `SMTP_PASSWORD` | Gmail App Password or SMTP password |
| `EMAIL_TO` | Where to send the daily summary |

3. Go to **Actions** tab → Enable workflows if prompted
4. Optionally click "Run workflow" to test manually

The workflow:
- Runs daily at 7:00 UTC (≈8:00 UK time)
- Sends you a summary email of new insolvencies
- Sends outreach emails to qualified Insolvency Practitioners
- Commits the outreach database back to the repo (tracks contact history)

### Other options

1. **Cron job**: `0 8 * * * cd /path/to/project && .venv/bin/python main.py`
2. **Built-in scheduler**: `python main.py --schedule` (keeps running)
3. **Systemd service**: Create a unit file for the scheduler
4. **Cloud function**: Deploy as an AWS Lambda / GCP Cloud Function triggered by CloudWatch/Cloud Scheduler

## Automated Outreach System

The outreach system automatically contacts Insolvency Practitioners about high-scoring opportunities.

### How it works

1. **Qualification**: Only companies scoring ≥40 with valid IP emails are queued
2. **Batching**: Multiple companies from the same IP firm are grouped into one email
3. **Warmup**: Starts with 5 emails/day, gradually increases to avoid spam filters
4. **Follow-ups**: Sends polite follow-ups at day 7 and day 14 if no reply
5. **Tracking**: SQLite database tracks all contacts to prevent duplicates

### CLI commands

```bash
# View outreach status and queue
python outreach.py status

# Preview what would be sent
python outreach.py preview

# Send pending outreach (respects warmup limits)
python outreach.py send

# Process follow-ups
python outreach.py followups

# Mark a reply received
python outreach.py reply <batch_id>

# Block an email/domain from future outreach
python outreach.py block <email_or_domain>
```

### Running with outreach

```bash
# Full pipeline: analyse + report + outreach
python main.py --outreach

# Dry run (no emails sent)
python main.py --outreach-dry-run
```

See `docs/OUTREACH_SYSTEM_DESIGN.md` for detailed architecture.
