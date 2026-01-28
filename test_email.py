#!/usr/bin/env python3
"""
Quick test script to send a sample email.
Reads the sample_email.html we generated and sends it.

Usage:
    python test_email.py
"""

import os
import sys
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()

def main():
    # Check config
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASSWORD")
    email_to = os.getenv("EMAIL_TO")

    if not smtp_user or not smtp_pass or not email_to:
        print("ERROR: Missing email configuration in .env file")
        print()
        print("Please create a .env file with:")
        print("  SMTP_USER=youremail@gmail.com")
        print("  SMTP_PASSWORD=your_gmail_app_password")
        print("  EMAIL_TO=youremail@gmail.com")
        print()
        print("To get an App Password: https://myaccount.google.com/apppasswords")
        sys.exit(1)

    # Read the sample HTML
    html_path = os.path.join(os.path.dirname(__file__), "data", "sample_email.html")
    if not os.path.exists(html_path):
        print(f"ERROR: Sample email not found at {html_path}")
        print("Run the main test first to generate it.")
        sys.exit(1)

    with open(html_path, "r") as f:
        html_content = f.read()

    # Build email
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "TEST: UK Gazette Insolvency Report – 28 January 2025"
    msg["From"] = os.getenv("EMAIL_FROM", smtp_user)
    msg["To"] = email_to

    # Plain text fallback
    plain = "This is an HTML email. Please view in an HTML-capable email client."
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    # Send
    print(f"Sending test email to {email_to}...")
    try:
        with smtplib.SMTP(os.getenv("SMTP_HOST", "smtp.gmail.com"), int(os.getenv("SMTP_PORT", "587"))) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(smtp_user, smtp_pass)
            server.sendmail(msg["From"], [email_to], msg.as_string())
        print("SUCCESS! Check your inbox.")
    except smtplib.SMTPAuthenticationError as e:
        print(f"AUTHENTICATION FAILED: {e}")
        print()
        print("Make sure you're using a Gmail App Password, not your regular password.")
        print("Get one at: https://myaccount.google.com/apppasswords")
        sys.exit(1)
    except Exception as e:
        print(f"FAILED: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
