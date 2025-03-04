import os
import json
import requests
from flask import Flask, request, jsonify, render_template
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Connect, Stream
import websocket
from dotenv import load_dotenv

# Initialize Flask app
app = Flask(__name__)

# Environment variables (These will be automatically available on Koyeb)
ELEVENLABS_API_KEY = os.getenv('ELEVENLABS_API_KEY')
ELEVENLABS_AGENT_ID = os.getenv('ELEVENLABS_AGENT_ID')
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')

# Initialize Twilio client
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Hardcoded prompt for the conversation
PROMPT = "Hello, I would like to schedule an appointment. Can you help me with that?"

# Helper function to get signed URL for ElevenLabs connection
def get_signed_url():
    response = requests.get(
        f"https://api.elevenlabs.io/v1/convai/conversation/get_signed_url?agent_id={ELEVENLABS_AGENT_ID}",
        headers={"xi-api-key": ELEVENLABS_API_KEY}
    )
    data = response.json()
    return data["signed_url"]

# Helper function to send an appointment confirmation SMS
def send_appointment_sms(to_number):
    try:
        message = "Thank you for scheduling an appointment with us. Your appointment has been confirmed."
        twilio_client.messages.create(
            body=message,
            from_=TWILIO_PHONE_NUMBER,
            to=to_number
        )
        print(f"SMS sent to {to_number}")
    except Exception as e:
        print(f"Error sending SMS: {e}")

# Route for the index page (form)
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/outbound-call', methods=['GET'])  # Use GET for the route
def initiate_outbound_call():
    number = request.args.get('number')  # Get the number from query parameters
    
    if not number:
        return jsonify({"error": "Phone number is required"}), 400
    
    try:
        # Create a call using Twilio
        call = twilio_client.calls.create(
            from_=TWILIO_PHONE_NUMBER,
            to=number,
            url=f"https://{request.host}/outbound-call-twiml"  # Ensure the URL is correctly formatted
        )
        return jsonify({
            "success": True,
            "message": "Call initiated",
            "callSid": call.sid
        })
    except Exception as error:
        print(f"Error initiating outbound call: {error}")
        return jsonify({"success": False, "error": "Failed to initiate call"}), 500


# TwiML route for outbound calls (now supports GET)
@app.route('/outbound-call-twiml', methods=['GET'])
def outbound_call_twiml():
    response = VoiceResponse()
    connect = Connect()
    stream = Stream(url=f"wss://{request.host}/outbound-media-stream")  # Correct WebSocket URL
    stream.parameter(name="prompt", value=PROMPT)  # Pass the predefined prompt
    connect.append(stream)
    response.append(connect)
    
    return str(response)


# WebSocket route for media streams
@app.route('/outbound-media-stream')
def outbound_media_stream():
    if request.environ.get('wsgi.websocket'):
        ws = request.environ['wsgi.websocket']
        print("[Server] Twilio connected to outbound media stream")
        
        elevenlabs_ws = None
        
        def setup_elevenlabs():
            nonlocal elevenlabs_ws
            signed_url = get_signed_url()
            elevenlabs_ws = websocket.WebSocketApp(
                signed_url,
                on_open=on_elevenlabs_open,
                on_message=on_elevenlabs_message,
                on_error=on_elevenlabs_error,
                on_close=on_elevenlabs_close
            )
            elevenlabs_ws.run_forever()
        
        def on_elevenlabs_open(wsapp):
            print("[ElevenLabs] Connected")
        
        def on_elevenlabs_message(wsapp, message):
            print("[ElevenLabs] Message received:", message)
            msg = json.loads(message)
            if msg.get("type") == "audio":
                audio_chunk = msg.get("audio", {}).get("chunk")
                if audio_chunk:
                    audio_data = {
                        "event": "media",
                        "media": {"payload": audio_chunk}
                    }
                    ws.send(json.dumps(audio_data))

            # Detect if the conversation involves an appointment (check for keywords)
            if msg.get("type") == "agent_response":
                agent_response = msg.get("agent_response_event", {}).get("agent_response", "")
                print(f"Agent response: {agent_response}")

                # Check if the response contains appointment-related keywords
                if any(keyword in agent_response.lower() for keyword in ["appointment", "schedule", "book", "reserve"]):
                    send_appointment_sms(ws.remote_address)  # Send SMS to the number
                    print(f"Appointment SMS sent to: {ws.remote_address}")

        def on_elevenlabs_error(wsapp, error):
            print("[ElevenLabs] Error:", error)

        def on_elevenlabs_close(wsapp, close_status_code, close_msg):
            print("[ElevenLabs] Connection closed")

        setup_elevenlabs()
        
        while True:
            message = ws.receive()
            if message is None:
                break
            msg = json.loads(message)
            if msg.get("event") == "media":
                audio_payload = msg.get("media", {}).get("payload")
                if audio_payload:
                    elevenlabs_ws.send(json.dumps({"user_audio_chunk": audio_payload}))
        
        print("[Twilio] Client disconnected")
        return ''

    return "WebSocket connection required", 400

if __name__ == '__main__':
    # Run Flask app on Koyeb's dynamically assigned port (8000)
    app.run(debug=True, host='0.0.0.0', port=8000)
