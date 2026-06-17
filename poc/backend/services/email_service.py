import email
import imaplib
import os
import re
import smtplib
from pathlib import Path
from email.header import decode_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parseaddr

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _decode(value):
    if not value:
        return ""
    decoded = []
    for text, encoding in decode_header(value):
        if isinstance(text, bytes):
            decoded.append(text.decode(encoding or "utf-8", errors="replace"))
        else:
            decoded.append(text)
    return "".join(decoded)


def _html_to_text(html):
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html or "")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n", text)
    text = re.sub(r"(?s)<.*?>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _message_body(message):
    plain = ""
    html = ""

    if message.is_multipart():
        for part in message.walk():
            if "attachment" in (part.get("Content-Disposition") or "").lower():
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            charset = part.get_content_charset() or "utf-8"
            content = payload.decode(charset, errors="replace")
            if part.get_content_type() == "text/plain" and not plain:
                plain = content
            elif part.get_content_type() == "text/html" and not html:
                html = content
    else:
        payload = message.get_payload(decode=True)
        if payload:
            charset = message.get_content_charset() or "utf-8"
            content = payload.decode(charset, errors="replace")
            if message.get_content_type() == "text/html":
                html = content
            else:
                plain = content

    return (plain or _html_to_text(html)).strip()


def fetch_unread_emails(limit=10, mark_seen=False):
    host = os.getenv("IMAP_HOST", "").strip()
    username = os.getenv("IMAP_USERNAME", "").strip()
    password = os.getenv("IMAP_PASSWORD", "").strip()
    folder = os.getenv("IMAP_FOLDER", "INBOX").strip()

    if not host or not username or not password:
        raise RuntimeError("IMAP_HOST, IMAP_USERNAME and IMAP_PASSWORD are required")

    mailbox = imaplib.IMAP4_SSL(host)
    try:
        mailbox.login(username, password)
        mailbox.select(folder)
        _, data = mailbox.search(None, "UNSEEN")
        ids = data[0].split()[-limit:]
        messages = []

        for msg_id in ids:
            _, msg_data = mailbox.fetch(msg_id, "(RFC822)")
            raw = msg_data[0][1]
            message = email.message_from_bytes(raw)
            sender_name, sender_email = parseaddr(_decode(message.get("From")))
            messages.append({
                "message_id": message.get("Message-ID") or msg_id.decode(),
                "subject": _decode(message.get("Subject")) or "(no subject)",
                "from_name": sender_name or sender_email or "Email Sender",
                "from_email": (sender_email or "").lower(),
                "sender_name": sender_name or sender_email or "Email Sender",
                "sender_email": (sender_email or "").lower(),
                "body": _message_body(message),
            })
            if not mark_seen:
                mailbox.store(msg_id, "-FLAGS", "\\Seen")

        return messages
    finally:
        try:
            mailbox.close()
        except Exception:
            pass
        mailbox.logout()


def send_reply(to_email, subject, body):
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME") or os.getenv("IMAP_USERNAME")
    password = os.getenv("SMTP_PASSWORD") or os.getenv("IMAP_PASSWORD")

    if not smtp_host or not username or not password:
        return {"sent": False, "error": "SMTP_HOST, SMTP_USERNAME and SMTP_PASSWORD are required"}

    message = MIMEMultipart("alternative")
    message["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    message["From"] = username
    message["To"] = to_email
    message.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(username, password)
            server.sendmail(username, to_email, message.as_string())
        return {"sent": True}
    except Exception as exc:
        return {"sent": False, "error": str(exc)}
