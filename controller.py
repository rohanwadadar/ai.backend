"""
controller.py - All LLM chat-related API route handlers

VERSION HISTORY:
  v1.0 - Rohan Wadadar - Standard blocking JSON response (no streaming)
  v2.0 - Changed by Rohan - SSE Streaming + real /api/chat/stop endpoint
         Groq now called with stream=True. Each token is forwarded to the
         frontend as a Server-Sent Event. Stop button actually closes the
         Groq connection mid-generation — saving real tokens.
"""
import requests
import json as json_lib
import re
import threading
from flask import Blueprint, request, jsonify, Response, stream_with_context
from config import Config
from models import get_history, trim_history, clear_session_data

# Blueprint groups all /api routes together
chat_bp = Blueprint("chat", __name__, url_prefix="/api")

# ═══════════════════════════════════════════════════════
# v2.0 - Changed by Rohan
# Active SSE stream registry.
# Key: session_id → {"abort": threading.Event()}
# Used by /api/chat/stop to signal the generator to stop.
# ═══════════════════════════════════════════════════════
_active_streams = {}


# ┌─────────────────────────────────────────────────────────┐
# │  v1.0 - OLD /api/chat (BLOCKING — PRESERVED BY ROHAN)   │
# │  This made a single blocking call to Groq and returned  │
# │  a complete JSON response. Stop button had NO effect on │
# │  the backend — Groq kept generating, wasting tokens.    │
# └─────────────────────────────────────────────────────────┘
# @chat_bp.route("/chat", methods=["POST"])
# def chat():
#     data = request.get_json()
#     if not data or "prompt" not in data:
#         return jsonify({"error": "Request body must contain a 'prompt' field."}), 400
#     prompt = data["prompt"].strip()
#     if not prompt:
#         return jsonify({"error": "Prompt cannot be empty."}), 400
#     session_id = data.get("session_id", "default")
#     try:
#         from duckduckgo_search import DDGS
#         web_context = ""
#         try:
#             with DDGS() as ddgs:
#                 results = ddgs.text(prompt, max_results=3, backend="lite")
#                 if results:
#                     for r in results:
#                         title = r.get('title', '')
#                         body = r.get('body', '')
#                         if title or body:
#                             web_context += f"- {title}: {body}\n"
#         except Exception as e:
#             print(f"Chat Web Search Error: {e}")
#         history = get_history(session_id)
#         dynamic_system_prompt = Config.SYSTEM_PROMPT
#         if web_context:
#             dynamic_system_prompt += (
#                 f"\n\n--- REAL-TIME WEB SEARCH RESULTS ---\n"
#                 f"{web_context}\n"
#                 f"------------------------------------\n"
#                 f"You have internet access via the search results above. "
#                 f"Synthesize the provided search results to answer the user. "
#                 f"Do not apologize or say you don't have real-time access. "
#                 f"If the exact answer is missing, provide general info from snippets."
#             )
#         history.append({"role": "user", "content": prompt})
#         messages_for_api = [{"role": "system", "content": dynamic_system_prompt}, *history]
#         headers = {"Content-Type": "application/json", "Authorization": f"Bearer {Config.GROQ_API_KEY}"}
#         payload = {"model": Config.GROQ_MODEL, "messages": messages_for_api}
#         response = requests.post(Config.GROQ_API_URL, headers=headers, json=payload, timeout=30)
#         if not response.ok:
#             history.pop()
#             error_msg = response.json().get("error", {}).get("message", "Groq API error")
#             return jsonify({"error": f"{response.status_code} {error_msg}"}), response.status_code
#         reply = response.json()["choices"][0]["message"]["content"]
#         history.append({"role": "assistant", "content": reply})
#         trim_history(history)
#         return jsonify({"response": reply})
#     except requests.Timeout:
#         return jsonify({"error": "Request timed out. Please try again."}), 504
#     except Exception as e:
#         return jsonify({"error": str(e)}), 500


# ┌─────────────────────────────────────────────────────────┐
# │  v2.0 - NEW /api/chat  (SSE STREAMING — Changed by Rohan)│
# │  Calls Groq with stream=True. Each token from Groq is   │
# │  immediately forwarded to the frontend as an SSE event. │
# │  The abort_event flag (set by /api/chat/stop) closes    │
# │  the Groq response mid-stream — stopping token spend.   │
# └─────────────────────────────────────────────────────────┘
@chat_bp.route("/chat", methods=["POST"])
def chat():
    """
    POST /api/chat  (v2.0 — SSE Streaming)
    Request body: { "prompt": "...", "session_id": "optional-uuid" }
    Response:     text/event-stream with token-by-token SSE events.

    SSE Event types:
      data: {"token": "..."} — a chunk of the AI response
      data: {"done": true}   — stream complete, response saved to history
      data: {"error": "..."}  — an error occurred
    """
    data = request.get_json()

    if not data or "prompt" not in data:
        return jsonify({"error": "Request body must contain a 'prompt' field."}), 400

    prompt = data["prompt"].strip()
    if not prompt:
        return jsonify({"error": "Prompt cannot be empty."}), 400

    session_id = data.get("session_id", "default")

    # v2.0: Create a threading abort event for this session
    abort_event = threading.Event()
    _active_streams[session_id] = {"abort": abort_event}

    def generate():
        """SSE generator — runs inside a streaming Flask response."""
        full_response = ""
        history = get_history(session_id)

        try:
            # --- Web search (same as v1.0) ---
            from duckduckgo_search import DDGS
            web_context = ""
            try:
                with DDGS() as ddgs:
                    results = ddgs.text(prompt, max_results=3, backend="lite")
                    if results:
                        for r in results:
                            title = r.get('title', '')
                            body = r.get('body', '')
                            if title or body:
                                web_context += f"- {title}: {body}\n"
            except Exception as e:
                print(f"Chat Web Search Error: {e}")

            # --- Build system prompt ---
            dynamic_system_prompt = Config.SYSTEM_PROMPT
            if web_context:
                dynamic_system_prompt += (
                    f"\n\n--- REAL-TIME WEB SEARCH RESULTS ---\n"
                    f"{web_context}\n"
                    f"------------------------------------\n"
                    f"You have internet access via the search results above. "
                    f"Synthesize the provided search results to answer the user. "
                    f"Do not apologize or say you don't have real-time access. "
                    f"If the exact answer (like current temperature) is missing from the snippets, "
                    f"provide general information from the snippets and answer thoughtfully."
                )

            # --- Append user message to history ---
            history.append({"role": "user", "content": prompt})

            messages_for_api = [
                {"role": "system", "content": dynamic_system_prompt},
                *history
            ]

            req_headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {Config.GROQ_API_KEY}",
            }
            # v2.0: KEY CHANGE — stream=True on both the payload and requests call
            payload = {
                "model": Config.GROQ_MODEL,
                "messages": messages_for_api,
                "stream": True,   # v2.0 — tell Groq to stream token-by-token
            }

            groq_response = requests.post(
                Config.GROQ_API_URL,
                headers=req_headers,
                json=payload,
                stream=True,      # v2.0 — keep TCP connection open for streaming
                timeout=60
            )

            if not groq_response.ok:
                history.pop()  # remove failed user message
                error_body = groq_response.json()
                error_msg = error_body.get("error", {}).get("message", "Groq API error")
                yield f"data: {json_lib.dumps({'error': f'{groq_response.status_code} {error_msg}'})}\n\n"
                return

            # --- Iterate over SSE lines from Groq ---
            for line in groq_response.iter_lines():

                # v2.0: Check abort flag every token — if set, close connection immediately
                if abort_event.is_set():
                    groq_response.close()   # ← This is the key: closes Groq TCP connection
                    print(f"[SSE] Stream aborted for session: {session_id}")
                    break

                if not line:
                    continue

                decoded = line.decode("utf-8") if isinstance(line, bytes) else line

                # Groq SSE lines look like: "data: {...}" or "data: [DONE]"
                if not decoded.startswith("data:"):
                    continue

                raw_json = decoded[len("data:"):].strip()

                if raw_json == "[DONE]":
                    break

                try:
                    chunk = json_lib.loads(raw_json)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    token = delta.get("content", "")
                    if token:
                        full_response += token
                        # Forward this token to the frontend as an SSE event
                        yield f"data: {json_lib.dumps({'token': token})}\n\n"
                except (json_lib.JSONDecodeError, IndexError, KeyError):
                    continue

        except requests.Timeout:
            yield f"data: {json_lib.dumps({'error': 'Request timed out. Please try again.'})}\n\n"
            return
        except Exception as e:
            yield f"data: {json_lib.dumps({'error': str(e)})}\n\n"
            return
        finally:
            # v2.0: Always clean up the active stream registry
            _active_streams.pop(session_id, None)

        # --- Save only what was generated (even if partially stopped) ---
        if full_response:
            history.append({"role": "assistant", "content": full_response})
            trim_history(history)

        # Signal stream completion to the frontend
        yield f"data: {json_lib.dumps({'done': True})}\n\n"

    # v2.0: Return a streaming response with correct SSE headers
    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # Prevents proxy/nginx buffering
            "Connection": "keep-alive",
        }
    )


# ┌─────────────────────────────────────────────────────────┐
# │  v2.0 - NEW ENDPOINT  (Changed by Rohan)                │
# │  POST /api/chat/stop                                    │
# │  Frontend calls this when the user clicks the Stop btn. │
# │  Sets the abort_event for the session → the SSE         │
# │  generator closes the Groq connection mid-stream.       │
# └─────────────────────────────────────────────────────────┘
@chat_bp.route("/chat/stop", methods=["POST"])
def stop_chat():
    """
    POST /api/chat/stop  (v2.0 — NEW endpoint)
    Request body: { "session_id": "uuid" }
    Signals the active SSE generator for that session to abort.
    """
    data = request.get_json()
    session_id = data.get("session_id", "default") if data else "default"

    stream_info = _active_streams.get(session_id)
    if stream_info:
        stream_info["abort"].set()  # ← triggers abort_event.is_set() in the generator
        return jsonify({"stopped": True, "session_id": session_id})

    return jsonify({"stopped": False, "reason": "No active stream for this session."})


@chat_bp.route("/clear", methods=["POST"])
def clear_session():
    """
    POST /api/clear
    Request body: { "session_id": "uuid" }
    Clears the conversation history for a specific session.
    """
    data = request.get_json()
    session_id = data.get("session_id", "default") if data else "default"
    clear_session_data(session_id)
    return jsonify({"status": "cleared"})


@chat_bp.route("/roadmap", methods=["POST"])
def generate_roadmap():
    """
    POST /api/roadmap
    Request body: { "prompt": "Topic to generate roadmap for" }
    Returns a strict JSON structure for the roadmap UI and real web links.
    (No streaming needed — roadmap uses response_format JSON mode)
    """
    from duckduckgo_search import DDGS
    data = request.get_json()
    if not data or "prompt" not in data:
        return jsonify({"error": "Missing prompt"}), 400

    prompt = data["prompt"].strip()

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
- For each topic's `searchUrl`, generate a properly URL-encoded search link for YouTube or Google.
'''

    try:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {Config.GROQ_API_KEY}",
        }
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

        parsed_json = json_lib.loads(reply)
        parsed_json["resources"] = external_links

        return jsonify(parsed_json)

    except json_lib.JSONDecodeError:
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

        lines = re.findall(r'^\d+\.\s*(.+)$', raw, re.MULTILINE)
        suggestions = [l.strip().strip('"') for l in lines if l.strip()][:2]
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
    data = request.get_json()
    if not data or "prompt" not in data:
        return jsonify({"error": "Prompt required."}), 400

    prompt = data["prompt"].strip()
    if not prompt:
        return jsonify({"error": "Prompt cannot be empty."}), 400

    num_match = re.search(r'(\d+)', prompt)
    num_questions = int(num_match.group(1)) if num_match else 10
    num_questions = max(2, min(num_questions, 20))

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
- Output ONLY the JSON object, nothing else"""

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

        try:
            parsed = json_lib.loads(raw)
        except json_lib.JSONDecodeError:
            match = re.search(r'\{[\s\S]*\}', raw)
            if match:
                parsed = json_lib.loads(match.group(0))
            else:
                return jsonify({"error": "Failed to parse MCQ response from AI."}), 500

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
    """
    data = request.get_json()
    if not data or "prompt" not in data:
        return jsonify({"error": "Prompt required."}), 400

    prompt = data["prompt"].strip()
    if not prompt:
        return jsonify({"error": "Prompt cannot be empty."}), 400

    num_match = re.search(r'(\d+)', prompt)
    num_cards = int(num_match.group(1)) if num_match else 8
    num_cards = max(4, min(num_cards, 20))

    flashcard_system_prompt = f"""You are a spaced-repetition flashcard expert. You MUST output ONLY valid JSON.

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
- "front" should be a SHORT question, term, or concept trigger
- "back" should be a COMPLETE answer
- Output ONLY the JSON object"""

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
        "streaming": True,   # v2.0
    })
