from flask import Blueprint, jsonify, request

from database import db
from models import ActivityLog, Client, Enquiry
from services.ai_service import classify_and_summarise
from services.email_service import send_reply
from services.thread_service import attach_enquiry_to_thread, get_or_register_thread

email_bp = Blueprint("email_webhook", __name__)


@email_bp.route("/api/webhook/email", methods=["POST"])
def receive_email():
    data = request.get_json(silent=True) or {}

    from_email = (data.get("from_email") or data.get("sender_email") or "").strip().lower()
    from_name = (data.get("from_name") or data.get("sender_name") or "Unknown Sender").strip()
    subject = (data.get("subject") or "").strip()
    body = (data.get("body") or "").strip()
    message_id = (data.get("message_id") or "").strip()

    if not from_email or not body:
        return jsonify({"error": "from_email and body are required"}), 400
    if message_id and Enquiry.query.filter_by(inbound_message_id=message_id).first():
        return jsonify({"success": True, "duplicate": True}), 200

    full_text = f"{subject}\n\n{body}" if subject else body
    ai = classify_and_summarise(full_text, customer_name=from_name)

    client = Client.query.filter_by(email=from_email).first()
    is_new_client = False
    if not client:
        client = Client(name=from_name, email=from_email)
        db.session.add(client)
        db.session.flush()
        is_new_client = True

    thread, is_first_contact = get_or_register_thread(
        client_email=from_email,
        category=ai["category"],
        client_id=client.id,
        subject=subject,
        message_id=message_id,
    )

    enquiry = Enquiry(
        client_id=client.id,
        thread_id=thread.id,
        customer_name=client.name,
        email=from_email,
        source="Email Webhook",
        description=body,
        category=ai["category"],
        priority=ai["priority"],
        ai_summary=ai["summary"],
        status="New",
        inbound_subject=subject,
        inbound_message_id=message_id or None,
        suggested_response=ai["suggested_reply"],
        automation_state="First Contact" if is_first_contact else "Manual Review",
        reply_status="pending_manual",
    )
    db.session.add(enquiry)
    db.session.flush()
    attach_enquiry_to_thread(enquiry, thread, requires_manual_review=not is_first_contact)

    action = (
        "Webhook email created enquiry. "
        f"{'New client.' if is_new_client else 'Existing client.'} "
        f"{'First contact.' if is_first_contact else 'Follow-up queued for manual review.'}"
    )
    db.session.add(ActivityLog(enquiry_id=enquiry.id, action=action))

    send_result = {"sent": False, "error": "Follow-up requires manual review"}
    if is_first_contact:
        send_result = send_reply(
            to_email=from_email,
            subject=subject or f"Enquiry #{enquiry.id}",
            body=enquiry.suggested_response,
        )
        if send_result.get("sent"):
            enquiry.reply_status = "auto_sent"
            enquiry.automation_state = "Auto Replied"
            db.session.add(ActivityLog(enquiry_id=enquiry.id, action="Auto-reply sent from webhook intake"))
        else:
            enquiry.reply_status = "send_failed"
            enquiry.automation_state = "Auto Reply Failed"
            db.session.add(ActivityLog(
                enquiry_id=enquiry.id,
                action=f"Webhook auto-reply failed: {send_result.get('error', 'Unknown SMTP error')}",
            ))

    db.session.commit()

    return jsonify({
        "success": True,
        "enquiry_id": enquiry.id,
        "client_id": client.id,
        "thread_id": thread.id,
        "is_new_client": is_new_client,
        "is_first_contact": is_first_contact,
        "category": enquiry.category,
        "priority": enquiry.priority,
        "reply_status": enquiry.reply_status,
        "reply_to": from_email,
        "reply_subject": f"Re: {subject}" if subject else f"Enquiry #{enquiry.id}",
        "reply_body": enquiry.suggested_response,
        "send_result": send_result,
    }), 200
