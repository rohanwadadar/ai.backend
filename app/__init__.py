"""
app/__init__.py - Application Factory
Creates and configures the Flask app instance.
"""
from flask import Flask
from flask_cors import CORS
from app.config import Config


def create_app() -> Flask:
    """Factory function — creates a fresh Flask app with all extensions registered."""
    Config.validate()

    flask_app = Flask(__name__)
    
    # Allow cross-origin requests from the React frontend
    CORS(flask_app, resources={r"/api/*": {"origins": "*"}})

    # Register route blueprints
    from app.routes.chat import chat_bp
    flask_app.register_blueprint(chat_bp)

    return flask_app
