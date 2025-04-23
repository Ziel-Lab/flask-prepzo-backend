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

# Get Application Environment (default to 'production' if not set)
APP_ENV = os.environ.get('APP_ENV').lower()

# Load the page passwords from environment variables (comma-separated)
# Use a default list for development if not set
PAGE_PASSWORDS_STR = os.environ.get('PAGE_PASSWORDS', 'password123')
VALID_PASSWORDS = {pw.strip() for pw in PAGE_PASSWORDS_STR.split(',') if pw.strip()}

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
    # Bypass auth check in development environment
    if APP_ENV == 'development':
        return jsonify({"authenticated": True}), 200

    if session.get('authenticated'):
        return jsonify({"authenticated": True}), 200
    else:
        return jsonify({"authenticated": False}), 401 # Use 401 to indicate not authorized

# Endpoint to verify the password and set the session
@app.route("/verify-password", methods=['POST'])
def verify_password():
    # Bypass password verification in development environment
    if APP_ENV == 'development':
        session['authenticated'] = True
        session.permanent = True
        return jsonify({"message": "Authentication successful (dev mode)"}), 200

    data = request.get_json()
    if not data or 'password' not in data:
        return jsonify({"error": "Password required"}), 400

    submitted_password = data['password']
    # Check if the submitted password is in the set of valid passwords
    if submitted_password in VALID_PASSWORDS:
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
            room=room
        ))
    
    return token.to_jwt()

# Wrap the Flask app with the ASGI adapter
asgi_app = WsgiToAsgi(app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(asgi_app, host="0.0.0.0", port=5001)
