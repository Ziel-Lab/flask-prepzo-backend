"""
Flask server implementation for Prepzo backend
"""
import os
import uuid
import pathlib
import logging
from flask import Flask, jsonify, request, session, redirect, abort
from flask_cors import CORS
from asgiref.wsgi import WsgiToAsgi
from datetime import timedelta, datetime
import aiofiles
from dotenv import load_dotenv
from livekit import api
from supabase import create_client
from ..config import settings
from ..utils.logging_config import setup_logger
from functools import wraps

# Load environment variables
load_dotenv()

# Configure logging
logger = setup_logger("server")


# --- ADD SUPABASE CONFIGURATION ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") # Use SERVICE ROLE KEY for backend verification

if not SUPABASE_URL or not SUPABASE_KEY:
    logger.error("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY environment variables.")
    # Depending on your app's needs, you might want to exit or handle this differently
    # raise ValueError("Supabase URL and Key must be configured.") 
else:
    logger.info("Supabase URL and Key loaded.")
    
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
logger.info("Supabase client initialized.")
# --- END SUPABASE CONFIGURATION ---

# --- ADD INTERNAL API KEY VERIFICATION DECORATOR ---
def require_internal_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        expected_key = os.environ.get('FLASK_INTERNAL_API_KEY')
        provided_key = request.headers.get('X-Internal-API-Key')

        # Basic validation
        if not expected_key:
            logger.error("Internal API Key is not configured on the server (FLASK_INTERNAL_API_KEY).")
            abort(500, 'Server configuration error') # Internal server error if key isn't set

        if not provided_key:
            logger.warning("Request missing X-Internal-API-Key header.")
            abort(401, 'Missing internal API key header')

        if provided_key != expected_key:
            logger.warning("Invalid internal API key provided.")
            abort(401, 'Invalid internal API key') # Use 401 Unauthorized or 403 Forbidden

        # Key is valid, proceed with the original function
        logger.info("Internal API key verified successfully.")
        return f(*args, **kwargs)
    return decorated_function
# --- END INTERNAL API KEY VERIFICATION DECORATOR ---

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
@app.route("/api/check-auth", methods=['GET'])
def check_auth():
    """Checks ONLY for recent password verification via Flask session."""
    # Removed Supabase check variables
    # supabase_authenticated = False
    # user_info = None
    password_recently_verified = False

    # Removed Supabase token verification block
    # try:
    #     verify_supabase_token() 
    #     supabase_authenticated = True
    #     user_info = { ... }
    #     logger.info(f"Supabase auth check successful for user: {g.user.email}")
    # except Exception as e:
    #     logger.info(f"Supabase auth check failed or no token present: {type(e).__name__}")
    #     pass 

    # Check Flask session for recent password verification
    try:
        password_verified_at = session.get('password_verified_at')
        if password_verified_at:
            if isinstance(password_verified_at, datetime):
                time_since_verified = datetime.utcnow() - password_verified_at
                session_lifetime = app.config.get('PERMANENT_SESSION_LIFETIME', timedelta(minutes=30))
                if time_since_verified < session_lifetime:
                    password_recently_verified = True
                    logger.info("Password session check: Verified within lifetime.")
                else:
                    logger.info("Password session check: Timestamp present but expired.")
            else:
                 logger.warning("Password session check: 'password_verified_at' is not a datetime object.")
        else:
            logger.info("Password session check: Timestamp not found in session.")
    except Exception as session_err:
        logger.error(f"Error checking password session: {session_err}", exc_info=True)

    # Determine final status based ONLY on password check
    final_status = password_recently_verified
    
    logger.info(f"Final Auth Check: PasswordRecent={password_recently_verified}")
    
    # Return 200 OK, but include detailed status for frontend
    return jsonify({
        "authenticated": final_status, 
        "password_recently_verified": password_recently_verified,
        # Removed: "supabase_authenticated": supabase_authenticated,
        # Removed: "user": user_info 
    }), 200

# Password verification endpoint
@app.route("/api/verify-password", methods=['POST'])
def verify_password():
    # Bypass password verification in development environment
    if APP_ENV == 'development':
        session['password_verified_at'] = datetime.utcnow() # Store timestamp
        session.permanent = True
        return jsonify({"message": "Authentication successful (dev mode)"}), 200

    data = request.get_json()
    if not data or 'password' not in data:
        return jsonify({"error": "Password required"}), 400

    submitted_password = data['password']
    # Check if the submitted password is in the set of valid passwords
    if submitted_password in VALID_PASSWORDS:
        session['password_verified_at'] = datetime.utcnow() # Store timestamp
        session.permanent = True # Use the configured session lifetime
        logger.info("Password verified successfully, timestamp stored in session.")
        return jsonify({"message": "Authentication successful"}), 200
    else:
        logger.warning("Invalid password submitted.")
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
@require_internal_api_key
def process_resume():
    """Receives resume data, requires internal API key auth."""
    logger.info(f"process-resume endpoint accessed with valid internal API key.")
    
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

        # Save the file synchronously (Replaced aiofiles)
        try:
            # Use file.save() which handles streaming data safely
            file.save(file_path) 
            logger.info(f"Resume for session {session_id} saved to {file_path}")
            return jsonify({"message": "Resume received and saved successfully"}), 200
        except Exception as save_err:
            logger.error(f"Error saving file {file_path}: {save_err}", exc_info=True) # Added exc_info
            return jsonify({"error": "Failed to save resume file on server"}), 500

    except Exception as e:
        logger.error(f"Error processing resume request: {e}", exc_info=True) # Added exc_info
        return jsonify({"error": "Failed to process resume"}), 500

# Create ASGI app
asgi_app = WsgiToAsgi(app)

def run_server(host="0.0.0.0", port=5001, reload=True):
    """Run the server using uvicorn"""
    import uvicorn
    reload_setting = reload or (APP_ENV == 'development')
    logger.info(f"Starting server on {host}:{port} with reload={reload_setting}")
    uvicorn.run(asgi_app, host=host, port=port, reload=reload_setting)

# For direct execution
if __name__ == "__main__":
    run_server() 