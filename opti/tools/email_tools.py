from livekit.agents import function_tool, get_job_context,ToolError
from typing import Annotated
from ..data.supabase_client import SupabaseEmailClient
from ..utils.logging_config import setup_logger
import json
import smtplib
import re
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

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


    @function_tool(
        name="send_email",
        description="Send an email with the specified subject and message to a recipient.",  
    )
    async def send_email(
        self,
        recipient_email: str,
        subject: str,
        message_body: str,
    ) -> str:
        """
        Send an email with the specified subject and message to a recipient.
        
        Args:
            recipient_email (str): Email address of the recipient
            subject (str): Subject of the email
            message_body (str): Body content of the email
            
        Returns:
            str: Status message indicating success or failure
        """
        try:
            # Validate email format
            if not re.match(r"[^@]+@[^@]+\.[^@]+", recipient_email):
                error_msg = "The email address seems incorrect. Please provide a valid one."
                self._log_tool_result(error_msg)
                return error_msg
                
            # Get SMTP settings from environment variables
            sender_email = os.getenv("SENDER_EMAIL", "your-email@example.com")
            smtp_server = os.getenv("SMTP_SERVER", "smtp.example.com")
            smtp_port = int(os.getenv("SMTP_PORT", "587"))
            smtp_password = os.getenv("SMTP_PASSWORD", "your-smtp-password")
            
            # Create the email
            msg = MIMEMultipart()
            msg["From"] = sender_email
            msg["To"] = recipient_email
            msg["Subject"] = subject
            msg.attach(MIMEText(message_body, "plain"))
            
            # Prepare log data
            log_data = {
                "session_id": self.room_name,
                # "email": sender_email,
                "email": recipient_email,
                "subject": subject,
                "html_content": message_body,
                "status": "pending",
                "timestamp": datetime.now().isoformat(),
                "email_sent": False,
            }
            
            # Log the email attempt
            log_id = await self.supabase.create_email_log(log_data)
            logger.info(f"Attempting to send email to: {recipient_email} with subject: {subject}")
            # Send the email
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()
            server.login(sender_email, smtp_password)
            server.sendmail(sender_email, recipient_email, msg.as_string())
            server.quit()
            
            # Update log with success
            await self.supabase.update_email_log(log_id, {
                "status": "sent",
                "email_sent": True,
                "updated_at": datetime.now().isoformat()
            })
            
            result = f"Email sent successfully to {recipient_email}."
            self._log_tool_result(result)
            return result
            
        except Exception as e:
            error_message = f"Error sending email: {str(e)}"
            logger.error(error_message)
            
            # Update log with error if log_id exists
            if 'log_id' in locals():
                self.supabase.update_email_log(log_id, {
                    "status": "failed",
                    "error": error_message,
                    "updated_at": datetime.now().isoformat()
                })
            
            self._log_tool_result(error_message)
            return "There was an error sending your email. Please try again later." 