import os
import requests
from flask import Flask, request as flask_request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

GROQ_API_KEY = os.getenv('GROQ_API_KEY')
GROQ_MODEL = os.getenv('GROQ_MODEL', 'llama3-8b-8192')

if not GROQ_API_KEY:
    raise ValueError("No GROQ_API_KEY found in .env file. Get one free at https://console.groq.com")

@app.route('/api/chat', methods=['POST'])
def chat():
    """
    Endpoint: POST /api/chat
    Body: { "prompt": "User message here" }
    Returns: { "response": "AI reply" }
    """
    try:
        data = flask_request.get_json()
        if not data or 'prompt' not in data:
            return jsonify({"error": "No prompt provided"}), 400

        prompt = data['prompt']

        # Groq uses an OpenAI-compatible REST API — very stable, huge free tier
        API_URL = "https://api.groq.com/openai/v1/chat/completions"

        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {GROQ_API_KEY}'
        }
        payload = {
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": "You are a helpful, concise AI assistant."},
                {"role": "user", "content": prompt}
            ]
        }

        response = requests.post(API_URL, headers=headers, json=payload)

        if not response.ok:
            error_data = response.json()
            error_msg = error_data.get('error', {}).get('message', 'Failed to fetch from Groq')
            return jsonify({"error": f"{response.status_code} {error_msg}"}), response.status_code

        response_data = response.json()
        generated_text = response_data['choices'][0]['message']['content']

        return jsonify({"response": generated_text})

    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy", "model": GROQ_MODEL, "provider": "Groq"})


if __name__ == '__main__':
    masked_key = f"{GROQ_API_KEY[:6]}...{GROQ_API_KEY[-4:]}" if GROQ_API_KEY else "NONE"
    print(f"\n--- SERVER STARTING (GROQ) ---")
    print(f"KEY:   {masked_key}")
    print(f"MODEL: {GROQ_MODEL}")
    print(f"------------------------------\n")
    app.run(debug=True, port=5000)
