from supabase import create_client, Client
from typing import Optional
import logging
import traceback
from ..config import settings
from ..utils.logging_config import setup_logger

# Use centralized logger
logger = setup_logger("supabase-client")

class SupabaseEmailClient:
    """Client for handling user email operations via Supabase"""
    
    def __init__(self):
        """Initialize Supabase client with credentials from settings"""
        try:
            self.client: Client = create_client(
                settings.SUPABASE_URL,
                settings.SUPABASE_KEY
            )
            logger.info("Supabase client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Supabase client: {e}")
            logger.error(traceback.format_exc())
            raise
    
    async def get_email_for_session(self, session_id: str) -> Optional[str]:
        """
        Retrieve the most recent email address associated with a session ID
        
        Args:
            session_id (str): The unique session identifier
            
        Returns:
            Optional[str]: The user's email address if found, None otherwise
        """
        try:
            logger.info(f"Fetching email for session ID: {session_id}")
            # Query the Supabase table for the email associated with the session ID
            response = self.client.table('user_emails') \
                .select('email') \
                .eq('session_id', session_id) \
                .order('timestamp', desc=True) \
                .limit(1) \
                .execute()
            
            if response.data:
                email = response.data[0]['email']
                logger.info(f"Email found for session ID {session_id}: {email}")
                return email
            
            logger.info(f"No email found for session ID: {session_id}")
            return None
        except Exception as e:
            logger.error(f"Error fetching email for session ID {session_id}: {str(e)}")
            logger.error(traceback.format_exc())
            return None
            
    async def store_user_email(self, session_id: str, participant_id: str, email: str):
        """
        Store a user's email address in the database
        
        Args:
            session_id (str): The unique session identifier
            participant_id (str): The participant identifier
            email (str): The user's email address
            
        Returns:
            The result from the Supabase upsert operation
        """
        try:
            logger.info(f"Storing user email: {email} for session: {session_id}")
            email_data = {
                "session_id": session_id,
                "participant_id": participant_id,
                "email": email,
            }
            result = self.client.table("user_emails").upsert(email_data).execute()
            logger.info(f"User email stored successfully")
            return result
        except Exception as e:
            logger.error(f"Error storing user email: {str(e)}")
            logger.error(traceback.format_exc())
            raise 
    
    async def create_email_log(self, log_data):
        """
        Create a new email log entry in the database
        
        Args:
            log_data (dict): The email log data to insert
            
        Returns:
            str: The ID of the newly created log entry
        """
        try:
            response =  self.client.table('email_logs').insert(log_data).execute()
            if response.data and len(response.data) > 0:
                log_id = response.data[0].get('id')
                return log_id
            return None
        except Exception as e:
            logger.error(f"Failed to create email log: {str(e)}")
            return None
            
    async def update_email_log(self, log_id, update_data):
        """
        Update an existing email log entry
        
        Args:
            log_id (str): The ID of the log entry to update
            update_data (dict): The data to update
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if not log_id:
                return False
                
            self.client.table('email_logs').update(update_data).eq('id', log_id).execute()
            return True
        except Exception as e:
            logger.error(f"Failed to update email log {log_id}: {str(e)}")
            return False 