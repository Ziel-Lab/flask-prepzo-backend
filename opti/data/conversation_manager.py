"""
Manages conversation state and persistence to database
"""
import asyncio
import traceback
import json
from datetime import datetime
from supabase import Client, create_client
import logging
from ..config import settings
from ..utils.logging_config import setup_logger

# Use centralized logger
logger = setup_logger("conversation-manager")

class ConversationManager:
    """Manages conversation history and persistence to Supabase"""
    
    def __init__(self, room_id: str):
        """
        Initialize the conversation manager
        
        Args:
            room_id (str): The room ID used as the session identifier
        """
        self.session_id = room_id
        self.participant_id = None
        self.message_count = 0
        self.messages = []
        self.emails = set()  # Set to track unique emails
        
        # Initialize Supabase client
        try:
            self.supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
            logger.info(f"ConversationManager initialized with session_id: {self.session_id}")
        except Exception as e:
            logger.error(f"Failed to initialize Supabase client in ConversationManager: {e}")
            logger.error(traceback.format_exc())
            raise

    async def initialize_session(self, participant_id: str):
        """
        Initialize a new conversation session
        
        Args:
            participant_id (str): The participant identifier
        """
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
        """
        Store or update the session data in Supabase
        
        Args:
            session_data (dict): The session data to store
            
        Returns:
            The result from the Supabase upsert operation
        """
        try:
            logger.info(f"Storing session data for {session_data['session_id']}")
            
            # Using upsert to handle both insert and update
            result = self.supabase.table("conversation_histories").upsert(session_data).execute()
            
            # Log the response data
            response_data = result.model_dump() if hasattr(result, 'model_dump') else str(result)
            logger.info(f"Session data stored successfully")
            return result
        except Exception as e:
            logger.error(f"Error storing session: {str(e)}")
            logger.error(traceback.format_exc())
            raise

    async def update_conversation_history(self):
        """
        Update the conversation history with the current state
        
        Returns:
            Tuple of results from the database operations
        """
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
            
            # Update conversation_histories table
            result = self.supabase.table("conversation_histories").upsert(history_data).execute()
            logger.info(f"Conversation history updated successfully")
            
            return result
        except Exception as e:
            logger.error(f"Error updating conversation history: {str(e)}")
            logger.error(traceback.format_exc())
            raise

    async def store_user_email(self, email: str):
        """
        Store user email if not already stored
        
        Args:
            email (str): The user's email address
            
        Returns:
            The result from the Supabase upsert operation if successful
        """
        if email not in self.emails:
            try:
                logger.info(f"Storing user email: {email}")
                email_data = {
                    "session_id": self.session_id,
                    "participant_id": self.participant_id,
                    "email": email,
                }
                result = self.supabase.table("user_emails").upsert(email_data).execute()
                self.emails.add(email)
                logger.info(f"User email stored successfully")
                return result
            except Exception as e:
                logger.error(f"Error storing user email: {str(e)}")
                logger.error(traceback.format_exc())
                raise

    def add_message(self, message: dict):
        """
        Add a new message to the conversation and update history
        
        Args:
            message (dict): The message to add with 'role' and 'content' keys
            
        Returns:
            The async task updating the conversation history
        """
        try:
            self.messages.append(message)
            self.message_count += 1
            logger.info(f"Added message #{self.message_count} from {message['role']}")
            
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
        """
        Create a standardized message data structure
        
        Args:
            msg: The message object
            role (str): The role of the message sender ('user' or 'assistant')
            event_type (str, optional): The event type
            
        Returns:
            dict: The standardized message data
        """
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
            return message_data
        except Exception as e:
            logger.error(f"Error creating message data: {str(e)}")
            logger.error(traceback.format_exc())
            raise 