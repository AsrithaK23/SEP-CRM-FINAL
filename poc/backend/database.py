from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text

db = SQLAlchemy()


def _ensure_columns(table_name, additions):
    inspector = inspect(db.engine)
    if table_name not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns(table_name)}
    for name, definition in additions.items():
        if name not in existing:
            db.session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {name} {definition}"))


def _ensure_runtime_migrations():
    _ensure_columns("enquiries", {
        "thread_id": "INTEGER",
        "inbound_subject": "VARCHAR(255) DEFAULT ''",
        "inbound_message_id": "VARCHAR(255)",
        "suggested_response": "TEXT DEFAULT ''",
        "automation_state": "VARCHAR(50) DEFAULT 'Manual'",
        "reply_status": "VARCHAR(50) DEFAULT 'pending_manual'",
    })
    db.session.commit()


def init_db(app):
    db.init_app(app)
    with app.app_context():
        db.create_all()
        _ensure_runtime_migrations()
        print("Database tables created.")
