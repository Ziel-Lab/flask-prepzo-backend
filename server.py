import os
import uuid
from livekit import api
from flask import Flask, jsonify, request, session
from dotenv import load_dotenv
from flask_cors import CORS
from livekit.api import LiveKitAPI, ListRoomsRequest
from asgiref.wsgi import WsgiToAsgi
from datetime import timedelta
import aiofiles # For async file operations
import pathlib

load_dotenv()

app = Flask(__name__)
# Allow requests from any origin, but explicitly support credentials for session cookies
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# Session Configuration
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'a_default_secret_key_for_development') # Load from env or use default
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30) # Set session lifetime to 30 minutes

# Get Application Environment (default to 'production' if not set)
APP_ENV = os.environ.get('APP_ENV', 'production').lower() # Added default 'production'

# Load the page passwords from environment variables (comma-separated)
# Use a default list for development if not set
PAGE_PASSWORDS_STR = os.environ.get('PAGE_PASSWORDS', 'password123')
VALID_PASSWORDS = {pw.strip() for pw in PAGE_PASSWORDS_STR.split(',') if pw.strip()}

UPLOAD_FOLDER = pathlib.Path('./uploads') # Store uploads in an 'uploads' folder
UPLOAD_FOLDER.mkdir(exist_ok=True) # Create the folder if it doesn't exist

async def generate_room_name(): # Made async
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
    name = "my_identity" # Changed default identity for clarity
    room = await generate_room_name() # Ensure this is awaited

    # Use environment variables securely
    livekit_api_key = os.getenv("LIVEKIT_API_KEY")
    livekit_api_secret = os.getenv("LIVEKIT_API_SECRET")

    if not livekit_api_key or not livekit_api_secret:
        print("Error: LIVEKIT_API_KEY or LIVEKIT_API_SECRET not set in environment variables.") # Use logger ideally
        return jsonify({"error": "Server configuration error"}), 500

    token = api.AccessToken(livekit_api_key, livekit_api_secret) \
        .with_identity(name) \
        .with_name(name) \
        .with_grants(api.VideoGrants(
            room_join=True,
            room=room
        ))

    # Return JSON structure consistent with frontend expectations (if any)
    return jsonify({
        "identity": name,
        "accessToken": token.to_jwt(),
        "roomName": room # Include room name in response
        })


# --- New Endpoint for Resume Processing ---
@app.route("/api/process-resume", methods=['POST'])
async def process_resume():
    """Receives resume data from the Next.js backend"""
    try:
        # Assuming Next.js sends FormData with 'resume' (file) and 'session_id' (text)
        if 'resume' not in request.files:
            print("Error: No resume file part in the request") # Use proper logging
            return jsonify({"error": "No resume file part in the request"}), 400
        if 'session_id' not in request.form:
             print("Error: No session_id provided in the form") # Use proper logging
             return jsonify({"error": "No session_id provided"}), 400

        file = request.files['resume']
        session_id = request.form['session_id']

        if file.filename == '':
            print("Warning: No file selected in the upload") # Use proper logging
            return jsonify({"error": "No selected file"}), 400

        # Basic sanitization of session_id if needed (depends on format)
        # Example: filename = secure_filename(file.filename) # If using original filename

        # Construct a safe path using the session_id
        # Ensure session_id doesn't contain path traversal characters if used directly
        # Using a fixed prefix and extension is safer
        file_extension = pathlib.Path(file.filename).suffix # Get original extension
        # Basic validation for common resume extensions
        allowed_extensions = ['.pdf', '.doc', '.docx']
        if file_extension.lower() not in allowed_extensions:
             print(f"Error: Invalid file type received: {file_extension}") # Use proper logging
             return jsonify({"error": f"Invalid file type. Allowed: {', '.join(allowed_extensions)}"}), 400

        safe_filename = f"{session_id}_resume{file_extension}"
        file_path = UPLOAD_FOLDER / safe_filename

        # Save the file asynchronously
        try:
            async with aiofiles.open(file_path, 'wb') as f:
                # Read chunks to avoid loading large files entirely into memory at once
                chunk_size = 8192 # 8KB chunks
                while True:
                    chunk = file.stream.read(chunk_size)
                    if not chunk:
                        break
                    await f.write(chunk)
            print(f"Resume for session {session_id} saved to {file_path}") # Use proper logging
            return jsonify({"message": "Resume received and saved successfully"}), 200
        except Exception as save_err:
            print(f"Error saving file {file_path}: {save_err}") # Use proper logging
            return jsonify({"error": "Failed to save resume file on server"}), 500

    except Exception as e:
        print(f"Error processing resume request: {e}") # Use proper logging
        # Consider logging traceback here for debugging
        # import traceback
        # print(traceback.format_exc())
        return jsonify({"error": "Failed to process resume"}), 500
# --- End New Endpoint ---


# Wrap the Flask app with the ASGI adapter
asgi_app = WsgiToAsgi(app)

if __name__ == "__main__":
    import uvicorn
    # Set reload=True for development, False for production
    uvicorn.run(asgi_app, host="0.0.0.0", port=5001, reload=(APP_ENV == 'development'))
