"""
models.py
Handles data structures and active state for the backend.
"""
from config import Config

# ═══════════════════════════════════════════════════════
#  IN-MEMORY CONVERSATION STORE (RAM only, wiped on restart)
#  Key: session_id (string)  →  Value: list of message dicts
# ═══════════════════════════════════════════════════════
_sessions = {}

def get_history(session_id: str) -> list:
    """Return the conversation history for a session, creating it if needed."""
    if session_id not in _sessions:
        _sessions[session_id] = []
    return _sessions[session_id]

def trim_history(history: list):
    """Keep only the last MAX_HISTORY pairs (user + assistant) to limit RAM usage."""
    max_messages = Config.MAX_HISTORY * 2  # each pair = 2 messages
    while len(history) > max_messages:
        history.pop(0)

def clear_session_data(session_id: str):
    """Clear memory for a specific session"""
    if session_id in _sessions:
        del _sessions[session_id]
