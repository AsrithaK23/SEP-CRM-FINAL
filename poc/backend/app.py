import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask
from flask_cors import CORS

load_dotenv(Path(__file__).resolve().parent / ".env")

from database import db, init_db
from routes.auth import auth_bp
from routes.automation import automation_bp
from routes.chatbot import chat_bp
from routes.dashboard import dashboard_bp
from routes.email_webhook import email_bp
from routes.enquiries import enquiries_bp


def create_app():
    app = Flask(__name__)
    base_dir = os.path.abspath(os.path.dirname(__file__))
    default_db = "sqlite:///" + os.path.join(base_dir, "database.db")

    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", default_db)
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    CORS(app, resources={r"/api/*": {"origins": "*"}})
    init_db(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(enquiries_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(email_bp)
    app.register_blueprint(automation_bp)

    @app.route("/")
    def health():
        return {"status": "Smart AI Enquiry Management API running"}, 200

    return app


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        from models import User

        if User.query.filter_by(role="admin").count() == 0:
            admin = User(name="Admin", email="admin@portal.com", role="admin")
            admin.set_password("admin123")
            db.session.add(admin)
            db.session.commit()
            print("Default admin created: admin@portal.com / admin123")

    print("Backend running at http://localhost:5000")
    app.run(debug=True, port=5000)
