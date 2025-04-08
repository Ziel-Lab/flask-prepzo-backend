#!/bin/sh
# Start the agent script in the background with the 'start' argument
echo "Starting LiveKit Agent..."
python agent.py start &

# Start the Flask/Uvicorn server in the foreground
echo "Starting Flask/Uvicorn server..."
uvicorn server:asgi_app --host 0.0.0.0 --port 5001

# Optional: Add wait or cleanup logic if needed