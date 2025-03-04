import os
import json
import requests
from flask import Flask, request, jsonify, render_template
from twilio.twiml.voice_response import VoiceResponse
from twilio.rest import Client
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Twilio credentials
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')

# ElevenLabs credentials
ELEVENLABS_API_KEY = os.getenv('ELEVENLABS_API_KEY')
ELEVENLABS_AGENT_ID = os.getenv('ELEVENLABS_AGENT_ID')

# Ensure all required variables are available
if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER, ELEVENLABS_API_KEY, ELEVENLABS_AGENT_ID]):
    raise ValueError("Missing required environment variables")

# Use the given Koyeb URL directly
BASE_URL = 'https://handsome-marquita-onewebonly-bffca566.koyeb.app/'

# Initialize Flask app and Twilio client
app = Flask(__name__)
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


@app.route('/')
def index():
    # This will render the index.html file
    return render_template('index.html')

# Endpoint for initiating outbound calls
@app.route('/outbound-call', methods=['POST'])
def outbound_call():
    data = request.json
    number = data.get('number')
    if not number:
        return jsonify({"error": "Phone number is required"}), 400

    try:
        # Make the outbound call using Twilio
        call = twilio_client.calls.create(
            from_=TWILIO_PHONE_NUMBER,
            to=number,
            url=f"{BASE_URL}outbound-call-twiml"
        )
        return jsonify({"success": True, "message": "Call initiated", "callSid": call.sid})
    except Exception as e:
        print(f"Error initiating outbound call: {e}")
        return jsonify({"success": False, "error": "Failed to initiate call"}), 500

# Endpoint to handle the Twilio call and respond with voice instructions
@app.route('/outbound-call-twiml', methods=['POST'])
def outbound_call_twiml():
    response = VoiceResponse()
    response.say("Please state your request after the beep.")
    response.record(
        action=f"{BASE_URL}process-speech", 
        method="POST", 
        max_length=30,
        timeout=10
    )
    return str(response)

# Endpoint to process speech input received from Twilio
@app.route('/process-speech', methods=['POST'])
def process_speech():
    recording_url = request.form.get('RecordingUrl')
    if not recording_url:
        return jsonify({"error": "No speech recorded"}), 400
    
    # Send speech to ElevenLabs for processing
    try:
        # Send the recorded URL (or text input) to ElevenLabs for processing
        response = requests.post(
            f"https://api.elevenlabs.io/v1/agents/{ELEVENLABS_AGENT_ID}/process", 
            headers={"xi-api-key": ELEVENLABS_API_KEY},
            json={"input": {"text": recording_url}}  # Send the URL or text (depending on ElevenLabs requirements)
        )
        response.raise_for_status()
        result = response.json()
        agent_response = result.get('response')

        # If ElevenLabs returns a response, send the audio to Twilio for playback
        if agent_response:
            # Generate an audio file (ElevenLabs provides this)
            audio_url = result.get('audio_url')  # This URL should be from ElevenLabs, containing the audio response
            twilio_response = VoiceResponse()
            twilio_response.play(audio_url)  # Play the ElevenLabs generated audio
            return str(twilio_response)
        else:
            return jsonify({"error": "No response from ElevenLabs"}), 400
    except Exception as e:
        print(f"Error processing speech with ElevenLabs: {e}")
        return jsonify({"error": "Failed to process speech with ElevenLabs"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
