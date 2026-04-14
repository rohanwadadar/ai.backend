"""
app.py - Application Factory and Entry Point
Creates and configures the Flask app instance.
"""
from flask import Flask
from flask_cors import CORS
from config import Config
from controller import chat_bp

def create_app() -> Flask:
    """Factory function — creates a fresh Flask app with all extensions registered."""
    Config.validate()
    flask_app = Flask(__name__)
    
    # Allow cross-origin requests from the React frontend
    CORS(flask_app, resources={r"/api/*": {"origins": "*"}})

    # Register route blueprints
    flask_app.register_blueprint(chat_bp)

    return flask_app

app = create_app()

if __name__ == "__main__":
    masked_key = f"{Config.GROQ_API_KEY[:6]}...{Config.GROQ_API_KEY[-4:]}" if Config.GROQ_API_KEY else "NONE"
    print("\n--- LUMINA AI BACKEND ---")
    print(f"  Provider : Groq")
    print(f"  Model    : {Config.GROQ_MODEL}")
    print(f"  API Key  : {masked_key}")
    print(f"  Endpoint : http://localhost:{Config.PORT}/api/chat")
    print(f"  Health   : http://localhost:{Config.PORT}/api/health")
    print("-------------------------\n")
    app.run(debug=Config.DEBUG, port=Config.PORT)
