"""
run.py - Application Entry Point
This is the ONLY file you run: `python run.py`
"""
from app import create_app
from app.config import Config

app = create_app()

if __name__ == "__main__":
    masked_key = f"{Config.GROQ_API_KEY[:6]}...{Config.GROQ_API_KEY[-4:]}"
    print("\n--- LUMINA AI BACKEND ---")
    print(f"  Provider : Groq")
    print(f"  Model    : {Config.GROQ_MODEL}")
    print(f"  API Key  : {masked_key}")
    print(f"  Endpoint : http://localhost:{Config.PORT}/api/chat")
    print(f"  Health   : http://localhost:{Config.PORT}/api/health")
    print("-------------------------\n")
    app.run(debug=Config.DEBUG, port=Config.PORT)
