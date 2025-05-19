"""
Centralized configuration settings loaded from environment variables
"""
import os
import logging
import pathlib
from dotenv import load_dotenv
import importlib.metadata
from opti.utils.aws_secrets import load_aws_secrets

# Load environment variables
# load_dotenv()
AWS_SECRET_NAME = 'dev-prepzo'  #dev
# AWS_SECRET_NAME =  'prepzo-agent-dev'  #prod
AWS_REGION =  'us-east-1'
load_aws_secrets(AWS_SECRET_NAME, region_name=AWS_REGION)

# Configure logging
logger = logging.getLogger("settings")
logger.setLevel(logging.INFO)

# Get package version
try:
    from .. import __version__
except ImportError:
    __version__ = "0.0.0"

# Base paths
ROOT_DIR = pathlib.Path(__file__).parent.parent.parent
UPLOAD_FOLDER = ROOT_DIR / 'uploads'

#llm
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
GROQ_API_KEY=os.getenv("GROQ_API_KEY")
GROQ_MODEL=os.getenv("GROQ_MODEL", "mixtral-8x7b-32768")
GROQ_TEMPERATURE=os.getenv("GROQ_TEMPERATURE", 0.8)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL=os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_TEMPERATURE=os.getenv("OPENAI_TEMPERATURE", 0.8)

GEMINI_API_KEY=os.getenv("GEMINI_API_KEY")
GEMINI_MODEL=os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_TEMPERATURE=os.getenv("GEMINI_TEMPERATURE", 0.8)

# API Keys

PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

#Elevenlabs
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")

# LiveKit settings
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET")

# Supabase settings
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# Pinecone settings
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_REGION = os.getenv("PINECONE_REGION")
PINECONE_INDEX_NAME = "coachingbooks"

SENDER_EMAIL=os.getenv("SENDER_EMAIL", "your-email@example.com")
SMTP_SERVER=os.getenv("SMTP_SERVER", "smtp.example.com")
SMTP_PORT=int(os.getenv("SMTP_PORT", "587"))
SMTP_PASSWORD=os.getenv("SMTP_PASSWORD", "your-smtp-password")

TTS_PROVIDER = os.getenv("TTS_PROVIDER", "openai")

# Also ensure your Google TTS specific settings are present and correct:
GOOGLE_TTS_LANGUAGE = "en-US"
GOOGLE_TTS_VOICE_NAME = "en-US-Chirp3-HD-Laomedeia"
GOOGLE_TTS_GENDER = "female"

# Google Document AI settings
GOOGLE_PROJECT_ID = os.getenv("GOOGLE_PROJECT_ID")
DOCAI_LOCATION = os.getenv("DOCAI_LOCATION")
DOCAI_LAYOUT_PROCESSOR_ID = os.getenv("DOCAI_LAYOUT_PROCESSOR_ID")

# AI Model settings
DEFAULT_TTS_MODEL = "gpt-4o-mini-tts"
DEFAULT_TTS_VOICE = "nova"
DEFAULT_LLM_MODEL = "gemini-2.5-flash-preview-04-17"
DEFAULT_LLM_TEMPERATURE = 0.8


GCP_CREDENTIALS_PATH=r"D:\prepzo\prepzo-backend\flask-prepzo-backend\opti\cred.json"
# Server settings
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "a_default_secret_key_for_development")
PAGE_PASSWORDS = os.getenv("PAGE_PASSWORDS", "password123").split(",")
APP_ENV = os.getenv("APP_ENV", "production").lower()

# Function to validate critical settings
def validate_settings():
    missing = []
    
    if not SUPABASE_URL or not SUPABASE_KEY:
        missing.append("Supabase credentials (SUPABASE_URL, SUPABASE_KEY)")
    
    if not PINECONE_API_KEY or not PINECONE_REGION:
        missing.append("Pinecone credentials (PINECONE_API_KEY, PINECONE_REGION)")
    
    if LLM_PROVIDER == "openai" and not OPENAI_API_KEY:
        missing.append("OpenAI API key (OPENAI_API_KEY)")

    elif LLM_PROVIDER == "groq" and not GROQ_API_KEY:
        missing.append("Groq API key (GROQ_API_KEY)")
        
    elif LLM_PROVIDER == "gemini" and not GEMINI_API_KEY:
        missing.append("Gemini API key (GEMINI_API_KEY)")

    if not LIVEKIT_API_KEY or not LIVEKIT_API_SECRET:
        missing.append("LiveKit credentials (LIVEKIT_API_KEY, LIVEKIT_API_SECRET)")
    
    if missing:
        logger.warning(f"Missing critical configuration: {', '.join(missing)}")
        return False
    
    return True 
