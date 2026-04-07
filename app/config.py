"""
config.py - Centralized configuration loaded from .env
All environment variables are read once here and used throughout the app.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Path to this file's directory (backend/app/)
BASE_DIR = Path(__file__).parent

def _load_system_prompt() -> str:
    """Reads the system prompt from prompts/system.txt."""
    prompt_path = BASE_DIR / "prompts" / "system.txt"
    try:
        return prompt_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return "You are Lumina AI, a helpful and concise AI assistant."

class Config:
    # Groq LLM Settings
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    GROQ_API_URL: str = "https://api.groq.com/openai/v1/chat/completions"

    # System Prompt — loaded from app/prompts/system.txt
    SYSTEM_PROMPT: str = _load_system_prompt()

    # Flask Settings
    DEBUG: bool = os.getenv("FLASK_DEBUG", "true").lower() == "true"
    PORT: int = int(os.getenv("PORT", 5000))

    # Memory — max user+bot message pairs to remember per session (RAM only)
    MAX_HISTORY: int = int(os.getenv("MAX_HISTORY", "20"))

    @classmethod
    def validate(cls):
        """Raises an error at startup if required config is missing."""
        if not cls.GROQ_API_KEY:
            raise ValueError(
                "GROQ_API_KEY is missing from .env file.\n"
                "Get a free key at: https://console.groq.com"
            )
