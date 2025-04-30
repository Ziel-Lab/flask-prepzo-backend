"""
Flask server implementation for Prepzo backend
"""
import os
import uuid
import pathlib
import logging
from flask import Flask, jsonify, request, session
from flask_cors import CORS
from asgiref.wsgi import WsgiToAsgi
from datetime import timedelta
import aiofiles
from dotenv import load_dotenv
from livekit import api
from ..config import settings
from ..utils.logging_config import setup_logger

# Load environment variables
load_dotenv()

# Configure logging
logger = setup_logger("server")

# Initialize Flask app
app = Flask(__name__)

# Configure CORS
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# Session Configuration
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'a_default_secret_key_for_development') 
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30) 

# Get Application Environment
APP_ENV = os.environ.get('APP_ENV', 'production').lower()

# Load page passwords
PAGE_PASSWORDS_STR = os.environ.get('PAGE_PASSWORDS', 'password123')
VALID_PASSWORDS = {pw.strip() for pw in PAGE_PASSWORDS_STR.split(',') if pw.strip()}

# Ensure uploads directory exists
UPLOAD_FOLDER = settings.UPLOAD_FOLDER
UPLOAD_FOLDER.mkdir(exist_ok=True)

async def generate_room_name():
    """Generate a random room name"""
    return "room-" + str(uuid.uuid4())[:8]

# Root route
@app.route("/")
def index():
    return "Prepzo backend server is running"

# Health check endpoint
@app.route("/health")
def health_check():
    """Simple health check endpoint for monitoring"""
    return jsonify({
        "status": "ok",
        "service": "prepzo-backend",
        "version": settings.__version__
    }), 200

# Authentication check endpoint
@app.route("/check-auth", methods=['GET'])
def check_auth():
    # Bypass auth check in development environment
    if APP_ENV == 'development':
        return jsonify({"authenticated": True}), 200

    if session.get('authenticated'):
        return jsonify({"authenticated": True}), 200
    else:
        return jsonify({"authenticated": False}), 401

# Password verification endpoint
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
        session.permanent = True
        return jsonify({"message": "Authentication successful"}), 200
    else:
        return jsonify({"error": "Invalid password"}), 401

# LiveKit token generation endpoint
@app.route("/getToken")
async def get_token():
    # Generate a new random room name each time
    name = "my_identity"
    room = await generate_room_name()

    # Use environment variables
    livekit_api_key = os.getenv("LIVEKIT_API_KEY")
    livekit_api_secret = os.getenv("LIVEKIT_API_SECRET")

    if not livekit_api_key or not livekit_api_secret:
        logger.error("Error: LIVEKIT_API_KEY or LIVEKIT_API_SECRET not set")
        return jsonify({"error": "Server configuration error"}), 500

    token = api.AccessToken(livekit_api_key, livekit_api_secret) \
        .with_identity(name) \
        .with_name(name) \
        .with_grants(api.VideoGrants(
            room_join=True,
            room=room
        ))

    # Return token and room info
    return jsonify({
        "identity": name,
        "accessToken": token.to_jwt(),
        "roomName": room
    })

# Resume processing endpoint
@app.route("/api/process-resume", methods=['POST'])
async def process_resume():
    """Receives resume data from the frontend"""
    try:
        # Check for resume file and session ID
        if 'resume' not in request.files:
            logger.error("No resume file part in the request")
            return jsonify({"error": "No resume file part in the request"}), 400
            
        if 'session_id' not in request.form:
            logger.error("No session_id provided in the form")
            return jsonify({"error": "No session_id provided"}), 400

        file = request.files['resume']
        session_id = request.form['session_id']

        if file.filename == '':
            logger.warning("No file selected in the upload")
            return jsonify({"error": "No selected file"}), 400

        # Validate file extension
        file_extension = pathlib.Path(file.filename).suffix
        allowed_extensions = ['.pdf', '.doc', '.docx']
        if file_extension.lower() not in allowed_extensions:
            logger.error(f"Invalid file type received: {file_extension}")
            return jsonify({"error": f"Invalid file type. Allowed: {', '.join(allowed_extensions)}"}), 400

        # Create safe filename and path
        safe_filename = f"{session_id}_resume{file_extension}"
        file_path = UPLOAD_FOLDER / safe_filename

        # Save the file asynchronously
        try:
            async with aiofiles.open(file_path, 'wb') as f:
                # Read chunks to avoid loading large files entirely into memory
                chunk_size = 8192  # 8KB chunks
                while True:
                    chunk = file.stream.read(chunk_size)
                    if not chunk:
                        break
                    await f.write(chunk)
            logger.info(f"Resume for session {session_id} saved to {file_path}")
            return jsonify({"message": "Resume received and saved successfully"}), 200
        except Exception as save_err:
            logger.error(f"Error saving file {file_path}: {save_err}")
            return jsonify({"error": "Failed to save resume file on server"}), 500

    except Exception as e:
        logger.error(f"Error processing resume request: {e}")
        return jsonify({"error": "Failed to process resume"}), 500

# Create ASGI app
asgi_app = WsgiToAsgi(app)

def run_server(host="0.0.0.0", port=5001, reload=False):
    """Run the server using uvicorn"""
    import uvicorn
    reload_setting = reload or (APP_ENV == 'development')
    logger.info(f"Starting server on {host}:{port} with reload={reload_setting}")
    uvicorn.run(asgi_app, host=host, port=port, reload=reload_setting)

# For direct execution
if __name__ == "__main__":
    run_server() 