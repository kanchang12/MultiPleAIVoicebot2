import os
import json
import websocket
import requests
from flask import Flask, request, render_template, jsonify
from dotenv import load_dotenv
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Connect, Stream

# Load environment variables
load_dotenv()

# Twilio and ElevenLabs credentials
ELEVENLABS_API_KEY = os.getenv('ELEVENLABS_API_KEY')
ELEVENLABS_AGENT_ID = os.getenv('ELEVENLABS_AGENT_ID')
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')
BASE_URL = "https://handsome-marquita-onewebonly-bffca566.koyeb.app"

if not all([ELEVENLABS_API_KEY, ELEVENLABS_AGENT_ID, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER]):
    raise ValueError('Missing required environment variables')

app = Flask(__name__)
PORT = int(os.getenv('PORT', 8000))
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

def get_signed_url():
    """Fetch signed URL for ElevenLabs conversation."""
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

@app.route('/outbound-call-twiml', methods=['GET', 'POST'])
def outbound_call_twiml():
    response = VoiceResponse()
    connect = Connect()
    stream = Stream(url=f"wss://{request.host}/outbound-media-stream")
    connect.append(stream)
    response.append(connect)
    return str(response), 200, {'Content-Type': 'text/xml'}

def send_appointment_sms(to_number, message):
    try:
        twilio_client.messages.create(
            body=message,
            from_=TWILIO_PHONE_NUMBER,
            to=to_number
        )
        print(f"SMS sent to {to_number}")
    except Exception as e:
        print(f"Error sending SMS: {e}")

@app.route('/outbound-media-stream')
def outbound_media_stream():
    if request.environ.get('wsgi.websocket'):
        ws = request.environ['wsgi.websocket']
        print("[Server] Twilio connected to outbound media stream")

        stream_sid, call_sid, elevenlabs_ws, to_number = None, None, None, None

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
                import threading
                threading.Thread(target=elevenlabs_ws.run_forever, daemon=True).start()
            except Exception as e:
                print(f"[ElevenLabs] Setup error: {e}")

        def on_elevenlabs_message(wsapp, message):
            nonlocal stream_sid, to_number
            try:
                msg = json.loads(message)
                print(f"[ElevenLabs] Message received: {msg}")
                if msg.get("type") == "audio" and stream_sid:
                    print(f"[Server] Sending audio chunk to Twilio, streamSid: {stream_sid}")
                    ws.send(json.dumps({"event": "media", "streamSid": stream_sid, "media": {"payload": msg["audio"]["chunk"]}}))
                elif msg.get("type") == "agent_response" and to_number:
                    agent_response = msg.get("agent_response_event", {}).get("agent_response", "")
                    print(f"[Server] Agent Response: {agent_response}")
                    if any(word in agent_response.lower() for word in ["appointment", "schedule", "book"]):
                        send_appointment_sms(to_number, "Your appointment has been confirmed.")
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
                    stream_sid, call_sid = msg["start"].get("streamSid"), msg["start"].get("callSid")
                    call_info = twilio_client.calls(call_sid).fetch() if call_sid else None
                    to_number = call_info.to if call_info else None
                    print(f"[Server] Call started: streamSid={stream_sid}, callSid={call_sid}, to={to_number}")
                    setup_elevenlabs()
                elif msg.get("event") == "media" and elevenlabs_ws:
                    print(f"[Server] Sending media to ElevenLabs: {msg['media']}")
                    elevenlabs_ws.send(json.dumps({"user_audio_chunk": msg["media"]["payload"]}))
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
    from gevent import pywsgi
    from geventwebsocket.handler import WebSocketHandler
    print(f"[Server] Running on port {PORT}")
    pywsgi.WSGIServer(('0.0.0.0', PORT), app, handler_class=WebSocketHandler).serve_forever()
