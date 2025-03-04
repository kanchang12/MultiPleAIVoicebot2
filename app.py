import os
import json
import websocket
from flask import Flask, request, render_template, jsonify
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Connect, Stream
from dotenv import load_dotenv
import threading
import requests

# Load environment variables
load_dotenv()

# Twilio and ElevenLabs credentials
ELEVENLABS_API_KEY = os.getenv('ELEVENLABS_API_KEY')
ELEVENLABS_AGENT_ID = os.getenv('ELEVENLABS_AGENT_ID')
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')

BASE_URL = 'https://handsome-marquita-onewebonly-bffca566.koyeb.app'
if not all([ELEVENLABS_API_KEY, ELEVENLABS_AGENT_ID, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER, BASE_URL]):
    raise ValueError('Missing required environment variables')

app = Flask(__name__)
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Fetch signed URL for ElevenLabs WebSocket
def get_signed_url():
    try:
        response = requests.get(
            f"https://api.elevenlabs.io/v1/convai/conversation/get_signed_url?agent_id={ELEVENLABS_AGENT_ID}",
            headers={"xi-api-key": ELEVENLABS_API_KEY}
        )
        response.raise_for_status()
        return response.json()["signed_url"]
    except Exception as e:
        print(f"Error getting signed URL: {e}")
        raise

@app.route('/')
def index():
    # This will render the index.html file
    return render_template('index.html')

@app.route('/outbound-call', methods=['POST'])
def outbound_call():
    data = request.json
    number = data.get('number')
    if not number:
        return jsonify({"error": "Phone number is required"}), 400

    try:
        call = twilio_client.calls.create(
            from_=TWILIO_PHONE_NUMBER,
            to=number,
            url=f"{BASE_URL}/outbound-call-twiml"
        )
        return jsonify({"success": True, "message": "Call initiated", "callSid": call.sid})
    except Exception as e:
        print(f"Error initiating outbound call: {e}")
        return jsonify({"success": False, "error": "Failed to initiate call"}), 500


# TwiML that Twilio will use to connect the call
@app.route('/outbound-call-twiml', methods=['GET', 'POST'])
def outbound_call_twiml():
    response = VoiceResponse()
    connect = Connect()
    stream = Stream(url="wss://handsome-marquita-onewebonly-bffca566.koyeb.app/outbound-media-stream")
    connect.append(stream)
    response.append(connect)
    return str(response), 200, {'Content-Type': 'text/xml'}

# Status callback to track the call's progress
@app.route('/statusCallback', methods=['POST'])
def status_callback():
    call_status = request.form.get('CallStatus')
    print(f"Call Status: {call_status}")
    return '', 200

# WebSocket to handle media streaming with ElevenLabs
@app.route('/outbound-media-stream')
def outbound_media_stream():
    if request.environ.get('wsgi.websocket'):
        ws = request.environ['wsgi.websocket']
        print("[Server] WebSocket connected to handle media stream")

        elevenlabs_ws = None
        def setup_elevenlabs():
            nonlocal elevenlabs_ws
            try:
                print("[Server] Setting up ElevenLabs WebSocket")
                signed_url = get_signed_url()
                elevenlabs_ws = websocket.WebSocketApp(
                    signed_url,
                    on_message=on_elevenlabs_message,
                    on_close=lambda ws, code, msg: print(f"[ElevenLabs] Disconnected with code {code}: {msg}"),
                    on_error=lambda ws, error: print(f"[ElevenLabs] Error: {error}")
                )
                threading.Thread(target=elevenlabs_ws.run_forever, daemon=True).start()
            except Exception as e:
                print(f"[ElevenLabs] Setup error: {e}")

        def on_elevenlabs_message(wsapp, message):
            try:
                msg = json.loads(message)
                print(f"[ElevenLabs] Message received: {msg}")
                if msg.get("type") == "agent_response":
                    agent_response = msg.get("agent_response_event", {}).get("agent_response", "")
                    print(f"[Server] Agent Response: {agent_response}")
                    if any(word in agent_response.lower() for word in ["appointment", "schedule", "book"]):
                        # Trigger some action like sending an SMS (this can be expanded)
                        print(f"[Server] Appointment confirmed.")
            except Exception as e:
                print(f"[ElevenLabs] Error processing message: {e}")

        try:
            while True:
                message = ws.receive()
                if message is None:
                    print("[Server] WebSocket closed by Twilio")
                    break
                msg = json.loads(message)
                print(f"[Server] Twilio WebSocket message: {msg}")
                if msg.get("event") == "start":
                    print(f"[Server] Call started: {msg['start']}")
                    setup_elevenlabs()
                elif msg.get("event") == "stop":
                    print("[Server] Stopping WebSocket connection")
                    if elevenlabs_ws:
                        elevenlabs_ws.close()
                    break
        except Exception as e:
            print(f"[Twilio] WebSocket error: {e}")
        finally:
            if elevenlabs_ws:
                elevenlabs_ws.close()
            print("[Twilio] Client disconnected")
            return ''
    return "WebSocket required", 400

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
