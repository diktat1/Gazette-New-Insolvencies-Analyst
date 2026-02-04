# Automated Outreach System - Design Document

## Overview

An intelligent outreach system for personal deal sourcing that:
- Sends personalized emails to Insolvency Practitioners (IPs)
- Tracks all communications and responses
- Prevents spam through smart rate limiting and deduplication
- Provides daily visibility into pipeline status

---

## Core Design Principles

1. **Quality over quantity** - Only contact for genuinely interesting opportunities
2. **Respect practitioners' time** - No spam, smart throttling, easy opt-out
3. **Personal touch** - Emails should feel hand-written, not automated
4. **Full visibility** - Know exactly what's happening at a glance
5. **Safe defaults** - Conservative settings, manual overrides available

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                     DAILY PIPELINE                                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  1. ANALYSE          2. QUALIFY           3. QUEUE                  │
│  ┌──────────┐       ┌──────────┐        ┌──────────┐               │
│  │ Gazette  │──────▶│ Outreach │───────▶│ Email    │               │
│  │ Notices  │       │ Rules    │        │ Queue    │               │
│  └──────────┘       └──────────┘        └──────────┘               │
│       │                  │                   │                      │
│       │                  │                   │                      │
│       ▼                  ▼                   ▼                      │
│  ┌──────────┐       ┌──────────┐        ┌──────────┐               │
│  │ Score &  │       │ Check    │        │ Schedule │               │
│  │ Enrich   │       │ Cooldowns│        │ & Send   │               │
│  └──────────┘       │ Blocklist│        └──────────┘               │
│                     │ Duplicates│             │                     │
│                     └──────────┘             │                      │
│                                              ▼                      │
│  4. TRACK            5. FOLLOW-UP       ┌──────────┐               │
│  ┌──────────┐       ┌──────────┐        │ SMTP     │               │
│  │ Response │◀──────│ Auto     │◀───────│ Send     │               │
│  │ Detection│       │ Follow-up│        └──────────┘               │
│  └──────────┘       └──────────┘                                    │
│       │                                                             │
│       ▼                                                             │
│  ┌──────────────────────────────────────────────────────────┐      │
│  │              DAILY DASHBOARD / SUMMARY                    │      │
│  │  - New opportunities    - Emails sent today              │      │
│  │  - Awaiting response    - Replies received               │      │
│  │  - Follow-ups due       - Pipeline value                 │      │
│  └──────────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Database Schema

```sql
-- Track all outreach activity
CREATE TABLE outreach_contacts (
    id INTEGER PRIMARY KEY,

    -- Who
    ip_name TEXT NOT NULL,
    ip_email TEXT NOT NULL,
    ip_firm TEXT,
    ip_phone TEXT,

    -- What
    notice_id TEXT NOT NULL,
    company_name TEXT NOT NULL,
    company_number TEXT,
    notice_type TEXT,
    opportunity_score INTEGER,

    -- Status tracking
    status TEXT DEFAULT 'queued',  -- queued, sent, opened, replied, meeting, won, lost, no_response

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    queued_at TIMESTAMP,
    sent_at TIMESTAMP,
    opened_at TIMESTAMP,
    replied_at TIMESTAMP,

    -- Email content (for reference)
    subject TEXT,
    body_preview TEXT,  -- First 200 chars

    -- Follow-up tracking
    follow_up_count INTEGER DEFAULT 0,
    next_follow_up_date DATE,

    -- User notes
    notes TEXT,

    UNIQUE(notice_id, ip_email)  -- Prevent duplicate outreach for same notice
);

-- Track IP-level rate limiting
CREATE TABLE ip_contact_history (
    id INTEGER PRIMARY KEY,
    ip_email TEXT NOT NULL,
    ip_firm TEXT,
    last_contacted_at TIMESTAMP,
    total_contacts INTEGER DEFAULT 0,
    total_replies INTEGER DEFAULT 0,
    is_blocked INTEGER DEFAULT 0,  -- User manually blocked
    block_reason TEXT,

    UNIQUE(ip_email)
);

-- Blocklist (opt-outs, bounces, complaints)
CREATE TABLE outreach_blocklist (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    reason TEXT,  -- 'opt_out', 'bounce', 'complaint', 'manual'
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Email templates
CREATE TABLE email_templates (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    notice_type TEXT,  -- 'administration', 'liquidation', 'receivership', 'default'
    subject_template TEXT NOT NULL,
    body_template TEXT NOT NULL,
    is_follow_up INTEGER DEFAULT 0,
    follow_up_number INTEGER,  -- 1, 2, 3 for sequential follow-ups
    is_active INTEGER DEFAULT 1
);

-- Daily summary log
CREATE TABLE daily_summaries (
    id INTEGER PRIMARY KEY,
    date DATE NOT NULL UNIQUE,
    notices_found INTEGER,
    notices_qualified INTEGER,
    emails_queued INTEGER,
    emails_sent INTEGER,
    replies_received INTEGER,
    summary_json TEXT  -- Full stats as JSON
);
```

---

## Anti-Spam Logic

### 1. Qualification Gates (Before Queuing)

```python
def should_queue_outreach(notice, ip_contact) -> tuple[bool, str]:
    """
    Returns (should_queue, reason) - all checks must pass
    """

    # Gate 1: Minimum quality threshold
    if notice.opportunity_score < CONFIG.MIN_OUTREACH_SCORE:  # Default: 50
        return False, f"Score {notice.opportunity_score} below threshold {CONFIG.MIN_OUTREACH_SCORE}"

    # Gate 2: Must have valid IP email
    if not ip_contact.email or not is_valid_email(ip_contact.email):
        return False, "No valid IP email found"

    # Gate 3: Check blocklist
    if is_blocked(ip_contact.email):
        return False, "IP email is on blocklist"

    # Gate 4: IP cooldown - don't contact same IP within N days
    last_contact = get_last_contact_date(ip_contact.email)
    if last_contact and days_since(last_contact) < CONFIG.IP_COOLDOWN_DAYS:  # Default: 14
        return False, f"IP contacted {days_since(last_contact)} days ago (cooldown: {CONFIG.IP_COOLDOWN_DAYS})"

    # Gate 5: Firm-level daily limit
    firm_today_count = get_firm_contacts_today(ip_contact.firm)
    if firm_today_count >= CONFIG.MAX_PER_FIRM_PER_DAY:  # Default: 2
        return False, f"Firm {ip_contact.firm} already contacted {firm_today_count}x today"

    # Gate 6: Global daily limit
    total_today = get_total_contacts_today()
    if total_today >= CONFIG.MAX_EMAILS_PER_DAY:  # Default: 10
        return False, f"Daily limit reached ({total_today}/{CONFIG.MAX_EMAILS_PER_DAY})"

    # Gate 7: Don't contact about already-dissolved companies
    if notice.ch_status in ['dissolved', 'closed']:
        return False, "Company already dissolved"

    # Gate 8: Skip if we already contacted this IP about this notice
    if already_contacted(notice.notice_id, ip_contact.email):
        return False, "Already contacted this IP about this notice"

    return True, "Qualified"
```

### 2. Rate Limiting Configuration

```python
# Default conservative settings for personal use
OUTREACH_CONFIG = {
    # Quality thresholds
    'MIN_OUTREACH_SCORE': 50,           # Only contact for score >= 50
    'PRIORITY_SCORE_THRESHOLD': 70,     # High priority gets sent first

    # Rate limits
    'MAX_EMAILS_PER_DAY': 10,           # Total daily limit
    'MAX_PER_FIRM_PER_DAY': 2,          # Per IP firm daily limit
    'IP_COOLDOWN_DAYS': 14,             # Days before re-contacting same IP
    'FIRM_COOLDOWN_DAYS': 7,            # Days before 3rd+ email to same firm

    # Timing
    'SEND_WINDOW_START': '09:00',       # Only send during business hours
    'SEND_WINDOW_END': '17:00',
    'SEND_DAYS': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'],  # Weekdays only
    'MIN_DELAY_BETWEEN_SENDS': 300,     # 5 min between emails (looks human)

    # Follow-ups
    'ENABLE_AUTO_FOLLOWUP': True,
    'FOLLOWUP_DELAY_DAYS': 7,           # Days before first follow-up
    'MAX_FOLLOWUPS': 2,                 # Maximum follow-up emails
    'FOLLOWUP_COOLDOWN_DAYS': 7,        # Days between follow-ups

    # Safety
    'REQUIRE_MANUAL_APPROVAL': False,   # If True, queue but don't send without approval
    'DRY_RUN_MODE': True,               # Start in dry-run, don't actually send
}
```

### 3. Smart Sending Schedule

```python
def get_next_send_slot() -> datetime:
    """
    Calculate next available send time respecting:
    - Business hours only (9am-5pm)
    - Weekdays only
    - Minimum delay between sends
    - Random jitter (looks more human)
    """
    now = datetime.now()

    # If outside business hours, schedule for next morning
    if now.hour < 9:
        next_slot = now.replace(hour=9, minute=random.randint(0, 30))
    elif now.hour >= 17:
        next_slot = (now + timedelta(days=1)).replace(hour=9, minute=random.randint(0, 30))
    else:
        # During business hours - add delay from last send
        last_send = get_last_send_time()
        min_next = last_send + timedelta(seconds=CONFIG.MIN_DELAY_BETWEEN_SENDS)
        next_slot = max(now, min_next)
        # Add random jitter (1-10 minutes)
        next_slot += timedelta(minutes=random.randint(1, 10))

    # Skip weekends
    while next_slot.weekday() >= 5:  # Saturday=5, Sunday=6
        next_slot += timedelta(days=1)

    return next_slot
```

---

## Email Templates

### Template Variables Available

```python
{
    # Company info
    'company_name': 'ABC Manufacturing Ltd',
    'company_number': '12345678',
    'trading_name': 'ABC Mfg',
    'registered_address': '123 Industrial Estate, Birmingham B1 1AA',
    'sector': 'Manufacturing',
    'estimated_assets': ['Machinery & Equipment', 'Stock/Inventory', 'Property Lease'],

    # Notice info
    'notice_type': 'Administration',
    'notice_date': '2024-01-15',
    'court_name': 'High Court of Justice',

    # IP info
    'ip_name': 'John Smith',
    'ip_firm': 'Big Four LLP',
    'ip_role': 'Joint Administrator',

    # Personalization
    'sender_name': 'Your Name',
    'sender_company': 'Your Company',
    'sender_phone': '+44 7xxx xxx xxx',

    # Computed
    'days_since_notice': 3,
}
```

### Initial Outreach Template (Administration)

```
Subject: {{ company_name }} - Expression of Interest

Dear {{ ip_name }},

I noticed the recent {{ notice_type | lower }} appointment for {{ company_name }}{% if trading_name and trading_name != company_name %} (trading as {{ trading_name }}){% endif %}.

I'm actively looking to acquire {{ sector | lower }} businesses and would be interested in understanding if there's an opportunity to acquire the business or its assets.

I can move quickly on due diligence and have funds available for the right opportunity.

Would you be open to a brief call to discuss whether this might be a fit?

Best regards,
{{ sender_name }}
{{ sender_phone }}
```

### Initial Outreach Template (Liquidation)

```
Subject: {{ company_name }} - Asset Acquisition Interest

Dear {{ ip_name }},

I understand you've been appointed {{ ip_role }} for {{ company_name }}.

I'm interested in acquiring assets from {{ sector | lower }} businesses and wanted to register my interest early in the process.

{% if estimated_assets %}Specifically, I'd be interested in: {{ estimated_assets | join(', ') }}.{% endif %}

Could you let me know the timeline for any asset sale process and how best to participate?

Best regards,
{{ sender_name }}
{{ sender_phone }}
```

### Follow-up Template #1 (Day 7)

```
Subject: Re: {{ company_name }} - Following Up

Dear {{ ip_name }},

I wanted to follow up on my email from last week regarding {{ company_name }}.

I remain interested in exploring this opportunity and am happy to work around your timeline.

Would a brief call this week be possible?

Best regards,
{{ sender_name }}
{{ sender_phone }}
```

### Follow-up Template #2 (Day 14 - Final)

```
Subject: Re: {{ company_name }} - Final Follow-up

Dear {{ ip_name }},

I appreciate you're likely managing multiple cases, so I'll keep this brief.

If {{ company_name }} or its assets are still available, I'd welcome the chance to discuss. If the opportunity has passed or isn't suitable, no need to reply - I'll remove this from my list.

Best regards,
{{ sender_name }}
{{ sender_phone }}
```

---

## Edge Cases & Pitfalls

### 1. Multiple Practitioners on Same Notice

**Problem:** Notice lists 3 joint administrators - don't email all 3
**Solution:**
- Only email the first practitioner listed (usually the lead)
- Or: Email only practitioners with email addresses found
- Store all practitioners, but mark only one as "contact_primary"

```python
def select_primary_contact(practitioners: list) -> InsolvencyPractitioner:
    """Select single best contact from multiple practitioners"""
    # Prefer those with email addresses
    with_email = [p for p in practitioners if p.email]
    if not with_email:
        return practitioners[0] if practitioners else None

    # Prefer lead roles
    lead_keywords = ['lead', 'principal', 'senior']
    for p in with_email:
        if any(kw in p.role.lower() for kw in lead_keywords):
            return p

    # Default to first with email
    return with_email[0]
```

### 2. Same IP, Different Companies

**Problem:** Same IP handling 5 insolvencies this week
**Solution:**
- IP cooldown prevents spam
- But also: batch multiple opportunities into one email if same IP has multiple in queue

```python
def batch_opportunities_by_ip(queue: list) -> dict:
    """Group queued outreach by IP email for potential batching"""
    by_ip = defaultdict(list)
    for item in queue:
        by_ip[item.ip_email].append(item)

    # If IP has multiple, create single combined email
    for ip_email, items in by_ip.items():
        if len(items) > 1:
            # Combine into single "multiple opportunities" email
            create_batch_email(ip_email, items)
```

### 3. Email Bounces

**Problem:** Invalid email addresses waste sends and hurt reputation
**Solution:**
- Track bounces via SMTP response codes
- Auto-add to blocklist after bounce
- Check email format before queuing

```python
def handle_send_result(contact_id: int, result: SendResult):
    if result.status == 'bounced':
        # Add to blocklist
        add_to_blocklist(result.email, reason='bounce')
        update_contact_status(contact_id, 'bounced')
        log_warning(f"Email bounced: {result.email} - {result.error}")
    elif result.status == 'sent':
        update_contact_status(contact_id, 'sent')
        update_ip_contact_history(result.email)
```

### 4. Out-of-Office / Auto-Replies

**Problem:** Auto-replies look like responses but aren't actionable
**Solution:**
- Detect auto-reply patterns
- Don't count as "replied" status
- Still useful: confirms email is valid

```python
AUTO_REPLY_PATTERNS = [
    r'out of (the )?office',
    r'automatic reply',
    r'auto-reply',
    r'away from (my )?(email|desk)',
    r'currently (out|away|unavailable)',
    r'on (annual |paid )?leave',
    r'maternity|paternity leave',
    r'i am away',
    r'thank you for your (email|message).*will respond',
]

def is_auto_reply(subject: str, body: str) -> bool:
    text = f"{subject} {body}".lower()
    return any(re.search(pattern, text) for pattern in AUTO_REPLY_PATTERNS)
```

### 5. Practitioner Moved Firms

**Problem:** IP left firm, email bounces or goes to wrong person
**Solution:**
- Check Companies House for current IP registrations (IP number)
- Cross-reference with IP firm websites
- Track bounces and note firm changes

### 6. Already Contacted via Other Channel

**Problem:** You manually emailed or called this IP last week
**Solution:**
- Manual "log contact" feature to record external outreach
- Check before auto-sending
- CLI: `python outreach.py log --ip "john@firm.com" --note "Called, interested"`

### 7. Duplicate Companies (Same Company, Multiple Notices)

**Problem:** Amended notice, or multiple notice types for same company
**Solution:**
- Dedupe by company number before outreach
- Keep most recent/relevant notice
- Don't re-contact about same company within 30 days

### 8. No Email Found in Notice

**Problem:** Many notices don't include practitioner email
**Solution:**
- Look up IP firm website and find contact
- Use IP number to find registration and contact
- Queue for manual research if high-value opportunity

### 9. GDPR / Legal Compliance (UK)

**Problem:** B2B cold email has rules
**Solution:**
- B2B legitimate interest generally permits cold outreach
- Must include: who you are, easy opt-out
- Honor opt-outs immediately
- Don't contact personal emails (only business)
- Keep records of consent/opt-out

```python
def get_email_footer() -> str:
    return """
---
This email was sent because you're listed as the appointed practitioner for an insolvency case.
If you'd prefer not to receive these emails, simply reply with "unsubscribe" and I'll remove you from my list.
"""
```

### 10. Email Deliverability

**Problem:** Emails going to spam
**Solutions:**
- Use proper SMTP authentication
- Set up SPF, DKIM, DMARC for sending domain
- Don't send too many too fast
- Avoid spam trigger words
- Use plain text or simple HTML (not marketing-style)
- Personalize subject lines
- Keep sending volume low and consistent

---

## Daily Dashboard / User Experience

### CLI Commands

```bash
# View today's summary
python outreach.py status

# View pipeline
python outreach.py pipeline

# View queue (what will be sent)
python outreach.py queue

# Approve queued emails (if manual approval enabled)
python outreach.py approve --all
python outreach.py approve --id 123

# Skip/reject a queued email
python outreach.py skip --id 123 --reason "Not interested in this sector"

# View sent emails awaiting response
python outreach.py awaiting

# Log a manual contact
python outreach.py log --email "ip@firm.com" --note "Called, very interested"

# Update status after response
python outreach.py update --id 123 --status replied --note "Interested, sending teaser"

# Block an IP (opt-out)
python outreach.py block --email "ip@firm.com" --reason "Requested no contact"

# View full history for an IP
python outreach.py history --email "ip@firm.com"

# Run outreach in dry-run mode (shows what would send)
python outreach.py send --dry-run

# Actually send queued emails
python outreach.py send

# Generate weekly report
python outreach.py report --week
```

### Daily Status Output

```
╔══════════════════════════════════════════════════════════════════════╗
║                    OUTREACH STATUS - 2024-01-15                       ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                       ║
║  TODAY'S ACTIVITY                                                     ║
║  ├─ New notices analysed:     12                                      ║
║  ├─ Qualified for outreach:    4                                      ║
║  ├─ Queued for sending:        3  (1 skipped: IP cooldown)           ║
║  ├─ Emails sent:               3                                      ║
║  └─ Replies received:          1  ✓                                   ║
║                                                                       ║
║  PIPELINE SUMMARY                                                     ║
║  ├─ Awaiting response:        15  (oldest: 12 days)                  ║
║  ├─ Follow-ups due today:      2                                      ║
║  ├─ In discussion:             3                                      ║
║  ├─ Meeting scheduled:         1                                      ║
║  └─ Closed (won/lost):        8/23                                   ║
║                                                                       ║
║  TODAY'S QUEUE (3 emails)                                            ║
║  ┌────────────────────────────────────────────────────────────────┐  ║
║  │ #1  ABC Manufacturing Ltd          Score: 78  HIGH             │  ║
║  │     → John Smith (Big Four LLP)    Administration              │  ║
║  │     Scheduled: 09:15                                           │  ║
║  ├────────────────────────────────────────────────────────────────┤  ║
║  │ #2  XYZ Retail Group               Score: 65  MEDIUM           │  ║
║  │     → Jane Doe (Regional IP Ltd)   CVL                         │  ║
║  │     Scheduled: 09:47                                           │  ║
║  ├────────────────────────────────────────────────────────────────┤  ║
║  │ #3  Smith Engineering              Score: 52  MEDIUM           │  ║
║  │     → Bob Wilson (Local LLP)       Liquidation                 │  ║
║  │     Scheduled: 10:22                                           │  ║
║  └────────────────────────────────────────────────────────────────┘  ║
║                                                                       ║
║  RECENT REPLIES                                                       ║
║  • DEF Services Ltd - "Interested, please send more info"  (2h ago)  ║
║                                                                       ║
║  ACTIONS NEEDED                                                       ║
║  ⚠ 2 follow-ups due today (run: python outreach.py followups)        ║
║  ⚠ 1 reply needs response (DEF Services Ltd)                         ║
║                                                                       ║
╚══════════════════════════════════════════════════════════════════════╝
```

### Daily Email Summary

Option to receive a daily summary email at end of day:

```
Subject: Outreach Summary - 15 Jan 2024

TODAY'S ACTIVITY
• 3 emails sent (ABC Manufacturing, XYZ Retail, Smith Engineering)
• 1 reply received (DEF Services - interested!)
• 2 follow-ups sent

ACTIONS NEEDED
• Reply to DEF Services Ltd - they're interested
• 2 contacts have been waiting 14+ days with no response

PIPELINE
• 15 awaiting response
• 3 in active discussion
• Win rate this month: 12%

---
Full dashboard: python outreach.py status
```

---

## Implementation Phases

### Phase 1: Core Infrastructure (Week 1)
- [ ] Database schema and migrations
- [ ] Configuration system
- [ ] Basic CLI structure
- [ ] Outreach qualification logic (all gates)
- [ ] Email template system

### Phase 2: Sending & Tracking (Week 2)
- [ ] Email queue management
- [ ] SMTP sending with retry logic
- [ ] Send scheduling (business hours, delays)
- [ ] Status tracking
- [ ] Blocklist management

### Phase 3: Follow-ups & Responses (Week 3)
- [ ] Auto follow-up scheduling
- [ ] Auto-reply detection
- [ ] Manual status updates
- [ ] Reply logging

### Phase 4: Dashboard & UX (Week 4)
- [ ] Daily status command
- [ ] Pipeline view
- [ ] History view
- [ ] Daily summary email
- [ ] Weekly report

### Phase 5: Polish & Safety (Week 5)
- [ ] Dry-run mode testing
- [ ] Manual approval workflow
- [ ] Comprehensive logging
- [ ] Error handling
- [ ] Documentation

---

## File Structure

```
src/
├── outreach/
│   ├── __init__.py
│   ├── manager.py          # Main orchestration
│   ├── qualifier.py        # Qualification gates
│   ├── queue.py            # Queue management
│   ├── sender.py           # SMTP sending
│   ├── tracker.py          # Status tracking
│   ├── followup.py         # Follow-up logic
│   ├── templates.py        # Template rendering
│   ├── db.py               # Database operations
│   └── cli.py              # CLI commands
├── outreach_config.py      # Configuration
└── outreach_main.py        # Entry point

templates/
├── outreach/
│   ├── initial_admin.txt
│   ├── initial_liquidation.txt
│   ├── initial_cvl.txt
│   ├── followup_1.txt
│   ├── followup_2.txt
│   └── batch_multiple.txt

data/
└── outreach.db             # SQLite database
```

---

## Configuration File

```python
# outreach_config.py

OUTREACH_CONFIG = {
    # Your details (for email signatures)
    'SENDER_NAME': 'Your Name',
    'SENDER_COMPANY': 'Your Company',  # Optional
    'SENDER_PHONE': '+44 7xxx xxx xxx',
    'SENDER_EMAIL': 'you@yourdomain.com',

    # Quality thresholds
    'MIN_OUTREACH_SCORE': 50,
    'PRIORITY_SCORE_THRESHOLD': 70,

    # Rate limits (conservative defaults)
    'MAX_EMAILS_PER_DAY': 10,
    'MAX_PER_FIRM_PER_DAY': 2,
    'IP_COOLDOWN_DAYS': 14,

    # Timing
    'SEND_WINDOW_START': '09:00',
    'SEND_WINDOW_END': '17:00',
    'SEND_DAYS': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'],
    'MIN_DELAY_BETWEEN_SENDS_SECONDS': 300,

    # Follow-ups
    'ENABLE_AUTO_FOLLOWUP': True,
    'FOLLOWUP_DELAY_DAYS': 7,
    'MAX_FOLLOWUPS': 2,

    # Safety
    'DRY_RUN_MODE': True,  # Start with this ON
    'REQUIRE_MANUAL_APPROVAL': False,

    # Target sectors (optional - leave empty for all)
    'TARGET_SECTORS': [],  # e.g., ['Manufacturing', 'Retail', 'Construction']

    # Daily summary
    'SEND_DAILY_SUMMARY_EMAIL': True,
    'DAILY_SUMMARY_TIME': '18:00',
}
```

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Marked as spam | Low volume, business hours, personalization, proper authentication |
| IP complaints | Easy opt-out, honor immediately, professional tone |
| Legal issues | B2B legitimate interest, proper identification, records |
| Reputation damage | Conservative limits, quality threshold, no aggressive follow-up |
| Technical failures | Retry logic, error logging, dry-run testing |
| Over-automation | Manual approval option, status visibility, easy override |

---

## Success Metrics

Track these to measure effectiveness:

- **Response rate**: % of emails that get a reply
- **Meeting rate**: % of outreach that leads to a call
- **Conversion rate**: % of outreach that leads to a deal
- **Time to response**: Average days between send and reply
- **Opt-out rate**: % of IPs who unsubscribe (should be <5%)
- **Bounce rate**: % of invalid emails (should be <2%)

---

## Questions Before Implementation

1. **Email domain**: Will you send from a personal email or company domain?
2. **Volume expectations**: How many opportunities per week do you expect to pursue?
3. **Target sectors**: Any specific sectors to focus on or exclude?
4. **Manual vs auto**: Start with manual approval for each send, or trust the automation?
5. **Follow-up style**: Aggressive (2 follow-ups) or gentle (1 follow-up)?
6. **Response handling**: Will you monitor replies manually, or want auto-detection?
