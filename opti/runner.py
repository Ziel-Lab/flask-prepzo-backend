"""
Process orchestration module for running both server and agent processes
"""
import subprocess
import sys
import signal
import os
import logging
from .utils.logging_config import setup_logger

# Configure logging
logger = setup_logger("runner")

def run_processes():
    """
    Start and manage both the server and agent processes
    
    This function:
    1. Starts the Flask server using uvicorn
    2. Starts the LiveKit agent process
    3. Sets up signal handlers to gracefully terminate both processes
    4. Waits for both processes to complete
    """
    logger.info("Starting Prepzo server and agent processes")
    
    # Use current Python executable to ensure proper virtual environment
    python_executable = sys.executable
    
    # Start the server process
    logger.info("Starting server process...")
    server_cmd = [
        python_executable, "-m", "uvicorn", "opti.server.app:asgi_app",
        "--host", "0.0.0.0",
        "--port", "5001"
    ]
    server_proc = subprocess.Popen(server_cmd)
    logger.info(f"Server process started with PID: {server_proc.pid}")
    
    # Start the agent process
    logger.info("Starting agent process...")
    agent_cmd = [python_executable, "-m", "opti.agent", "start"]
    agent_proc = subprocess.Popen(agent_cmd)
    logger.info(f"Agent process started with PID: {agent_proc.pid}")
    
    def terminate_processes(signum=None, frame=None):
        """Terminate both processes gracefully"""
        logger.info("Terminating processes...")
        
        try:
            server_proc.terminate()
            logger.info("Server process termination signal sent")
        except Exception as e:
            logger.error(f"Error terminating server process: {e}")
        
        try:
            agent_proc.terminate()
            logger.info("Agent process termination signal sent")
        except Exception as e:
            logger.error(f"Error terminating agent process: {e}")
        
        logger.info("All termination signals sent. Exiting...")
        sys.exit(0)
    
    # Set up signal handlers for graceful termination
    signal.signal(signal.SIGINT, terminate_processes)
    signal.signal(signal.SIGTERM, terminate_processes)
    
    # Wait for both processes to complete
    try:
        logger.info("Monitoring processes...")
        exit_codes = []
        
        server_code = server_proc.wait()
        logger.info(f"Server process exited with code: {server_code}")
        exit_codes.append(server_code)
        
        agent_code = agent_proc.wait()
        logger.info(f"Agent process exited with code: {agent_code}")
        exit_codes.append(agent_code)
        
        # If we get here, both processes have exited
        logger.info(f"All processes exited with codes: {exit_codes}")
        
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
        terminate_processes()

def main():
    """Main entry point for the runner module"""
    run_processes()

if __name__ == "__main__":
    main() 