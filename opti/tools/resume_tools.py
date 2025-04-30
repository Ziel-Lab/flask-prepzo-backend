"""
Resume-related tools for the agent
"""
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
        self.docai_service = ResumeAnalysisService()
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
    
    # @function_tool()
    # async def request_resume(self) -> str:
    #     """Triggers resume collection flow using LiveKit data channels"""
    #     try:
    #         context = get_job_context()
    #         room = context.room
        
    #     # Send request to frontend
    #         await room.local_participant.publish_data(
    #             payload=json.dumps({
    #                 "action": "request_resume",
    #                 "message": "Please upload your resume to continue"
    #             }).encode("utf-8"),
    #             reliable=True,
    #             topic="resume_request"
    #         )
        
    #     # Wait for response with timeout
    #         try:
    #             participant = next(iter(room.remote_participants.values()))
    #             response = await participant.wait_for_data(
    #                 topic="resume_response",
    #                 timeout=120.0  # Longer timeout for file upload
    #             )
    #             resume_data = json.loads(response.value)
    #             return f"Resume received: {resume_data.get('filename')}"
    #         except TimeoutError:
    #             raise ToolError("Resume upload timed out")
    #     except Exception as e:
    #         logger.error(f"Resume request failed: {str(e)}")
    #         raise ToolError("Could not complete resume request")
    
    @function_tool()
    async def request_resume(self) -> str:
        """Triggers resume collection flow using LiveKit data channels"""
        try:
            context = get_job_context()
            room = context.room
        
        # Send request to frontend
            await room.local_participant.publish_data(
                payload=json.dumps({
                    "action": "request_resume",
                    "message": "Please upload your resume to continue"
                }).encode("utf-8"),
                reliable=True,
                topic="resume_request"
            )
        
        # Wait for response with timeout
            try:
                participant = next(iter(room.remote_participants.values()))
                # response = await participant.wait_for_data(
                #     topic="resume_response",
                #     timeout=120.0  # Longer timeout for file upload
                # )
                # resume_data = json.loads(response.value)
                # return f"Resume received: {resume_data.get('filename')}"
            
            except TimeoutError:
                raise ToolError("Resume upload timed out")
            
        except Exception as e:
            logger.error(f"Resume request failed: {str(e)}")
            raise ToolError("Could not complete resume request")


    # @function_tool()
    # async def get_resume_information(self) -> str:
    #     """
    #     Analyzes the user's previously uploaded resume using the Google Cloud Document AI Summarizer
    #     to extract key information. Call this when the user asks to analyze, summarize, or get details
    #     from their resume.
    #     """
    #     try:
    #         logger.info(f"Attempting to analyze resume for session: {self.room_name}")
    #         result = await self.docai_service.summarize_resume(self.room_name)
    #         self._log_tool_result(result)
    #         return result
    #     except Exception as e:
    #         error_msg = "An unexpected error occurred while attempting to analyze your resume."
    #         logger.error(f"Resume analysis error: {str(e)}")
    #         self._log_tool_result(error_msg)
    #         return error_msg
    
    # @function_tool()
    # async def get_resume_information(self) -> str:
    #     """
    #     Analyzes the user's previously uploaded resume using our combined
    #     Document AI + Vision-based ResumeAnalysisService and returns
    #     a summary of the key layout, visual, and ATS-compatibility metrics.
    #     """
    #     try:
    #         logger.info(f"Attempting to analyze resume for session: {self.room_name}")

    #     # Call the new ResumeAnalysisService (returns a dict)
    #         report: dict = await self.docai_service.analyze_resume(self.room_name)
    #         self._log_tool_result(report)

    #     # If there was an error, short-circuit
    #         if "error" in report:
    #             return report["error"]

    #     # Build a readable summary
    #         summary_lines = []
    #         summary_lines.append("📄 **Resume Analysis Report**\n")

    #     # Sections
    #         secs = report.get("sections", [])
    #         summary_lines.append(f"• Detected section breaks: {len(secs)}")
    #         if secs:
    #             locs = [f"(page {s['page']+1}, block {s['block']+1})" for s in secs]
    #             summary_lines.append(f"  → {', '.join(locs)}")

    #     # Formatting
    #         # fmt = report.get("formatting", {})
    #         # summary_lines.append(f"\n• Formatting consistency: {'✅' if fmt.get('consistent') else '⚠️'}")

    #     # Logo analysis
    #         logo = report.get("logo_analysis", {})
    #         total = logo.get("total", 0)
    #         header = logo.get("header", 0)
    #         summary_lines.append(f"\n• Logos detected: {total} (in header: {header})")

    #     # Color score
    #         color_score = report.get("color_score", 0.0)
    #         summary_lines.append(f"\n• Color harmony score: {color_score:.2f}/1.00")

    #     # ATS score
    #         ats = report.get("ats_score", 0)
    #         summary_lines.append(f"\n• ATS Compatibility Score: {ats}/100")

    #         return "\n".join(summary_lines)

    #     except Exception as e:
    #         error_msg = "An unexpected error occurred while attempting to analyze your resume."
    #         logger.error(f"Resume analysis error: {str(e)}", exc_info=True)
    #         self._log_tool_result(error_msg)
    #         return error_msg

    @function_tool()
    async def get_resume_information(self) -> str:
        """
        Analyzes the user's previously uploaded resume using our
        Document AI–only ResumeAnalysisService and returns a summary
        of the structural and ATS-compatibility metrics.
        """
        try:
            logger.info(f"Attempting to analyze resume for session: {self.room_name}")

            # Call the trimmed-down analysis service
            report: dict = await self.docai_service.analyze_resume(self.room_name)
            self._log_tool_result(report)

        # Short-circuit on error
            if "error" in report:
                return report["error"]

        # Build summary
            lines = ["📄 **Resume Analysis Report**\n"]

        # Section breaks
            secs = report.get("sections", [])
            lines.append(f"• Detected section breaks: {len(secs)}")
            if secs:
                locs = [f"(page {s['page']+1}, block {s['block']+1})" for s in secs]
                lines.append(f"  → {', '.join(locs)}")

        # Formatting consistency
            fmt = report.get("formatting", {})
            consistent = fmt.get("consistent", False)
            lines.append(f"\n• Formatting consistency: {'✅ Consistent' if consistent else '⚠️ Inconsistent'}")

        # ATS score
            ats = report.get("ats_score", 0)
            lines.append(f"\n• ATS Compatibility Score: {ats}/100")

            return "\n".join(lines)

        except Exception as e:
            error_msg = "An unexpected error occurred while attempting to analyze your resume."
            logger.error(f"Resume analysis error: {e}", exc_info=True)
            self._log_tool_result(error_msg)
            return error_msg





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