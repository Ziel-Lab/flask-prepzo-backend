# supabase_client.py
import os
from supabase import create_client, Client
from typing import Optional
import logging

class SupabaseEmailClient:
    def __init__(self):
        self.client: Client = create_client(
            os.getenv("SUPABASE_URL"),
            os.getenv("SUPABASE_KEY")
        )
    
    async def get_email_for_session(self, session_id: str) -> Optional[str]:
        try:
            response = self.client.table('user_emails') \
                .select('email') \
                .eq('session_id', session_id) \
                .order('created_at', desc=True) \
                .limit(1) \
                .execute()
            
            if response.data:
                return response.data[0]['email']
            return None
        except Exception as e:
            logging.error(f"Supabase query failed: {str(e)}")
            return None