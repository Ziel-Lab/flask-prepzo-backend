"""
Entry point for running the agent directly with 'python -m opti.agent'
"""
import sys
# from dotenv import load_dotenv
from livekit.agents import cli, WorkerOptions
from livekit.plugins import deepgram, google as google_plugin, openai
from .session import initialize_session
from ..utils.logging_config import setup_logger
from ..config import settings
# Load environment variables
# load_dotenv()

# Configure logging
logger = setup_logger("agent-main")

# if getattr(settings, "TTS_PROVIDER", "openai") == "google":
#     TTS_SINGLETON = google_plugin.TTS(
#         language=settings.GOOGLE_TTS_LANGUAGE,
#         voice_name=settings.GOOGLE_TTS_VOICE_NAME,
#         gender=settings.GOOGLE_TTS_GENDER
#     )
# else:
#     TTS_SINGLETON = openai.TTS(
#         model=getattr(settings, 'OPENAI_TTS_MODEL', 'tts-1'),
#         voice=getattr(settings, 'OPENAI_TTS_VOICE', 'nova')
#     )

# STT_SINGLETON = deepgram.STT(
#     model="nova-2-conversationalai",
#     keywords=[("LiveKit", 1.5)],
#     language="en-US",
#     endpointing_ms=25,
#     no_delay=True,
#     numerals=True
# )

# LLM_SINGLETON = google_plugin.LLM(
#     model=settings.DEFAULT_LLM_MODEL,
#     temperature=settings.DEFAULT_LLM_TEMPERATURE
# )

def main():
    """Run the agent process"""
    logger.info("Starting Prepzo agent process")
    
    cli.run_app(
        WorkerOptions(
             entrypoint_fnc=initialize_session
        ),
    )

if __name__ == "__main__":
    # Check for command line arguments
    if len(sys.argv) > 1 and sys.argv[1] == "start":
        main()
    else:
        logger.error("Invalid command. Use 'start' to run the agent.")
        print("Usage: python -m opti.agent start")
        sys.exit(1) 