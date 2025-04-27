import os
import uuid
from livekit import api
from flask import Flask, jsonify, request, session
from dotenv import load_dotenv
from flask_cors import CORS
from livekit.api import LiveKitAPI, ListRoomsRequest
from asgiref.wsgi import WsgiToAsgi
from datetime import timedelta

load_dotenv()

app = Flask(__name__)
# Allow requests from any origin, but explicitly support credentials for session cookies
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# Session Configuration
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'a_default_secret_key_for_development') # Load from env or use default
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30) # Set session lifetime to 30 minutes

# Load the page password from environment variables
PAGE_PASSWORD = os.environ.get('PAGE_PASSWORD', 'password123') # Use a default for development if not set

def generate_room_name():
    # Create a random room name using UUID
    return "room-" + str(uuid.uuid4())[:8]

# Simple root route to confirm server is running
@app.route("/")
def index():
    return "server.py is running"

@app.route("/health")
def health_check():
    """Simple health check endpoint for monitoring"""
    return jsonify({
        "status": "ok",
        "service": "livekit-bot",
        "version": "1.0.0"
    }), 200

# Endpoint to check if the user is already authenticated via session
@app.route("/check-auth", methods=['GET'])
def check_auth():
    if session.get('authenticated'):
        return jsonify({"authenticated": True}), 200
    else:
        return jsonify({"authenticated": False}), 401 # Use 401 to indicate not authorized

# Endpoint to verify the password and set the session
@app.route("/verify-password", methods=['POST'])
def verify_password():
    data = request.get_json()
    if not data or 'password' not in data:
        return jsonify({"error": "Password required"}), 400

    submitted_password = data['password']
    if submitted_password == PAGE_PASSWORD:
        session['authenticated'] = True
        session.permanent = True  # Use the configured lifetime
        return jsonify({"message": "Authentication successful"}), 200
    else:
        return jsonify({"error": "Invalid password"}), 401

@app.route("/getToken")
async def get_token():
    # Use a default identity and generate a new random room name each time
    name = "my name"
    room = await generate_room_name()
    
    token = api.AccessToken(os.getenv("LIVEKIT_API_KEY"), os.getenv("LIVEKIT_API_SECRET")) \
        .with_identity(name) \
        .with_name(name) \
        .with_grants(api.VideoGrants(
            room_join=True,
            room=room,
            can_update_own_metadata=True
        ))
    
    return token.to_jwt()

# Wrap the Flask app with the ASGI adapter
asgi_app = WsgiToAsgi(app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(asgi_app, host="0.0.0.0", port=5001)
