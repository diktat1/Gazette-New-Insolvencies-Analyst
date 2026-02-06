"""
Static HTML dashboard generator for outreach status.

Generates a standalone HTML file that can be:
- Viewed locally
- Hosted on GitHub Pages
- Attached to summary emails

This is a lightweight alternative to a full web dashboard
that works well with the GitHub Actions-based workflow.
"""

import os
from datetime import datetime, date
from typing import Optional

from src.outreach.db import (
    get_all_batches,
    get_pipeline_stats,
    get_warmup_stats,
    get_warmup_limit,
    get_tracking_stats,
    get_blocklist,
    OutreachBatch,
)


def generate_dashboard_html(output_path: Optional[str] = None) -> str:
    """
    Generate a static HTML dashboard with outreach status.

    Args:
        output_path: Optional path to write the HTML file

    Returns:
        The generated HTML string
    """
    # Gather data
    batches = get_all_batches(limit=50)
    pipeline = get_pipeline_stats()
    warmup = get_warmup_stats()
    warmup_limit = get_warmup_limit()
    tracking = get_tracking_stats()
    blocklist = get_blocklist()

    # Calculate derived stats
    domain_age = warmup.get('domain_age_days', 0)
    if domain_age < 7:
        warmup_week = 1
    elif domain_age < 14:
        warmup_week = 2
    elif domain_age < 21:
        warmup_week = 3
    elif domain_age < 28:
        warmup_week = 4
    else:
        warmup_week = 5

    # Generate HTML
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Outreach Dashboard - {date.today().isoformat()}</title>
    <style>
        :root {{
            --primary: #2563eb;
            --success: #16a34a;
            --warning: #d97706;
            --danger: #dc2626;
            --bg: #f8fafc;
            --card-bg: #ffffff;
            --text: #1e293b;
            --text-muted: #64748b;
            --border: #e2e8f0;
        }}
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
            padding: 20px;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        header {{
            text-align: center;
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 2px solid var(--primary);
        }}
        header h1 {{
            color: var(--primary);
            font-size: 28px;
            margin-bottom: 5px;
        }}
        header .date {{
            color: var(--text-muted);
            font-size: 14px;
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        .stat-card {{
            background: var(--card-bg);
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }}
        .stat-card h3 {{
            font-size: 12px;
            text-transform: uppercase;
            color: var(--text-muted);
            margin-bottom: 8px;
        }}
        .stat-card .value {{
            font-size: 32px;
            font-weight: 700;
            color: var(--primary);
        }}
        .stat-card .subtext {{
            font-size: 13px;
            color: var(--text-muted);
            margin-top: 5px;
        }}
        .stat-card.success .value {{ color: var(--success); }}
        .stat-card.warning .value {{ color: var(--warning); }}
        .stat-card.danger .value {{ color: var(--danger); }}
        .section {{
            background: var(--card-bg);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }}
        .section h2 {{
            font-size: 18px;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 1px solid var(--border);
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid var(--border);
        }}
        th {{
            font-weight: 600;
            color: var(--text-muted);
            font-size: 12px;
            text-transform: uppercase;
        }}
        .status-badge {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
        }}
        .status-queued {{ background: #fef3c7; color: #92400e; }}
        .status-approved {{ background: #dbeafe; color: #1e40af; }}
        .status-sent {{ background: #dcfce7; color: #166534; }}
        .status-replied {{ background: #d1fae5; color: #065f46; }}
        .status-closed {{ background: #f1f5f9; color: #475569; }}
        .progress-bar {{
            background: var(--border);
            border-radius: 8px;
            height: 8px;
            overflow: hidden;
        }}
        .progress-bar .fill {{
            background: var(--primary);
            height: 100%;
            transition: width 0.3s;
        }}
        .warmup-info {{
            display: flex;
            align-items: center;
            gap: 15px;
            margin-top: 10px;
        }}
        .warmup-label {{
            font-size: 13px;
            color: var(--text-muted);
        }}
        .no-data {{
            text-align: center;
            padding: 40px;
            color: var(--text-muted);
        }}
        footer {{
            text-align: center;
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid var(--border);
            font-size: 12px;
            color: var(--text-muted);
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Outreach Dashboard</h1>
            <p class="date">Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
        </header>

        <div class="stats-grid">
            <div class="stat-card">
                <h3>Pending</h3>
                <div class="value">{pipeline.get('queued_count', 0) + pipeline.get('approved_count', 0)}</div>
                <p class="subtext">{pipeline.get('queued_count', 0)} queued, {pipeline.get('approved_count', 0)} approved</p>
            </div>
            <div class="stat-card success">
                <h3>Sent Today</h3>
                <div class="value">{pipeline.get('sent_today', 0)}</div>
                <p class="subtext">of {warmup_limit or '∞'} daily limit</p>
            </div>
            <div class="stat-card">
                <h3>Awaiting Reply</h3>
                <div class="value">{pipeline.get('awaiting_reply', 0)}</div>
                <p class="subtext">{pipeline.get('sent_count', 0)} total sent</p>
            </div>
            <div class="stat-card success">
                <h3>Replies</h3>
                <div class="value">{pipeline.get('replied_count', 0)}</div>
                <p class="subtext">{tracking.get('reply_rate', 0):.1f}% response rate</p>
            </div>
        </div>

        <div class="section">
            <h2>Domain Warm-up Status</h2>
            <div class="warmup-info">
                <span class="warmup-label">Week {warmup_week}</span>
                <span class="warmup-label">Domain Age: {domain_age} days</span>
                <span class="warmup-label">Today: {warmup.get('today_sent', 0)}/{warmup_limit or '∞'}</span>
            </div>
            <div style="margin-top: 15px;">
                <div class="progress-bar">
                    <div class="fill" style="width: {min(100, (warmup.get('today_sent', 0) / (warmup_limit or 100)) * 100)}%"></div>
                </div>
            </div>
        </div>

        <div class="section">
            <h2>Email Performance</h2>
            <div class="stats-grid" style="margin-bottom: 0;">
                <div class="stat-card">
                    <h3>Open Rate</h3>
                    <div class="value">{tracking.get('open_rate', 0):.1f}%</div>
                    <p class="subtext">{tracking.get('total_opened', 0)} of {tracking.get('total_sent', 0)} opened</p>
                </div>
                <div class="stat-card">
                    <h3>Click Rate</h3>
                    <div class="value">{tracking.get('click_rate', 0):.1f}%</div>
                    <p class="subtext">{tracking.get('total_clicked', 0)} clicked</p>
                </div>
                <div class="stat-card success">
                    <h3>Reply Rate</h3>
                    <div class="value">{tracking.get('reply_rate', 0):.1f}%</div>
                    <p class="subtext">{tracking.get('total_replied', 0)} replies</p>
                </div>
            </div>
        </div>

        <div class="section">
            <h2>Recent Batches</h2>
            {_render_batches_table(batches)}
        </div>

        <div class="section">
            <h2>Blocklist ({len(blocklist)} entries)</h2>
            {_render_blocklist_table(blocklist) if blocklist else '<p class="no-data">No blocked emails</p>'}
        </div>

        <footer>
            <p>Gazette Insolvency Analyst - Outreach System</p>
        </footer>
    </div>
</body>
</html>
"""

    # Write to file if path specified
    if output_path:
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        with open(output_path, 'w') as f:
            f.write(html)

    return html


def _render_batches_table(batches: list[OutreachBatch]) -> str:
    """Render the batches table HTML."""
    if not batches:
        return '<p class="no-data">No batches yet</p>'

    rows = ""
    for batch in batches[:20]:  # Limit to 20 most recent
        status_class = f"status-{batch.status}"
        notices = batch.notices
        company_names = ", ".join(n.get('company_name', 'Unknown')[:30] for n in notices[:2])
        if len(notices) > 2:
            company_names += f" +{len(notices) - 2} more"

        primary = batch.primary_recipient
        recipient_email = primary.get('email', 'Unknown') if primary else 'Unknown'

        rows += f"""
        <tr>
            <td>#{batch.id}</td>
            <td>{batch.firm[:25] if batch.firm else 'Unknown'}...</td>
            <td>{company_names}</td>
            <td>{recipient_email}</td>
            <td><span class="status-badge {status_class}">{batch.status}</span></td>
            <td>{batch.created_at[:10] if batch.created_at else '-'}</td>
            <td>{batch.follow_up_count}</td>
        </tr>
        """

    return f"""
    <table>
        <thead>
            <tr>
                <th>ID</th>
                <th>Firm</th>
                <th>Companies</th>
                <th>Recipient</th>
                <th>Status</th>
                <th>Created</th>
                <th>Follow-ups</th>
            </tr>
        </thead>
        <tbody>
            {rows}
        </tbody>
    </table>
    """


def _render_blocklist_table(blocklist: list[dict]) -> str:
    """Render the blocklist table HTML."""
    rows = ""
    for entry in blocklist[:10]:
        rows += f"""
        <tr>
            <td>{entry.get('email', 'Unknown')}</td>
            <td>{entry.get('reason', 'manual')}</td>
            <td>{entry.get('added_at', '-')[:10] if entry.get('added_at') else '-'}</td>
        </tr>
        """

    return f"""
    <table>
        <thead>
            <tr>
                <th>Email</th>
                <th>Reason</th>
                <th>Added</th>
            </tr>
        </thead>
        <tbody>
            {rows}
        </tbody>
    </table>
    """


def save_dashboard(output_dir: str = "output") -> str:
    """
    Generate and save the dashboard to a file.

    Args:
        output_dir: Directory to save the dashboard

    Returns:
        Path to the generated file
    """
    output_path = os.path.join(output_dir, f"outreach_dashboard_{date.today().isoformat()}.html")
    generate_dashboard_html(output_path)
    return output_path
