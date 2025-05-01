"""
Flask server implementation for Prepzo backend
"""
import os
import uuid
import pathlib
import logging
import requests
from flask import Flask, jsonify, request, session, redirect
from flask_cors import CORS
from asgiref.wsgi import WsgiToAsgi
from datetime import timedelta
import aiofiles
from dotenv import load_dotenv
from livekit import api
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from ..config import settings
from ..utils.logging_config import setup_logger

# Load environment variables
load_dotenv()

# Configure logging
logger = setup_logger("server")

# Load OAuth Configuration from Environment Variables
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI")
LINKEDIN_CLIENT_ID = os.environ.get("LINKEDIN_CLIENT_ID")
LINKEDIN_CLIENT_SECRET = os.environ.get("LINKEDIN_CLIENT_SECRET")
LINKEDIN_REDIRECT_URI = os.environ.get("LINKEDIN_REDIRECT_URI")
FRONTEND_LOGIN_SUCCESS_URL = os.environ.get("FRONTEND_LOGIN_SUCCESS_URL", "/") # Default to root if not set
logger.info(f"Loaded FRONTEND_LOGIN_SUCCESS_URL: {FRONTEND_LOGIN_SUCCESS_URL}")

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
    # Bypass auth check in development environment
    if APP_ENV == 'development':
        return jsonify({"authenticated": True}), 200

    if session.get('authenticated'):
        return jsonify({"authenticated": True}), 200
    else:
        return jsonify({"authenticated": False}), 401

# Password verification endpoint
@app.route("/api/verify-password", methods=['POST'])
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

# --- Google OAuth Routes ---

@app.route('/api/auth/google/login')
def google_login():
    if not GOOGLE_CLIENT_ID or not GOOGLE_REDIRECT_URI:
         logger.error("Google OAuth Client ID or Redirect URI not configured.")
         return jsonify({"error": "Server configuration error"}), 500

    # Construct the Google authorization URL
    authorization_url = (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={GOOGLE_CLIENT_ID}&"
        f"redirect_uri={GOOGLE_REDIRECT_URI}&"
        "response_type=code&"
        "scope=openid%20email%20profile&" # Request basic profile info
        "access_type=offline&" # Request refresh token if needed for long-term access
        "prompt=consent" # Force consent screen for testing, remove for production?
    )
    # TODO: Add state parameter for CSRF protection
    # state = secrets.token_urlsafe(16)
    # session['oauth_state'] = state
    # authorization_url += f"&state={state}"

    logger.info(f"Redirecting user to Google for authentication: {authorization_url[:100]}...")
    return redirect(authorization_url)

@app.route('/api/auth/google/callback')
def google_callback():
    # TODO: Implement CSRF protection check using state parameter
    # received_state = request.args.get('state')
    # expected_state = session.pop('oauth_state', None)
    # if not received_state or received_state != expected_state:
    #     logger.warning("Invalid OAuth state parameter received.")
    #     return jsonify({"error": "Invalid state parameter"}), 400

    code = request.args.get('code')
    if not code:
        logger.warning("Authorization code not found in Google callback.")
        return jsonify({"error": "Authorization code not found"}), 400
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET or not GOOGLE_REDIRECT_URI:
         logger.error("Google OAuth credentials not fully configured for callback.")
         return jsonify({"error": "Server configuration error"}), 500

    try:
        # Exchange authorization code for tokens
        logger.info("Exchanging Google authorization code for tokens.")
        token_url = "https://oauth2.googleapis.com/token"
        token_data = {
            'code': code,
            'client_id': GOOGLE_CLIENT_ID,
            'client_secret': GOOGLE_CLIENT_SECRET,
            'redirect_uri': GOOGLE_REDIRECT_URI,
            'grant_type': 'authorization_code'
        }
        token_response = requests.post(token_url, data=token_data)
        token_response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        token_json = token_response.json()
        logger.info("Successfully exchanged Google code for tokens.")

        id_token_received = token_json.get('id_token')
        if not id_token_received:
            logger.error("ID token not found in Google token response.")
            return jsonify({"error": "ID token not found in response"}), 400

        # Verify the ID token
        try:
            logger.info("Verifying Google ID token.")
            # Specify the CLIENT_ID of the app that accesses the backend:
            idinfo = id_token.verify_oauth2_token(
                id_token_received,
                google_requests.Request(),
                GOOGLE_CLIENT_ID # Audience must match your client ID
            )
            logger.info("Google ID token verified successfully.")

            # ID token is valid. Get the user's Google Account ID from the decoded token.
            google_user_id = idinfo['sub']
            user_email = idinfo.get('email')
            user_name = idinfo.get('name')
            # user_picture = idinfo.get('picture')

            logger.info(f"Google User Info: ID={google_user_id}, Email={user_email}, Name={user_name}")

            # --- Placeholder for User Handling ---
            # TODO: Implement user lookup/creation logic here
            # Example:
            # user = find_or_create_user(google_id=google_user_id, email=user_email, name=user_name)
            # if not user:
            #    logger.error("Failed to find or create user after Google authentication.")
            #    return jsonify({"error": "User processing failed"}), 500
            # --- End Placeholder ---

            # Log the user into your application's session
            session.permanent = True
            session['authenticated'] = True
            session['auth_provider'] = 'google' # Store provider
            # Optionally store user ID or other non-sensitive info
            # session['user_id'] = user.id
            session['user_email'] = user_email # Store email for display/use
            session['user_name'] = user_name
            logger.info(f"User {user_email} authenticated via Google and session created.")

            # Redirect to the frontend success page
            logger.info(f"Attempting to redirect authenticated user to URL from variable: {FRONTEND_LOGIN_SUCCESS_URL}")
            return redirect(FRONTEND_LOGIN_SUCCESS_URL)

        except ValueError as e:
            # Invalid token
            logger.error(f"Error verifying Google ID token: {e}", exc_info=True)
            return jsonify({"error": "Invalid ID token"}), 401

    except requests.exceptions.RequestException as e:
        # Handle errors during the token exchange
        logger.error(f"Error exchanging Google code for token: {e}", exc_info=True)
        if e.response is not None:
             logger.error(f"Google Token API Response Status: {e.response.status_code}")
             logger.error(f"Google Token API Response Body: {e.response.text}")
        return jsonify({"error": "Failed to exchange authorization code for token"}), 500
    except Exception as e:
         logger.error(f"An unexpected error occurred during Google callback: {e}", exc_info=True)
         return jsonify({"error": "An unexpected error occurred"}), 500

# --- LinkedIn OAuth Routes ---

@app.route('/api/auth/linkedin/login')
def linkedin_login():
    if not LINKEDIN_CLIENT_ID or not LINKEDIN_REDIRECT_URI:
        logger.error("LinkedIn OAuth Client ID or Redirect URI not configured.")
        return jsonify({"error": "Server configuration error"}), 500

    # Construct the LinkedIn authorization URL
    linkedin_auth_url = (
        "https://www.linkedin.com/oauth/v2/authorization?"
        "response_type=code&"
        f"client_id={LINKEDIN_CLIENT_ID}&"
        f"redirect_uri={LINKEDIN_REDIRECT_URI}&"
        "scope=profile%20email%20openid" # Request basic profile, email, openid scopes
    )
    # TODO: Add state parameter for CSRF protection
    # state = secrets.token_urlsafe(16)
    # session['linkedin_oauth_state'] = state
    # linkedin_auth_url += f"&state={state}"

    logger.info(f"Redirecting user to LinkedIn for authentication: {linkedin_auth_url[:100]}...")
    return redirect(linkedin_auth_url)

@app.route('/api/auth/linkedin/callback')
def linkedin_callback():
    # TODO: Implement CSRF protection check using state parameter
    # received_state = request.args.get('state')
    # expected_state = session.pop('linkedin_oauth_state', None)
    # if not received_state or received_state != expected_state:
    #     logger.warning("Invalid LinkedIn OAuth state parameter received.")
    #     return jsonify({"error": "Invalid state parameter"}), 400

    code = request.args.get('code')
    if not code:
        logger.warning("Authorization code not found in LinkedIn callback.")
        return jsonify({"error": "Authorization code not found"}), 400
    if not LINKEDIN_CLIENT_ID or not LINKEDIN_CLIENT_SECRET or not LINKEDIN_REDIRECT_URI:
        logger.error("LinkedIn OAuth credentials not fully configured for callback.")
        return jsonify({"error": "Server configuration error"}), 500

    try:
        # Exchange authorization code for tokens
        logger.info("Exchanging LinkedIn authorization code for tokens.")
        token_url = "https://www.linkedin.com/oauth/v2/accessToken"
        token_data = {
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': LINKEDIN_REDIRECT_URI,
            'client_id': LINKEDIN_CLIENT_ID,
            'client_secret': LINKEDIN_CLIENT_SECRET
        }
        # LinkedIn expects form-encoded data
        token_response = requests.post(token_url, data=token_data, headers={'Content-Type': 'application/x-www-form-urlencoded'})
        token_response.raise_for_status() # Raise HTTPError for bad responses
        token_json = token_response.json()
        logger.info("Successfully exchanged LinkedIn code for tokens.")

        access_token = token_json.get('access_token')
        if not access_token:
            logger.error("Access token not found in LinkedIn token response.")
            return jsonify({"error": "Access token not found in response"}), 400

        # Get user info using the access token (OpenID Connect endpoint)
        logger.info("Fetching user info from LinkedIn OpenID endpoint.")
        userinfo_url = "https://api.linkedin.com/v2/userinfo"
        userinfo_response = requests.get(userinfo_url, headers={'Authorization': f'Bearer {access_token}'})
        userinfo_response.raise_for_status()
        userinfo = userinfo_response.json()
        logger.info("Successfully fetched LinkedIn user info.")

        linkedin_user_id = userinfo.get('sub') # Standard OpenID field for user ID
        user_email = userinfo.get('email')
        user_name = userinfo.get('name')
        # user_picture = userinfo.get('picture')

        if not linkedin_user_id:
             logger.error("Could not retrieve LinkedIn User ID (sub) from userinfo.")
             return jsonify({"error": "Failed to get user identifier from LinkedIn"}), 500

        logger.info(f"LinkedIn User Info: ID={linkedin_user_id}, Email={user_email}, Name={user_name}")

        # --- Placeholder for User Handling (similar to Google) ---
        # TODO: Implement user lookup/creation logic here
        # Example:
        # user = find_or_create_user(linkedin_id=linkedin_user_id, email=user_email, name=user_name)
        # if not user:
        #    logger.error("Failed to find or create user after LinkedIn authentication.")
        #    return jsonify({"error": "User processing failed"}), 500
        # --- End Placeholder ---

        # Log the user into your application's session
        session.permanent = True
        session['authenticated'] = True
        session['auth_provider'] = 'linkedin' # Store provider
        session['user_email'] = user_email
        session['user_name'] = user_name
        logger.info(f"User {user_email} authenticated via LinkedIn and session created.")

        # Redirect to the frontend success page
        logger.info(f"Attempting to redirect authenticated user to URL from variable: {FRONTEND_LOGIN_SUCCESS_URL}")
        return redirect(FRONTEND_LOGIN_SUCCESS_URL)

    except requests.exceptions.RequestException as e:
        logger.error(f"Error during LinkedIn OAuth flow: {e}", exc_info=True)
        if e.response is not None:
            logger.error(f"LinkedIn API Response Status: {e.response.status_code}")
            logger.error(f"LinkedIn API Response Body: {e.response.text}")
        return jsonify({"error": "Failed to communicate with LinkedIn"}), 500
    except Exception as e:
         logger.error(f"An unexpected error occurred during LinkedIn callback: {e}", exc_info=True)
         return jsonify({"error": "An unexpected error occurred"}), 500

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