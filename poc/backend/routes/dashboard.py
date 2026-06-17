from datetime import date

from flask import Blueprint, jsonify

from database import db
from models import ActivityLog, ChatMessage, ChatSession, ConversationThread, Enquiry

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/api/dashboard", methods=["GET"])
def dashboard():
    total = Enquiry.query.count()
    new = Enquiry.query.filter_by(status="New").count()
    in_disc = Enquiry.query.filter_by(status="In Discussion").count()
    quoted = Enquiry.query.filter_by(status="Quoted").count()
    closed = Enquiry.query.filter_by(status="Closed").count()
    dropped = Enquiry.query.filter_by(status="Dropped").count()

    today_str = date.today().isoformat()
    pending_followup = Enquiry.query.filter(
        Enquiry.follow_up_date != "",
        Enquiry.follow_up_date <= today_str,
        Enquiry.status.notin_(["Closed", "Dropped"]),
    ).count()

    by_category = db.session.query(
        Enquiry.category, db.func.count(Enquiry.id)
    ).group_by(Enquiry.category).all()

    by_priority = db.session.query(
        Enquiry.priority, db.func.count(Enquiry.id)
    ).group_by(Enquiry.priority).all()

    by_reply_status = db.session.query(
        Enquiry.reply_status, db.func.count(Enquiry.id)
    ).group_by(Enquiry.reply_status).all()

    automation = {
        "email_enquiries": Enquiry.query.filter(Enquiry.source.ilike("%Email%")).count(),
        "auto_sent": Enquiry.query.filter_by(reply_status="auto_sent").count(),
        "pending_manual": Enquiry.query.filter_by(reply_status="pending_manual").count(),
        "send_failed": Enquiry.query.filter_by(reply_status="send_failed").count(),
        "manually_sent": Enquiry.query.filter_by(reply_status="manually_sent").count(),
    }

    thread_status = {
        "total": ConversationThread.query.count(),
        "manual_review": ConversationThread.query.filter_by(requires_manual_review=True).count(),
        "open": ConversationThread.query.filter_by(status="Open").count(),
        "closed": ConversationThread.query.filter_by(status="Closed").count(),
    }

    chatbot = {
        "sessions": ChatSession.query.count(),
        "messages": ChatMessage.query.count(),
        "chatbot_enquiries": Enquiry.query.filter_by(source="Chatbot").count(),
    }

    recent = Enquiry.query.order_by(Enquiry.created_at.desc()).limit(5).all()
    activity = ActivityLog.query.order_by(ActivityLog.created_at.desc()).limit(8).all()

    return jsonify({
        "total": total,
        "new": new,
        "in_discussion": in_disc,
        "quoted": quoted,
        "closed": closed,
        "dropped": dropped,
        "pending_followup": pending_followup,
        "by_category": {k or "General": v for k, v in by_category},
        "by_priority": {k or "Medium": v for k, v in by_priority},
        "by_reply_status": {k or "pending_manual": v for k, v in by_reply_status},
        "automation": automation,
        "thread_status": thread_status,
        "chatbot": chatbot,
        "recent": [e.to_dict(include_logs=False) for e in recent],
        "activity": [log.to_dict() for log in activity],
    }), 200
