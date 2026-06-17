from flask import Blueprint, jsonify, request

from database import db
from models import ActivityLog, Client, ConversationThread, Enquiry
from services.ai_service import classify_and_summarise
from services.email_service import fetch_unread_emails, send_reply
from services.thread_service import attach_enquiry_to_thread, get_or_register_thread

automation_bp = Blueprint("automation", __name__)


def log(enquiry_id, action):
    db.session.add(ActivityLog(enquiry_id=enquiry_id, action=action))


def _client_for_email(email, name):
    client = Client.query.filter_by(email=email).first()
    if client:
        return client, False

    client = Client(name=name or "Email Sender", email=email)
    db.session.add(client)
    db.session.flush()
    return client, True


def save_enquiry_from_email(mail, ai_result, client, thread, is_first_contact):
    description = f"Subject: {mail.get('subject', 'No Subject')}\n\n{mail.get('body', '')}"
    enquiry = Enquiry(
        client_id=client.id,
        thread_id=thread.id,
        customer_name=client.name,
        email=client.email,
        source="Email",
        description=description,
        category=ai_result.get("category", "General"),
        priority=ai_result.get("priority", "Medium"),
        ai_summary=ai_result.get("summary", ""),
        status="New",
        inbound_subject=mail.get("subject", ""),
        inbound_message_id=mail.get("message_id", ""),
        automation_state="First Contact" if is_first_contact else "Manual Review",
        suggested_response=ai_result.get("suggested_reply", ""),
        reply_status="pending_manual",
    )
    db.session.add(enquiry)
    db.session.flush()
    attach_enquiry_to_thread(enquiry, thread, requires_manual_review=not is_first_contact)
    log(enquiry.id, "Imported from unread email and AI response drafted")
    return enquiry


@automation_bp.route("/api/automation/email/sync", methods=["POST"])
def sync_emails():
    data = request.get_json(silent=True) or {}
    limit = int(data.get("limit", 10))
    mark_seen = bool(data.get("mark_seen", False))

    try:
        emails = fetch_unread_emails(limit=limit, mark_seen=mark_seen)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

    imported = []
    results = []
    skipped = 0

    for mail in emails:
        message_id = mail.get("message_id", "")
        if message_id and Enquiry.query.filter_by(inbound_message_id=message_id).first():
            skipped += 1
            continue

        sender_email = mail.get("from_email") or mail.get("sender_email")
        sender_name = mail.get("from_name") or mail.get("sender_name") or sender_email
        if not sender_email:
            skipped += 1
            continue

        full_text = f"{mail.get('subject', '')}\n\n{mail.get('body', '')}"
        ai_result = classify_and_summarise(full_text, customer_name=sender_name)
        client, is_new_client = _client_for_email(sender_email, sender_name)
        thread, is_first_contact = get_or_register_thread(
            client_email=sender_email,
            category=ai_result.get("category", "General"),
            client_id=client.id,
            subject=mail.get("subject", ""),
            message_id=message_id,
        )
        enquiry = save_enquiry_from_email(mail, ai_result, client, thread, is_first_contact)

        if is_first_contact:
            send_result = send_reply(
                to_email=sender_email,
                subject=mail.get("subject", "Your enquiry"),
                body=enquiry.suggested_response,
            )
            if send_result.get("sent"):
                enquiry.reply_status = "auto_sent"
                enquiry.automation_state = "Auto Replied"
                log(enquiry.id, "Auto-reply sent for first contact")
            else:
                enquiry.reply_status = "send_failed"
                enquiry.automation_state = "Auto Reply Failed"
                log(enquiry.id, f"Auto-reply failed: {send_result.get('error', 'Unknown SMTP error')}")
        else:
            enquiry.reply_status = "pending_manual"
            enquiry.automation_state = "Manual Review"
            log(enquiry.id, "Follow-up thread detected; queued for manual review")

        db.session.commit()
        imported.append(enquiry.to_dict(include_logs=False))
        results.append({
            "enquiry_id": enquiry.id,
            "client": sender_email,
            "is_new_client": is_new_client,
            "thread_id": thread.id,
            "is_first_contact": is_first_contact,
            "category": enquiry.category,
            "priority": enquiry.priority,
            "reply_status": enquiry.reply_status,
        })

    return jsonify({
        "synced": len(imported),
        "imported_count": len(imported),
        "skipped": skipped,
        "skipped_count": skipped,
        "imported": imported,
        "results": results,
    }), 200


@automation_bp.route("/api/automation/threads", methods=["GET"])
def list_threads():
    threads = ConversationThread.query.order_by(ConversationThread.last_contact_at.desc()).all()
    return jsonify([thread.to_dict() for thread in threads]), 200


@automation_bp.route("/api/automation/activity", methods=["GET"])
def recent_activity():
    logs = ActivityLog.query.order_by(ActivityLog.created_at.desc()).limit(50).all()
    return jsonify([log.to_dict() for log in logs]), 200


@automation_bp.route("/api/automation/test", methods=["GET"])
def test_route():
    return jsonify({"message": "Automation route is working", "status": "ok"}), 200
