import os
import uuid
from livekit import api
from flask import Flask, jsonify
from dotenv import load_dotenv
from flask_cors import CORS
from livekit.api import LiveKitAPI, ListRoomsRequest
from asgiref.wsgi import WsgiToAsgi

load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

def generate_room_name():
    # Create a random room name using UUID
    return "room-" + str(uuid.uuid4())[:8]

@app.route("/health")
def health_check():
    """Simple health check endpoint for monitoring"""
    return jsonify({
        "status": "ok",
        "service": "livekit-bot",
        "version": "1.0.0"
    }), 200


@app.route("/getToken")
async def get_token():
    # Use a default identity and generate a new random room name each time
    name = "my name"
    room = await generate_room_name()
    
    token = api.AccessToken(os.getenv("LIVEKIT_API_KEY"), os.getenv("LIVEKIT_API_SECRET")) \
        .with_identity(name) \
        .with_name(name) \
        .with_grants(api.VideoGrants(
            room_join=True,
            room=room
        ))
    
    return token.to_jwt()

# Wrap the Flask app with the ASGI adapter
asgi_app = WsgiToAsgi(app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(asgi_app, host="0.0.0.0", port=5001, debug=True)
