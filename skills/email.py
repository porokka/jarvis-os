"""
JARVIS Skill — Email via SMTP/IMAP.

Send emails and read inbox. Supports any email provider
(Gmail, Outlook, custom SMTP).

Config: config/email.json
Gmail setup: enable "App Passwords" in Google account security.
"""

import json
import email
import email.mime.text
import email.mime.multipart
import imaplib
import smtplib
from datetime import datetime
from pathlib import Path

SKILL_NAME = "email"
SKILL_DESCRIPTION = "Email — send, read inbox, search via SMTP/IMAP"

CONFIG_FILE = Path(__file__).parent.parent / "config" / "email.json"
VAULT_DIR = Path("/mnt/d/Jarvis_vault") if __import__("os").name != "nt" else Path("D:/Jarvis_vault")


def _load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _send_email(to: str, subject: str, body: str) -> str:
    """Send an email via SMTP."""
    cfg = _load_config()
    smtp_host = cfg.get("smtp_host", "smtp.gmail.com")
    smtp_port = cfg.get("smtp_port", 587)
    username = cfg.get("username", "")
    password = cfg.get("password", "")
    from_name = cfg.get("from_name", "JARVIS")

    if not username or not password:
        return "Email not configured. Add credentials to config/email.json"

    try:
        msg = email.mime.multipart.MIMEMultipart()
        msg["From"] = f"{from_name} <{username}>"
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(email.mime.text.MIMEText(body, "plain"))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(username, password)
            server.send_message(msg)

        return f"Email sent to {to}: {subject}"
    except Exception as e:
        return f"Email send error: {e}"


def _read_inbox(count: int = 10, folder: str = "INBOX") -> str:
    """Read recent emails via IMAP."""
    cfg = _load_config()
    imap_host = cfg.get("imap_host", "imap.gmail.com")
    imap_port = cfg.get("imap_port", 993)
    username = cfg.get("username", "")
    password = cfg.get("password", "")

    if not username or not password:
        return "Email not configured."

    try:
        with imaplib.IMAP4_SSL(imap_host, imap_port) as mail:
            mail.login(username, password)
            mail.select(folder)

            _, msg_nums = mail.search(None, "ALL")
            nums = msg_nums[0].split()

            if not nums:
                return "Inbox is empty."

            recent = nums[-count:]
            recent.reverse()

            lines = []
            for num in recent:
                _, data = mail.fetch(num, "(RFC822)")
                msg = email.message_from_bytes(data[0][1])
                sender = msg.get("From", "?")
                subject = msg.get("Subject", "(no subject)")
                date = msg.get("Date", "")[:20]
                # Decode subject
                if "=?" in subject:
                    decoded = email.header.decode_header(subject)
                    subject = str(decoded[0][0], decoded[0][1] or "utf-8") if isinstance(decoded[0][0], bytes) else str(decoded[0][0])
                lines.append(f"  {date:20s} {sender[:30]:30s} {subject[:50]}")

            return f"Inbox ({len(lines)} recent):\n" + "\n".join(lines)
    except Exception as e:
        return f"Email read error: {e}"


def _search_email(query: str, count: int = 5) -> str:
    """Search emails via IMAP."""
    cfg = _load_config()
    imap_host = cfg.get("imap_host", "imap.gmail.com")
    username = cfg.get("username", "")
    password = cfg.get("password", "")

    if not username or not password:
        return "Email not configured."

    try:
        with imaplib.IMAP4_SSL(imap_host) as mail:
            mail.login(username, password)
            mail.select("INBOX")

            # Search by subject or from
            _, msg_nums = mail.search(None, f'(OR SUBJECT "{query}" FROM "{query}")')
            nums = msg_nums[0].split()

            if not nums:
                return f"No emails matching '{query}'."

            recent = nums[-count:]
            recent.reverse()

            lines = []
            for num in recent:
                _, data = mail.fetch(num, "(RFC822)")
                msg = email.message_from_bytes(data[0][1])
                sender = msg.get("From", "?")
                subject = msg.get("Subject", "(no subject)")
                date = msg.get("Date", "")[:20]
                lines.append(f"  {date:20s} {sender[:30]:30s} {subject[:50]}")

            return f"Found {len(lines)} emails for '{query}':\n" + "\n".join(lines)
    except Exception as e:
        return f"Email search error: {e}"


def _read_email(index: int = 0) -> str:
    """Read a specific email body."""
    cfg = _load_config()
    imap_host = cfg.get("imap_host", "imap.gmail.com")
    username = cfg.get("username", "")
    password = cfg.get("password", "")

    if not username or not password:
        return "Email not configured."

    try:
        with imaplib.IMAP4_SSL(imap_host) as mail:
            mail.login(username, password)
            mail.select("INBOX")

            _, msg_nums = mail.search(None, "ALL")
            nums = msg_nums[0].split()

            if not nums:
                return "Inbox is empty."

            # Get the nth most recent
            target = nums[-(index + 1)]
            _, data = mail.fetch(target, "(RFC822)")
            msg = email.message_from_bytes(data[0][1])

            sender = msg.get("From", "?")
            subject = msg.get("Subject", "(no subject)")
            date = msg.get("Date", "")

            # Get body
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode("utf-8", errors="replace")
                        break
            else:
                body = msg.get_payload(decode=True).decode("utf-8", errors="replace")

            return f"From: {sender}\nDate: {date}\nSubject: {subject}\n\n{body[:2000]}"
    except Exception as e:
        return f"Email read error: {e}"


def exec_email(action: str, to: str = "", subject: str = "", body: str = "", query: str = "") -> str:
    """Email management."""
    action = action.lower().strip()

    if action == "send":
        if not to or not subject:
            return "Specify to and subject. Example: send to@example.com 'Meeting' 'See you at 3pm'"
        return _send_email(to, subject, body or "(no body)")

    elif action == "inbox" or action == "recent":
        return _read_inbox()

    elif action == "read":
        # Read most recent email
        return _read_email(0)

    elif action == "search":
        if not query:
            return "Specify search query."
        return _search_email(query)

    elif action == "status":
        cfg = _load_config()
        username = cfg.get("username", "not set")
        smtp = cfg.get("smtp_host", "not set")
        return f"Email: {username}\nSMTP: {smtp}"

    else:
        return "Available actions: send, inbox, read, search, status"


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "email",
            "description": "Send and read emails. Actions: send (to + subject + body), inbox (recent), read (latest email body), search (query), status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Action: send, inbox, read, search, status",
                    },
                    "to": {
                        "type": "string",
                        "description": "Recipient email address",
                    },
                    "subject": {
                        "type": "string",
                        "description": "Email subject",
                    },
                    "body": {
                        "type": "string",
                        "description": "Email body text",
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query for search action",
                    },
                },
                "required": ["action"],
            },
        },
    },
]

TOOL_MAP = {"email": exec_email}

KEYWORDS = {
    "email": [
        "email", "mail", "send email", "inbox", "check email",
        "read email", "compose", "reply",
    ],
}
