"""
routes/chat.py - All LLM chat-related API route handlers
"""
import requests
from flask import Blueprint, request, jsonify
from app.config import Config

# Blueprint groups all /api routes together
chat_bp = Blueprint("chat", __name__, url_prefix="/api")

# ═══════════════════════════════════════════════════════
#  IN-MEMORY CONVERSATION STORE (RAM only, wiped on restart)
#  Key: session_id (string)  →  Value: list of message dicts
# ═══════════════════════════════════════════════════════
_sessions = {}


def _get_history(session_id: str) -> list:
    """Return the conversation history for a session, creating it if needed."""
    if session_id not in _sessions:
        _sessions[session_id] = []
    return _sessions[session_id]


def _trim_history(history: list):
    """Keep only the last MAX_HISTORY pairs (user + assistant) to limit RAM usage."""
    max_messages = Config.MAX_HISTORY * 2  # each pair = 2 messages
    while len(history) > max_messages:
        history.pop(0)


@chat_bp.route("/chat", methods=["POST"])
def chat():
    """
    POST /api/chat
    Request body: { "prompt": "Your message", "session_id": "optional-uuid" }
    Response:     { "response": "AI reply" }
    
    If session_id is provided, the backend remembers previous messages
    for the duration of this server session (RAM only, no disk).
    """
    data = request.get_json()

    if not data or "prompt" not in data:
        return jsonify({"error": "Request body must contain a 'prompt' field."}), 400

    prompt = data["prompt"].strip()
    if not prompt:
        return jsonify({"error": "Prompt cannot be empty."}), 400

    session_id = data.get("session_id", "default")

    try:
        # Perform a quick background search for the user's prompt
        from duckduckgo_search import DDGS
        web_context = ""
        try:
            with DDGS() as ddgs:
                results = ddgs.text(prompt, max_results=3)
                if results:
                    for r in results:
                        web_context += f"- {r.get('title')}: {r.get('body')}\n"
        except Exception as e:
            print(f"Chat Web Search Error: {e}")

        # Get or create the conversation history for this session
        history = _get_history(session_id)

        # We inject the web context invisibly into this specific request
        dynamic_system_prompt = Config.SYSTEM_PROMPT
        if web_context:
            dynamic_system_prompt += (
                f"\n\n--- REAL-TIME WEB SEARCH RESULTS ---\n"
                f"{web_context}\n"
                f"------------------------------------\n"
                f"CRITICAL INSTRUCTION: You now have real-time web access via the search results above. "
                f"You MUST use the provided search results to directly answer the user. "
                f"NEVER say 'I am an AI and don't have real-time access' or 'I cannot check the internet' — the web search results above ARE your real-time internet access."
            )

        # Add the new user message to history
        history.append({"role": "user", "content": prompt})

        # Build the full messages array: system prompt + conversation history
        messages_for_api = [
            {"role": "system", "content": dynamic_system_prompt},
            *history
        ]

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {Config.GROQ_API_KEY}",
        }
        payload = {
            "model": Config.GROQ_MODEL,
            "messages": messages_for_api,
        }

        response = requests.post(Config.GROQ_API_URL, headers=headers, json=payload, timeout=30)

        if not response.ok:
            # Remove the failed user message from history
            history.pop()
            error_msg = response.json().get("error", {}).get("message", "Groq API error")
            return jsonify({"error": f"{response.status_code} {error_msg}"}), response.status_code

        reply = response.json()["choices"][0]["message"]["content"]

        # Save the assistant's reply to history
        history.append({"role": "assistant", "content": reply})

        # Trim history to stay within RAM limits
        _trim_history(history)

        return jsonify({"response": reply})

    except requests.Timeout:
        return jsonify({"error": "Request timed out. Please try again."}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@chat_bp.route("/clear", methods=["POST"])
def clear_session():
    """
    POST /api/clear
    Request body: { "session_id": "uuid" }
    Clears the conversation history for a specific session.
    """
    data = request.get_json()
    session_id = data.get("session_id", "default") if data else "default"
    if session_id in _sessions:
        del _sessions[session_id]
    return jsonify({"status": "cleared"})



from duckduckgo_search import DDGS

@chat_bp.route("/roadmap", methods=["POST"])
def generate_roadmap():
    """
    POST /api/roadmap
    Request body: { "prompt": "Topic to generate roadmap for" }
    Returns a strict JSON structure for the roadmap UI and real web links.
    """
    data = request.get_json()
    if not data or "prompt" not in data:
        return jsonify({"error": "Missing prompt"}), 400

    prompt = data["prompt"].strip()

    # Perform a quick web search to find real content links for the main topic
    external_links = []
    try:
        with DDGS() as ddgs:
            results = ddgs.text(f"best free courses learning {prompt}", max_results=4)
            if results:
                for r in results:
                    external_links.append({
                        "title": r.get('title', 'Resource'),
                        "url": r.get('href', '#')
                    })
    except Exception as e:
        print(f"DuckDuckGo search error: {e}")

    system_instruction = f'''
You are an expert curriculum designer. The user wants to learn a topic.
You must generate a structured learning roadmap.
You MUST reply with ONLY valid JSON and nothing else.

JSON Schema:
{{
  "title": "Mastering [Topic]",
  "categories": [
    {{
      "id": "1",
      "title": "1. [Category Name]",
      "topics": [
        {{ "name": "[Specific Concept]", "level": "must", "searchUrl": "https://www.youtube.com/results?search_query=..." }} 
      ]
    }}
  ]
}}

Important:
- Provide 3 to 5 categories.
- Provide 3 to 5 topics per category.
- Map "must" to critical foundational knowledge, "good" to important/secondary, and "suggested" to extra.
- For each topic's `searchUrl`, generate a properly URL-encoded search link for YouTube or Google so the user can click it to learn that specific concept immediately.
'''

    try:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {Config.GROQ_API_KEY}",
        }
        
        # We enforce JSON mode via LLaMA 3's built-in response_format if compatible, 
        # or just prompt engineering.
        payload = {
            "model": Config.GROQ_MODEL,
            "messages": [
                {"role": "system", "content": system_instruction.strip()},
                {"role": "user", "content": f"Generate a learning roadmap for: {prompt}"}
            ],
            "response_format": {"type": "json_object"}
        }

        response = requests.post(Config.GROQ_API_URL, headers=headers, json=payload, timeout=40)

        if not response.ok:
            error_msg = response.json().get("error", {}).get("message", "Groq API error")
            return jsonify({"error": f"{response.status_code} {error_msg}"}), response.status_code

        reply = response.json()["choices"][0]["message"]["content"]
        
        import json
        parsed_json = json.loads(reply)
        # Inject the real internet links directly into the parsed JSON
        parsed_json["resources"] = external_links
        
        return jsonify(parsed_json)

    except json.JSONDecodeError:
        return jsonify({"error": "Failed to parse roadmap JSON from model. Please try again."}), 500
    except requests.Timeout:
        return jsonify({"error": "Request timed out."}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@chat_bp.route("/suggest", methods=["POST"])
def suggest():
    """
    POST /api/suggest
    Request body: { "prompt": "Your partial message" }
    Response:     { "suggestions": ["Option 1", "Option 2"] }
    """
    data = request.get_json()
    if not data or "prompt" not in data:
        return jsonify({"suggestions": []})

    prompt = data["prompt"].strip()
    if len(prompt) < 10:
        return jsonify({"suggestions": []})

    try:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {Config.GROQ_API_KEY}",
        }
        suggestion_system_prompt = (
            "You are a prompt enhancer. The user typed a message that may have typos, "
            "poor grammar, or be unclear. Rewrite it as exactly TWO improved alternatives "
            "that are clear, professional, and more effective for an AI assistant. "
            "Format your response ONLY as two lines, each starting with a number and period:\n"
            "1. First alternative here\n"
            "2. Second alternative here\n"
            "If the message is already perfectly clear, still provide two polished variations. "
            "DO NOT explain, add headers, or say anything else."
        )

        payload = {
            "model": Config.GROQ_MODEL,
            "messages": [
                {"role": "system", "content": suggestion_system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
            "max_tokens": 150
        }

        response = requests.post(Config.GROQ_API_URL, headers=headers, json=payload, timeout=8)

        if not response.ok:
            return jsonify({"suggestions": []})

        raw = response.json()["choices"][0]["message"]["content"].strip()

        # Parse "1. ..." and "2. ..." lines
        import re
        lines = re.findall(r'^\d+\.\s*(.+)$', raw, re.MULTILINE)
        suggestions = [l.strip().strip('"') for l in lines if l.strip()][:2]

        # Filter out suggestions identical to original input
        suggestions = [s for s in suggestions if s.lower() != prompt.lower()]

        return jsonify({"suggestions": suggestions})

    except Exception:
        return jsonify({"suggestions": []})


@chat_bp.route("/mcq", methods=["POST"])
def mcq():
    """
    POST /api/mcq
    Request body: { "prompt": "Give me 5 MCQ on Python" }
    Response:     { "mcq": true, "title": "...", "questions": [...] }
    """
    import json as json_lib
    import re

    data = request.get_json()
    if not data or "prompt" not in data:
        return jsonify({"error": "Prompt required."}), 400

    prompt = data["prompt"].strip()
    if not prompt:
        return jsonify({"error": "Prompt cannot be empty."}), 400

    # Extract how many questions the user wants (default 10)
    num_match = re.search(r'(\d+)', prompt)
    num_questions = int(num_match.group(1)) if num_match else 10
    num_questions = max(2, min(num_questions, 20))  # clamp 2-20

    mcq_system_prompt = f"""You are an exam generator. You MUST output ONLY valid JSON — no extra text, no markdown.

Generate exactly {num_questions} multiple-choice questions based on the user's topic.

Output this exact JSON structure:
{{
  "mcq": true,
  "title": "Topic Name Quiz",
  "questions": [
    {{
      "id": 1,
      "question": "What is ...?",
      "options": ["Option A", "Option B", "Option C", "Option D"],
      "answer": 2
    }}
  ]
}}

RULES:
- "answer" is the 0-based INDEX of the correct option (0=first, 1=second, 2=third, 3=fourth)
- Generate exactly {num_questions} questions
- Each question MUST have exactly 4 options
- Make questions challenging but fair  
- All 4 options must be plausible
- Output ONLY the JSON object, nothing else — no markdown, no explanation, no code fences"""

    try:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {Config.GROQ_API_KEY}",
        }
        payload = {
            "model": Config.GROQ_MODEL,
            "messages": [
                {"role": "system", "content": mcq_system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.6,
            "max_tokens": 4000,
            "response_format": {"type": "json_object"},
        }

        response = requests.post(Config.GROQ_API_URL, headers=headers, json=payload, timeout=45)

        if not response.ok:
            error_msg = response.json().get("error", {}).get("message", "Groq API error")
            return jsonify({"error": f"{response.status_code} {error_msg}"}), response.status_code

        raw = response.json()["choices"][0]["message"]["content"].strip()

        # Parse the JSON
        try:
            parsed = json_lib.loads(raw)
        except json_lib.JSONDecodeError:
            # Try to extract JSON from within the text
            match = re.search(r'\{[\s\S]*\}', raw)
            if match:
                parsed = json_lib.loads(match.group(0))
            else:
                return jsonify({"error": "Failed to parse MCQ response from AI."}), 500

        # Validate structure
        if not isinstance(parsed.get("questions"), list) or len(parsed["questions"]) == 0:
            return jsonify({"error": "AI returned invalid quiz structure."}), 500

        parsed["mcq"] = True
        return jsonify(parsed)

    except requests.Timeout:
        return jsonify({"error": "Request timed out. Please try again."}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@chat_bp.route("/flashcards", methods=["POST"])
def flashcards():
    """
    POST /api/flashcards
    Request body: { "prompt": "Generate flashcards on Python decorators" }
    Response:     { "flashcards": true, "title": "...", "cards": [ { "id":1, "front": "...", "back": "..." } ] }
    """
    import json as json_lib
    import re

    data = request.get_json()
    if not data or "prompt" not in data:
        return jsonify({"error": "Prompt required."}), 400

    prompt = data["prompt"].strip()
    if not prompt:
        return jsonify({"error": "Prompt cannot be empty."}), 400

    # Extract how many cards the user wants (default 8)
    num_match = re.search(r'(\d+)', prompt)
    num_cards = int(num_match.group(1)) if num_match else 8
    num_cards = max(4, min(num_cards, 20))  # clamp 4–20

    flashcard_system_prompt = f"""You are a spaced-repetition flashcard expert. You MUST output ONLY valid JSON — no extra text, no markdown.

Generate exactly {num_cards} flashcards on the user's topic.

Output this exact JSON structure:
{{
  "flashcards": true,
  "title": "Flashcards: Topic Name",
  "cards": [
    {{
      "id": 1,
      "front": "Concise question or term (max 15 words)",
      "back": "Clear, complete answer (2-4 sentences max)"
    }}
  ]
}}

RULES:
- Generate exactly {num_cards} cards
- "front" should be a SHORT question, term, or concept trigger (max 15 words)
- "back" should be a COMPLETE answer with a concrete example if possible (2-4 sentences)
- Cover the topic progressively from basics to advanced
- Make cards genuinely educational and memorable
- Output ONLY the JSON object, nothing else"""

    try:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {Config.GROQ_API_KEY}",
        }
        payload = {
            "model": Config.GROQ_MODEL,
            "messages": [
                {"role": "system", "content": flashcard_system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.65,
            "max_tokens": 4000,
            "response_format": {"type": "json_object"},
        }

        response = requests.post(Config.GROQ_API_URL, headers=headers, json=payload, timeout=45)

        if not response.ok:
            error_msg = response.json().get("error", {}).get("message", "Groq API error")
            return jsonify({"error": f"{response.status_code} {error_msg}"}), response.status_code

        raw = response.json()["choices"][0]["message"]["content"].strip()

        try:
            parsed = json_lib.loads(raw)
        except json_lib.JSONDecodeError:
            match = re.search(r'\{[\s\S]*\}', raw)
            if match:
                parsed = json_lib.loads(match.group(0))
            else:
                return jsonify({"error": "Failed to parse flashcard response from AI."}), 500

        if not isinstance(parsed.get("cards"), list) or len(parsed["cards"]) == 0:
            return jsonify({"error": "AI returned invalid flashcard structure."}), 500

        parsed["flashcards"] = True
        return jsonify(parsed)

    except requests.Timeout:
        return jsonify({"error": "Request timed out. Please try again."}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@chat_bp.route("/health", methods=["GET"])
def health():
    """GET /api/health — Returns server status and active config."""
    return jsonify({
        "status": "healthy",
        "provider": "Groq",
        "model": Config.GROQ_MODEL,
    })

