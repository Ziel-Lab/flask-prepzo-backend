from __future__ import annotations
import logging
from supabase import create_client, Client
from datetime import datetime
import json
import os
from dotenv import load_dotenv
import asyncio
import traceback

# Load environment variables
load_dotenv(dotenv_path=".env.local")

# Configure logging
logger = logging.getLogger("conversation-manager")
logger.setLevel(logging.DEBUG)



# Also log to console
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
logger.addHandler(console_handler)

logger.info("Initializing Supabase client")

# Initialize Supabase client
try:
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")
    
    if not supabase_url or not supabase_key:
        logger.error(f"Supabase credentials missing! URL: {supabase_url}, Key: {'*****' if supabase_key else None}")
    
    supabase: Client = create_client(supabase_url, supabase_key)
    logger.info(f"Supabase client initialized with URL: {supabase_url}")
except Exception as e:
    logger.error(f"Failed to initialize Supabase client: {e}")
    logger.error(traceback.format_exc())
    raise

class ConversationManager:
    def __init__(self, room_id: str):
        self.session_id = room_id  # Use room_id as session_id
        self.participant_id = None
        self.message_count = 0
        self.messages = []  # Array to store all messages
        self.emails = set()  # Set to track unique emails
        logger.info(f"ConversationManager initialized with session_id: {self.session_id}")

    async def initialize_session(self, participant_id: str):
        """Initialize a new conversation session."""
        self.participant_id = participant_id
        logger.info(f"Initializing session for participant: {participant_id}")
        
        session_data = {
            "session_id": self.session_id,
            "participant_id": participant_id,
            "conversation": [],  # Start with empty array
            "raw_conversation": "[]",
            "message_count": 0,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        try:
            await self.store_session(session_data)
            logger.info(f"Session {self.session_id} initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize session: {e}")
            logger.error(traceback.format_exc())

    async def store_session(self, session_data: dict):
        """Store or update the session data in Supabase."""
        try:
            logger.info(f"Storing session data for {session_data['session_id']}")
            logger.debug(f"Session data: {json.dumps(session_data)}")
            
            # Using upsert to handle both insert and update
            result = supabase.table("conversation_histories").upsert(session_data).execute()
            
            # Log the response data
            response_data = result.model_dump() if hasattr(result, 'model_dump') else str(result)
            logger.info(f"Session data stored successfully: {response_data}")
            return result
        except Exception as e:
            logger.error(f"Error storing session: {str(e)}")
            logger.error(traceback.format_exc())
            raise

    async def update_conversation_history(self):
        """Update the conversation history with the current state."""
        try:
            logger.info(f"Updating conversation history with {len(self.messages)} messages")
            
            history_data = {
                "session_id": self.session_id,
                "participant_id": self.participant_id,
                "conversation": self.messages,  # Store directly as JSONB
                "raw_conversation": json.dumps(self.messages),
                "message_count": self.message_count,
                "timestamp": datetime.utcnow().isoformat()
            }
            
            # Log the data being sent
            logger.debug(f"Conversation data being updated: {json.dumps(history_data)}")
            
            # Check for emails in the conversation
            for message in self.messages:
                if message["role"] == "user" and "@" in message["content"]:
                    words = message["content"].split()
                    for word in words:
                        if "@" in word:
                            email = word.strip(".,!?")
                            history_data["user_email"] = email
                            history_data["email_sent"] = False
                            logger.info(f"Email detected in conversation: {email}")
                            break
            
            # Update both tables atomically
            async def update_tables():
                # Update conversation_histories
                result1 = supabase.table("conversation_histories").upsert(history_data).execute()
                logger.info(f"Conversation history updated: {str(result1)}")
                
                # Update conversation_histories with the same data
                result2 = supabase.table("conversation_histories").upsert(history_data).execute()
                logger.info(f"Session data updated: {str(result2)}")
                
                return result1, result2
            
            results = await asyncio.create_task(update_tables())
            return results
        except Exception as e:
            logger.error(f"Error updating conversation history: {str(e)}")
            logger.error(traceback.format_exc())
            raise

    async def store_user_email(self, email: str):
        """Store user email if not already stored."""
        if email not in self.emails:
            try:
                logger.info(f"Storing user email: {email}")
                email_data = {
                    "session_id": self.session_id,
                    "participant_id": self.participant_id,
                    "email": email,
                }
                result = supabase.table("user_emails").upsert(email_data).execute()
                self.emails.add(email)
                logger.info(f"User email stored successfully: {str(result)}")
                return result
            except Exception as e:
                logger.error(f"Error storing user email: {str(e)}")
                logger.error(traceback.format_exc())
                raise

    def add_message(self, message: dict):
        """Add a new message to the conversation array."""
        try:
            self.messages.append(message)
            self.message_count += 1
            logger.info(f"Added message #{self.message_count} from {message['role']}")
            logger.debug(f"Message content: {message['content'][:50]}...")
            
            # Check for email in the message content
            if message["role"] == "user" and isinstance(message.get("content"), str) and "@" in message["content"]:
                words = message["content"].split()
                for word in words:
                    if "@" in word:
                        email = word.strip(".,!?")
                        logger.info(f"Email detected in message: {email}")
                        asyncio.create_task(self.store_user_email(email))
            
            # Update conversation history immediately
            update_task = asyncio.create_task(self.update_conversation_history())
            logger.info(f"Conversation update task created for message #{self.message_count}")
            return update_task
        except Exception as e:
            logger.error(f"Error adding message: {str(e)}")
            logger.error(traceback.format_exc())
            raise

    def create_message_data(self, msg, role: str, event_type: str = None):
        """Create a standardized message data structure according to requirements."""
        try:
            timestamp = datetime.utcnow().isoformat()
            
            if role == "user":
                message_data = {
                    "role": role,
                    "content": msg.content,
                    "metadata": {
                        "type": "transcription",
                        "is_final": True
                    },
                    "timestamp": timestamp
                }
            else:  # assistant
                message_data = {
                    "role": role,
                    "content": msg.content,
                    "metadata": {
                        "type": "response",
                        "event": event_type
                    },
                    "timestamp": timestamp
                }
            
            logger.info(f"Created {role} message data with event: {event_type}")
            logger.debug(f"Message data: {json.dumps(message_data)}")
            return message_data
        except Exception as e:
            logger.error(f"Error creating message data: {str(e)}")
            logger.error(traceback.format_exc())
            raise

    def get_messages(self):
        """Retrieve all messages stored in the conversation."""
        return self.messages

    # If you need an async version
    async def get_messages_async(self):
        """Asynchronously retrieve all messages stored in the conversation."""
        return self.messages 