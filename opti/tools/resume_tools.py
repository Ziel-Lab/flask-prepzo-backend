from livekit.agents import function_tool,ToolError,get_job_context
from typing import Annotated
from ..services.docai import ResumeAnalysisService
from ..utils.logging_config import setup_logger
import json

# Use centralized logger
logger = setup_logger("resume-tools")

class ResumeTools:
    """Resume-related tools for the agent"""
    
    def __init__(self, room_name: str, conversation_manager):
        """
        Initialize resume tools
        
        Args:
            room_name (str): The room identifier
            conversation_manager: The conversation manager instance for logging
        """
        self.room_name = room_name
        self.conversation_manager = conversation_manager
        self.resume_service = ResumeAnalysisService()
        self.agent_state = None  # Track agent state
        logger.info(f"ResumeTools initialized for room: {room_name}")
    
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
    async def request_resume(self) -> str:
        """Triggers resume collection flow using LiveKit data channels"""
        # Log function entry
        logger.info(f"Entering request_resume for room '{self.room_name}'")
        
        try:
            # Log before getting context
            logger.info(f"Attempting to get job context for room '{self.room_name}'")
            context = get_job_context()
            # Log after getting context
            logger.info(f"Successfully got job context for room '{self.room_name}'")

            # Log before getting room
            logger.info(f"Attempting to get room from context for room '{self.room_name}'")
            room = context.room
            # Log after getting room
            logger.info(f"Successfully got room from context for room '{self.room_name}'")
        
            # Prepare payload
            payload = json.dumps({
                "action": "request_resume",
                "message": "Please upload your resume to continue"
            }).encode("utf-8")
            topic = "resume_request"
            
            # Log before publishing
            logger.info(f"Attempting to publish data on topic '{topic}' for room '{self.room_name}'")

            # Send request to frontend
            try:
                await room.local_participant.publish_data(
                    payload=payload,
                    reliable=True,
                    topic=topic
                )
                # Log after successful publishing
                logger.info(f"Successfully published data on topic '{topic}' for room '{self.room_name}'")
            except Exception as pub_err:
                # Log publishing error
                logger.error(f"Error publishing data on topic '{topic}' for room '{self.room_name}': {pub_err}", exc_info=True)
                raise ToolError(f"Failed to send resume request: {pub_err}")
        
            # Wait for response with timeout (Currently commented out - keep as is)
            try:
                # Log before getting participant (though this part is inactive)
                logger.debug(f"Attempting to get participant iterator for room '{self.room_name}' (wait logic inactive)")
                participant = next(iter(room.remote_participants.values()))
                logger.debug(f"Got participant for room '{self.room_name}' (wait logic inactive)")

            
            except StopIteration:
                logger.warning(f"No remote participants found for room '{self.room_name}' when checking for resume response (wait logic inactive).")
                # This isn't necessarily an error if we aren't waiting, but good to know.
            except TimeoutError:
                # This block shouldn't be reached as wait_for_data is commented out
                logger.warning(f"Timeout waiting for resume response on topic 'resume_response' for room '{self.room_name}'")

            # it implies publish was successful but we didn't wait for a reply.
            logger.info(f"Exiting request_resume successfully for room '{self.room_name}' (publish succeeded, no wait)")
            return "Resume request sent successfully." # Return statement consolidated here

        except Exception as e:
            # Catch other potential errors (like getting context/room)
            logger.error(f"Error in request_resume tool for room '{self.room_name}': {str(e)}", exc_info=True)
            # Log function exit due to error
            logger.info(f"Exiting request_resume due to error for room '{self.room_name}'")
            raise ToolError("Could not complete resume request due to an internal error.")
   
    @function_tool()
    async def get_resume_information(self) -> str:
        """
        Analyzes the user's previously uploaded resume using our
        Gemini-powered ResumeAnalysisService for comprehensive
        visual and content analysis.
        """
        try:
            logger.info(f"Attempting to analyze resume for session: {self.room_name}")

            # Call the Gemini-based analysis service
            analysis: dict = await self.resume_service.analyze_resume(self.room_name)
            self._log_tool_result(analysis)

            # Short-circuit on error
            if "error" in analysis:
                return analysis["error"]
            
            # Handle the narrative format from multimodal analysis
            if "format" in analysis and analysis["format"] == "narrative":
                if "analysis" in analysis:
                    resume_analysis = analysis["analysis"]
                    # Return the formatted analysis
                    return f"📄 **Resume Analysis**\n\n{resume_analysis}"
                else:
                    return "I couldn't find any analysis content in the response."
                
            # Fallback for other formats (though we don't expect this path to be used)
            if "raw_analysis" in analysis:
                return f"📄 **Resume Analysis**\n\n{analysis['raw_analysis']}"
            
            # This is a fallback that shouldn't be reached with the new implementation
            return "I was able to analyze your resume, but couldn't format the results correctly. Please try again."

        except Exception as e:
            error_msg = "An unexpected error occurred while attempting to analyze your resume."
            logger.error(f"Resume analysis error: {e}", exc_info=True)
            self._log_tool_result(error_msg)
            return error_msg