from datetime import datetime

from database import db
from models import ConversationThread


def check_and_register_thread(client_email, category, client_id=None, subject="", message_id=""):
    thread, is_first_contact = get_or_register_thread(
        client_email=client_email,
        category=category,
        client_id=client_id,
        subject=subject,
        message_id=message_id,
    )
    return is_first_contact


def get_or_register_thread(client_email, category, client_id=None, subject="", message_id=""):
    email = (client_email or "").lower().strip()
    normalized_category = category or "General"

    thread = ConversationThread.query.filter_by(
        client_email=email,
        category=normalized_category,
    ).first()

    if thread is None:
        thread = ConversationThread(
            client_id=client_id,
            client_email=email,
            category=normalized_category,
            subject=subject or "",
            first_message_id=message_id or "",
            last_message_id=message_id or "",
            contact_count=1,
            status="Open",
            requires_manual_review=False,
        )
        db.session.add(thread)
        db.session.flush()
        return thread, True

    thread.contact_count = (thread.contact_count or 0) + 1
    thread.last_contact_at = datetime.utcnow()
    thread.last_message_id = message_id or thread.last_message_id
    thread.subject = subject or thread.subject
    thread.client_id = thread.client_id or client_id
    thread.requires_manual_review = True
    db.session.flush()
    return thread, False


def attach_enquiry_to_thread(enquiry, thread, requires_manual_review=False):
    enquiry.thread_id = thread.id
    thread.last_enquiry_id = enquiry.id
    if requires_manual_review:
        thread.requires_manual_review = True
    db.session.flush()
