from livekit.agents import function_tool, get_job_context,ToolError
from typing import Annotated
from ..data.supabase_client import SupabaseEmailClient
from ..utils.logging_config import setup_logger
import json

# Use centralized logger
logger = setup_logger("email-tools")

class EmailTools:
    """Email-related tools for the agent"""
    
    def __init__(self, room_name: str, conversation_manager):
        """
        Initialize email tools
        
        Args:
            room_name (str): The room identifier
            conversation_manager: The conversation manager instance for logging
        """
        self.room_name = room_name
        self.conversation_manager = conversation_manager
        self.supabase = SupabaseEmailClient()
        self._session_emails = {}  # Cache for session emails
        logger.info(f"EmailTools initialized for room: {room_name}")
        
    def _log_tool_result(self, result_content: str):
        """Log tool result to conversation manager"""
        if self.conversation_manager:
            try:
                self.conversation_manager.add_message({
                    "role": "tool_result",
                    "content": str(result_content)
                })
                logger.info(f"Logged tool result: {str(result_content)[:100]}...")
            except Exception as e:
                logger.error(f"Error logging tool result: {e}")
        else:
            logger.warning("ConversationManager not available for logging tool result")
    
    @function_tool()
    async def get_user_email(self) -> str:
        """Returns stored email or empty string"""
        try:
            # First check local cache
            roomName = self.room_name
            print(f"Checking email for room: {roomName}")
            logger.info(f"Checking email for room: {roomName}")
            if roomName in self._session_emails:
                email = self._session_emails[roomName]
                self._log_tool_result(f"get_user_email result: {email}")
                return email
            
            # Query Supabase
            email = await self.supabase.get_email_for_session(roomName)
            if email:
                self._session_emails[roomName] = email
                self._log_tool_result(f"get_user_email result: {email}")
                return email
                
            result = "email not found"
            self._log_tool_result(f"get_user_email result: {result}")
            return result
        except Exception as e:
            logger.error(f"Email lookup failed: {str(e)}")
            self._log_tool_result(f"get_user_email error: {str(e)}")
            return ""
            
    # @function_tool()
    # async def request_email(self) -> str:
    #     """Signal frontend to show email form and provide user instructions"""
    #     try:
    #         await self.set_agent_state("email_requested")
    #         result = "Please provide your email address in the form that just appeared below."
    #         self._log_tool_result(result)
    #         return result
    #     except Exception as e:
    #         error_msg = "There was an issue requesting your email. Please let me know your email address directly."
    #         logger.error(f"Failed to request email: {str(e)}")
    #         self._log_tool_result(error_msg)
    #         return error_msg
    # raise ToolError("Could not complete email request")

    @function_tool()
    async def request_email(self) -> str:
        room = get_job_context().room  # get the active Room object
        payload = json.dumps({
            "action": "email_request",
            "prompt": "Please enter your email to stay connected"
        }).encode("utf-8")
        
    # Broadcast to all participants with topic "email_request"
        await room.local_participant.publish_data(
            payload,
            reliable=True,
            topic="email_request",
        )  # :contentReference[oaicite:4]{index=4}
        return "Email request sent."


    @function_tool()
    async def set_agent_state(self, state: str) -> str:
        """
        Update the agent state marker that the frontend listens for
        
        Args:
            state (str): The new state to set
            
        Returns:
            str: Confirmation message
        """
        try:
            # This is used by frontend to update UI state
            self.agent_state = state
            logger.info(f"Agent state set to: {state[:50]}..." if len(state) > 50 else f"Agent state set to: {state}")
            result = f"Agent state updated."
            self._log_tool_result(result)
            return result
        except Exception as e:
            logger.error(f"Error setting agent state: {str(e)}")
            error_msg = f"Internal error setting agent state: {str(e)}"
            self._log_tool_result(error_msg)
            return f"I encountered an internal issue updating my state." 