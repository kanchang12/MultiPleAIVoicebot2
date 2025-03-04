import os
import time
import re
import json
from flask import Flask, request, jsonify
from twilio.twiml.voice_response import VoiceResponse
from twilio.rest import Client
from openai import OpenAI
import requests
from collections import defaultdict
from datetime import datetime, timedelta

# Load environment variables
ELEVENLABS_API_KEY = os.getenv('ELEVENLABS_API_KEY')
ELEVENLABS_AGENT_ID = os.getenv('ELEVENLABS_AGENT_ID')
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
CALENDLY_LINK = "https://calendly.com/ali-shehroz-19991/30min"

# Initialize Flask app
app = Flask(__name__)

# Initialize Twilio client
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Initialize OpenAI client
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Performance tracking
performance_metrics = defaultdict(list)

def track_performance(category, execution_time):
    performance_metrics[category].append(execution_time)
    if len(performance_metrics[category]) > 100:
        performance_metrics[category].pop(0)
    avg = sum(performance_metrics[category]) / len(performance_metrics[category])
    print(f"[PERFORMANCE] {category}: {execution_time:.2f}ms (Avg: {avg:.2f}ms)")

def print_performance_table():
    print("\n===== PERFORMANCE METRICS =====")
    for category, times in performance_metrics.items():
        if not times:
            continue
        avg = sum(times) / len(times)
        min_time = min(times)
        max_time = max(times)
        last = times[-1]
        print(f"{category}: Last={last:.2f}ms, Avg={avg:.2f}ms, Min={min_time:.2f}ms, Max={max_time:.2f}ms, Count={len(times)}")
    print("===============================\n")

# Schedule periodic performance table printing
import threading
def schedule_performance_printing():
    threading.Timer(60.0, schedule_performance_printing).start()
    print_performance_table()

schedule_performance_printing()

# Document indexing and search
document_index = {
    "word_to_documents": {},  # word -> [document IDs]
    "document_content": {},   # document ID -> content
    "document_names": {},     # document ID -> filename
    "last_updated": None
}

def load_and_index_documents():
    start_time = time.time()
    print("Loading document data...")
    document_data = {}
    try:
        with open("document_contents.json", "r") as file:
            document_data = json.load(file)
        print(f"Loaded {len(document_data)} documents from JSON file.")
    except Exception as error:
        print(f"Error loading document JSON file: {error}")

    track_performance("documentLoading", (time.time() - start_time) * 1000)
    build_inverted_index(document_data)

def build_inverted_index(documents):
    start_time = time.time()
    print("Building inverted index...")
    document_index["word_to_documents"] = {}
    document_index["document_content"] = {}
    document_index["document_names"] = {}
    document_index["last_updated"] = datetime.now()

    doc_id = 0
    for filename, content in documents.items():
        document_index["document_content"][doc_id] = content
        document_index["document_names"][doc_id] = filename

        words = content.lower().replace(/[^\w\s]/g, ' ').split()
        words = [word for word in words if len(word) > 3 and not is_stop_word(word)]
        unique_words = set(words)

        for word in unique_words:
            if word not in document_index["word_to_documents"]:
                document_index["word_to_documents"][word] = set()
            document_index["word_to_documents"][word].add(doc_id)

        doc_id += 1

    for word in document_index["word_to_documents"]:
        document_index["word_to_documents"][word] = list(document_index["word_to_documents"][word])

    track_performance("indexBuilding", (time.time() - start_time) * 1000)
    print(f"Indexed {doc_id} documents with {len(document_index['word_to_documents'])} unique terms.")

def is_stop_word(word):
    stopwords = ['the', 'and', 'that', 'have', 'for', 'not', 'this', 'with', 'you', 'but']
    return word in stopwords

def search_documents_with_index(query):
    start_time = time.time()
    search_terms = query.lower().replace(/[^\w\s]/g, ' ').split()
    search_terms = [word for word in search_terms if len(word) > 3 and not is_stop_word(word)]

    if not search_terms:
        track_performance("documentSearch", (time.time() - start_time) * 1000)
        return {}

    document_scores = {}
    for term in search_terms:
        matching_doc_ids = document_index["word_to_documents"].get(term, [])
        for doc_id in matching_doc_ids:
            document_scores[doc_id] = document_scores.get(doc_id, 0) + 1

    results = {}
    for doc_id, score in document_scores.items():
        if score / len(search_terms) >= 0.25:
            filename = document_index["document_names"][doc_id]
            content = document_index["document_content"][doc_id]
            contexts = extract_contexts(content, search_terms)
            results[filename] = {
                "match_count": score,
                "contexts": contexts
            }

    track_performance("documentSearch", (time.time() - start_time) * 1000)
    print(f"Search for '{query}' found {len(results)} relevant documents.")
    return results

def extract_contexts(content, search_terms):
    contexts = []
    content_lower = content.lower()
    for term in search_terms:
        start_index = 0
        while True:
            term_index = content_lower.find(term, start_index)
            if term_index == -1:
                break
            context_start = max(0, term_index - 100)
            context_end = min(len(content), term_index + len(term) + 100)
            context = content[context_start:context_end].strip()
            contexts.append(context)
            start_index = term_index + len(term)
            if len(contexts) >= 3:
                break
    return list(set(contexts))[:5]

# ElevenLabs TTS function
def generate_elevenlabs_audio(text):
    url = f"https://api.elevenlabs.io/v1/convai/voice/generate?agent_id={ELEVENLABS_AGENT_ID}"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json"
    }
    data = {
        "text": text,
        "voice_id": "hope",  # Using "Hope" voice
        "encoding": "mp3"    # Audio format (MP3)
    }
    response = requests.post(url, json=data, headers=headers)
    if response.status_code == 200:
        audio_data = response.json()
        audio_url = audio_data.get("audio_url")
        return audio_url
    else:
        print("Error generating audio:", response.text)
        return None

# MAT prompt for OpenAI
MAT_PROMPT = """
You are Mat, a friendly professional from MultipleAI Solutions in Perth, Australia. You are a human representative, NOT an AI.

CRITICAL: Review the FULL conversation history before responding. NEVER repeat greetings or introduce yourself again if you've already done so.

RULES:
1. IF THIS IS YOUR FIRST MESSAGE:
   - Start with warm greeting and 3-4 sentences of genuine ice breaker conversation.
   - Example: "Hi there! This is Mat from MultipleAI Solutions. Beautiful day in Perth today! Have you been enjoying the sunshine? I managed to get out for a bike ride this morning before work."

2. FOR ALL SUBSEQUENT MESSAGES:
   - NEVER introduce yourself again or repeat greetings.
   - Continue the conversation naturally based on context.
   - Respond directly to what the user just said.

3. BUSINESS DISCUSSION:
   - Only after establishing rapport, discuss business needs.
   - "The reason I'm calling is to learn about your business needs..."

4. MAINTAIN CONTEXT AWARENESS:
   - If user mentions something confusing, politely ask for clarification.
   - Never pretend you discussed something you didn't.

5. BOOKING MEETINGS:
   - If customer shows interest, suggest scheduling a meeting.
   - Add [Appointment Suggested] tag if appropriate.
"""

# Route to handle outbound call
@app.route('/outbound-call', methods=['POST'])
def initiate_outbound_call():
    data = request.json
    number = data.get('number')
    if not number:
        return jsonify({"error": "Phone number is required"}), 400

    try:
        call = twilio_client.calls.create(
            from_=TWILIO_PHONE_NUMBER,
            to=number,
            url=f"https://{request.host}/outbound-call-twiml"
        )
        return jsonify({
            "success": True,
            "message": "Call initiated",
            "callSid": call.sid
        })
    except Exception as error:
        print(f"Error initiating outbound call: {error}")
        return jsonify({"success": False, "error": "Failed to initiate call"}), 500

# Route to handle TwiML response
@app.route('/outbound-call-twiml', methods=['GET', 'POST'])
def outbound_call_twiml():
    prompt = "Hello, this is Hope. How can I assist you today?"
    audio_url = generate_elevenlabs_audio(prompt)
    if not audio_url:
        return "Error generating voice response", 500

    response = VoiceResponse()
    response.play(audio_url)
    return str(response)

# Route for the index page
@app.route('/')
def index():
    return '''
    <html>
        <body>
            <h1>Initiate Outbound Call</h1>
            <form id="callForm">
                <label for="number">Enter Phone Number:</label>
                <input type="text" id="number" name="number" required>
                <button type="submit">Call</button>
            </form>
            <script>
                document.getElementById('callForm').addEventListener('submit', function(e) {
                    e.preventDefault();
                    fetch('/outbound-call', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({ number: document.getElementById('number').value })
                    }).then(response => response.json())
                      .then(data => console.log(data))
                      .catch(error => console.error('Error:', error));
                });
            </script>
        </body>
    </html>
    '''

if __name__ == '__main__':
    load_and_index_documents()
    app.run(debug=True, host='0.0.0.0', port=5000)
