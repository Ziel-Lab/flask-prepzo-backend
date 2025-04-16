# supabase_client.py
import os
from supabase import create_client, Client
from typing import Optional
import logging

logger = logging.getLogger("user-data")
logger.setLevel(logging.DEBUG)  

class SupabaseEmailClient:
    def __init__(self):
        self.client: Client = create_client(
            os.getenv("SUPABASE_URL"),
            os.getenv("SUPABASE_KEY")
        )
    
    async def get_email_for_session(self, session_id: str) -> Optional[str]:
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
                logger.info(f"Email found for session ID {session_id}: {response.data[0]['email']}")
                return response.data[0]['email']
            return None
        except Exception as e:
            logger.error(f"Error fetching email for session ID {session_id}: {str(e)}")
            return None