"""
Centralized logging configuration for all modules
"""
import logging
import sys

# Define logging formatters
DEFAULT_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

def setup_logger(name, level=logging.INFO, format_str=DEFAULT_FORMAT):
    """
    Creates and configures a logger with the given name and settings
    
    Args:
        name (str): The logger name
        level (int): The logging level (default: INFO)
        format_str (str): The log format string
        
    Returns:
        logging.Logger: The configured logger instance
    """
    logger = logging.getLogger(name)
    
    # If the logger already has handlers, assume it's configured
    if logger.handlers:
        return logger
        
    logger.setLevel(level)
    
    # Add console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    
    # Create formatter
    formatter = logging.Formatter(format_str)
    console_handler.setFormatter(formatter)
    
    # Add handler to logger
    logger.addHandler(console_handler)
    
    return logger

# Pre-configure standard loggers
agent_logger = setup_logger("agent", logging.INFO)
conversation_logger = setup_logger("conversation", logging.INFO)
knowledge_logger = setup_logger("knowledge", logging.INFO)
tools_logger = setup_logger("tools", logging.INFO)
user_data_logger = setup_logger("user-data", logging.INFO) 