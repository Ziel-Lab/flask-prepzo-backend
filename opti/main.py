"""
Main entry point for the Prepzo backend application
"""
import asyncio
import logging
import traceback
from dotenv import load_dotenv
from livekit.agents import cli, WorkerOptions
from .agent.session import initialize_session
from .config import settings
from .utils.logging_config import setup_logger

# Initialize application
load_dotenv()

# Setup logger
logger = setup_logger("main", logging.INFO)

def main():
    """
    Main application entry point
    
    Initializes and runs the LiveKit agent application
    """
    try:
        logger.info("Starting Prepzo backend application")
        
        # Validate critical settings
        if not settings.validate_settings():
            logger.warning("Application started with missing critical configuration")
        
        # Run the agent application
        cli.run_app(
            WorkerOptions(
                entrypoint_fnc=initialize_session,
            ),
        )
    except Exception as e:
        logger.error(f"Application error: {str(e)}")
        logger.error(traceback.format_exc())
        raise

if __name__ == "__main__":
    main() 