# Prepzo Backend - Modular Structure

This folder contains the modular implementation of the Prepzo coaching assistant. The code has been refactored to follow a more organized and maintainable structure.

## Directory Structure

```
opti/
├── __init__.py              # Package initialization
├── __main__.py              # Entry point to run all processes
├── main.py                  # Main entry point for agent only
├── runner.py                # Process orchestration for server and agent
├── migration.py             # Migration utility from legacy structure
├── knowledgebase.py         # Legacy compatibility module
├── run_backend.py           # Compatibility wrapper for run_backend.py
├── README.md                # This documentation
├── agent/                   # Agent implementation
│   ├── __init__.py
│   ├── __main__.py          # Entry point to run agent directly
│   ├── agent.py             # Agent class implementation
│   └── session.py           # Agent session management
├── config/                  # Configuration management
│   ├── __init__.py
│   └── settings.py          # Centralized settings module
├── data/                    # Data management
│   ├── __init__.py
│   ├── conversation_manager.py  # Conversation persistence
│   └── supabase_client.py   # Database client
├── prompts/                 # Prompt management
│   ├── __init__.py
│   └── agent_prompts.py     # System prompts for agent
├── server/                  # Server implementation
│   ├── __init__.py
│   ├── __main__.py          # Entry point to run server directly
│   └── app.py               # Flask server implementation
├── services/                # External service integrations
│   ├── __init__.py
│   ├── docai.py             # Document AI service
│   ├── perplexity.py        # Perplexity web search API
│   └── pinecone_service.py  # Pinecone vector database service
├── tools/                   # Agent tool implementations
│   ├── __init__.py
│   ├── email_tools.py       # Email-related tools
│   ├── knowledge_tools.py   # Knowledge base search tools
│   ├── resume_tools.py      # Resume processing tools
│   └── web_search.py        # Web search tools
└── utils/                   # Utility modules
    ├── __init__.py
    └── logging_config.py    # Centralized logging configuration
```

## Benefits of Modular Structure

1. **Improved organization**: Code is logically grouped by functionality
2. **Better separation of concerns**: Each module has a clear responsibility
3. **Enhanced maintainability**: Easier to update or replace specific components
4. **Reduced duplicate code**: Common functionality is centralized
5. **Simplified testing**: Modules can be tested independently
6. **Easier onboarding**: New developers can understand the system more quickly

## Different Ways to Run the Application

You have several options to run the application:

1. **Run both server and agent processes** (recommended):
   ```bash
   python run_prepzo.py
   ```
   or
   ```bash
   python -m opti
   ```

2. **Run the server and agent separately**:
   ```bash
   # Terminal 1 - Run server
   python -m opti.server

   # Terminal 2 - Run agent
   python -m opti.agent start
   ```

3. **For backward compatibility**:
   ```bash
   # Using the compatibility wrapper
   python run_backend.py
   ```

## Migration from Legacy Structure

To migrate from the old structure to the new modular structure, run:

```bash
python -m opti.migration --backup
```

This will:
1. Create a backup of your legacy files (with `--backup`)
2. Update import statements in your existing code
3. Create compatibility wrappers for server.py and run_backend.py
4. Create a new `run_prepzo.py` entry point

## Core Components

### Server Implementation

The server is implemented as a Flask application with the following components:
- `app.py`: Defines the Flask application with all routes and ASGI compatibility
- `__main__.py`: Provides a direct entry point for running the server independently

### Process Orchestration

The `runner.py` module handles running both server and agent processes:
- Starts the server using uvicorn
- Starts the agent process
- Sets up signal handlers for graceful termination
- Waits for both processes to complete

### Agent Implementation

The agent implementation is divided into two main components:
- `agent.py`: Defines the `PrepzoAgent` class that extends the LiveKit `Agent`
- `session.py`: Manages the agent session lifecycle and event handling

### Data Management

- `conversation_manager.py`: Handles conversation persistence to Supabase
- `supabase_client.py`: Provides a client for Supabase data operations

### Services

- `docai.py`: Google Document AI service for resume parsing
- `perplexity.py`: Perplexity API service for web search
- `pinecone_service.py`: Pinecone vector database service for knowledge retrieval

### Tools

The tools are organized into functional modules:
- `email_tools.py`: Tools for email-related operations
- `knowledge_tools.py`: Tools for searching the knowledge base
- `resume_tools.py`: Tools for resume uploading and analysis
- `web_search.py`: Tools for web searching

### Configuration

Settings are centralized in the `config/settings.py` module, which loads values from environment variables and provides validation functions.

### Utilities

Shared utilities like logging configuration are in the `utils` directory.

## Backward Compatibility

For backward compatibility with the legacy structure:
- `knowledgebase.py` provides a bridge to the new modules
- `run_backend.py` maintains the same entry point but uses the new runner
- `server.py` is updated to reference the new server implementation

## Getting Started

To use the modular structure in a new project:

1. Copy the `opti` directory to your project
2. Copy `run_prepzo.py` to your project root
3. Set up the required environment variables (see `config/settings.py`)
4. Run the application with `python run_prepzo.py` 