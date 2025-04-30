"""
Entry point for running the agent directly with 'python -m opti.agent'
"""
import sys
from dotenv import load_dotenv
from livekit.agents import cli, WorkerOptions
from .session import initialize_session
from ..utils.logging_config import setup_logger

# Load environment variables
load_dotenv()

# Configure logging
logger = setup_logger("agent-main")

def main():
    """Run the agent process"""
    logger.info("Starting Prepzo agent process")
    
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=initialize_session,
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