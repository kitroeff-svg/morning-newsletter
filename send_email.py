#!/usr/bin/env python3
"""
Send the daily briefing newsletter via Gmail SMTP.

Setup (one time):
1. Go to https://myaccount.google.com/apppasswords
2. Generate an app password for "Mail"
3. Save it in ~/.newsletter-creds as two lines:
   kitroeff@gmail.com
   xxxx xxxx xxxx xxxx
"""

import smtplib
import os
import re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

NEWSLETTER_DIR = os.path.dirname(os.path.abspath(__file__))
HTML_FILE = os.path.join(NEWSLETTER_DIR, "index.html")
CREDS_FILE = os.path.expanduser("~/.newsletter-creds")
RECIPIENTS = ["kitroeff@gmail.com", "hillarylperlman@gmail.com"]


def reorder_for_email(html_content):
    """Move the Right/Left synthesis sections to just after the header."""

    # For email clients: inline the Google Fonts import won't work reliably.
    # Swap to web-safe fallbacks and inline key styles.
    # Also strip CSS custom properties (var()) for email compatibility.

    # Extract sections by finding their comment markers
    def extract_section(html, start_marker, end_marker):
        start = html.find(start_marker)
        end = html.find(end_marker, start + 1)
        if start == -1 or end == -1:
            return "", html
        # Include from start_marker up to (but not including) end_marker
        section = html[start:end]
        remaining = html[:start] + html[end:]
        return section, remaining

    # Pull out: the right section, left section, trump section, and their surrounding dividers
    # We need to grab the divider before "THE RIGHT" and the divider before "ALSO NOTED"

    # Find the first divider (before Trump)
    divider_html = '<div class="divider"><div class="divider-dot"></div><div class="divider-dot"></div><div class="divider-dot"></div></div>'

    # Extract the right and left synthesis sections
    right_start = html_content.find('<!-- ═══════════ THE RIGHT ═══════════ -->')
    left_start = html_content.find('<!-- ═══════════ THE LEFT ═══════════ -->')
    left_section_end = html_content.find('<!-- ═══════════ ALSO NOTED ═══════════ -->')

    if right_start == -1 or left_start == -1 or left_section_end == -1:
        return html_content  # Can't find markers, return as-is

    # Find the divider just before THE RIGHT (it's the one after Trump section)
    divider_before_right = html_content.rfind(divider_html, 0, right_start)

    # Find the divider between LEFT and ALSO NOTED
    divider_before_also = html_content.rfind(divider_html, left_start, left_section_end)

    # Extract the right+left block (from divider before right through divider before also noted)
    if divider_before_right == -1:
        divider_before_right = right_start
    if divider_before_also == -1:
        block_end = left_section_end
    else:
        block_end = divider_before_also + len(divider_html)

    right_left_block = html_content[divider_before_right:block_end]

    # Remove that block from original position
    modified = html_content[:divider_before_right] + html_content[block_end:]

    # Insert right after </header>
    header_end = modified.find('</header>')
    if header_end != -1:
        insert_pos = header_end + len('</header>')
        modified = modified[:insert_pos] + '\n\n' + right_left_block + '\n' + modified[insert_pos:]

    return modified


def inline_for_email(html_content):
    """Make HTML more email-client friendly."""
    # Replace var() references with actual colors
    replacements = {
        'var(--bg)': '#f7f5f0',
        'var(--fg)': '#2c2a25',
        'var(--muted)': '#8a857c',
        'var(--light-muted)': '#b5b0a6',
        'var(--border)': '#e4e0d8',
        'var(--card-bg)': '#fffef9',
        'var(--warm-white)': '#fdfcf7',
        'var(--sage)': '#6b7f6b',
        'var(--steel)': '#5c7a8a',
        'var(--terra)': '#8a6f5e',
        'var(--clay)': '#9a7b6b',
        'var(--umber)': '#7a6b5a',
        'var(--indigo)': '#6b6a7a',
        'var(--dusty-rose)': '#8a6b7a',
    }
    for var, val in replacements.items():
        html_content = html_content.replace(var, val)

    # Remove the :root block
    html_content = re.sub(r':root\s*\{[^}]+\}', '', html_content)

    # Replace Google Fonts with safe fallbacks
    html_content = re.sub(r"font-family:\s*'Instrument Serif'[^;]*;", "font-family: Georgia, 'Times New Roman', serif;", html_content)
    html_content = re.sub(r"font-family:\s*'Newsreader'[^;]*;", "font-family: Georgia, 'Times New Roman', serif;", html_content)
    html_content = re.sub(r"font-family:\s*'Inter'[^;]*;", "font-family: -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Arial, sans-serif;", html_content)

    return html_content


def send_newsletter():
    # Read credentials
    if not os.path.exists(CREDS_FILE):
        print(f"Error: Credentials file not found at {CREDS_FILE}")
        print("Create it with two lines: email and app password")
        print("Get an app password at https://myaccount.google.com/apppasswords")
        return False

    with open(CREDS_FILE, 'r') as f:
        lines = f.read().strip().split('\n')
    if len(lines) < 2:
        print("Error: Credentials file must have two lines (email and app password)")
        return False

    sender_email = lines[0].strip()
    app_password = lines[1].strip()

    # Read HTML
    if not os.path.exists(HTML_FILE):
        print(f"Error: Newsletter HTML not found at {HTML_FILE}")
        return False

    with open(HTML_FILE, 'r', encoding='utf-8') as f:
        html_content = f.read()

    # Reorder: put left/right summaries at top
    html_content = reorder_for_email(html_content)

    # Make email-client friendly
    html_content = inline_for_email(html_content)

    today = datetime.now().strftime("%A, %B %d")

    for recipient in RECIPIENTS:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"Daily Briefing — {today}"
        msg['From'] = f"Daily Briefing <{sender_email}>"
        msg['To'] = recipient

        # Plain text fallback
        plain_text = f"Daily Briefing for {today}\n\nOpen this email in an HTML-capable client to read the full briefing."
        msg.attach(MIMEText(plain_text, 'plain'))
        msg.attach(MIMEText(html_content, 'html'))

        try:
            with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
                server.login(sender_email, app_password)
                server.sendmail(sender_email, recipient, msg.as_string())
            print(f"  Sent to {recipient}")
        except Exception as e:
            print(f"  Error sending to {recipient}: {e}")
            return False

    return True


if __name__ == "__main__":
    print("Sending daily briefing...")
    if send_newsletter():
        print("Done!")
    else:
        print("Failed to send.")
