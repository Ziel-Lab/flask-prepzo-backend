from livekit.agents import function_tool
from typing import Annotated
from ..services.perplexity import PerplexityService
from ..utils.logging_config import setup_logger
from ..data.conversation_manager import ConversationManager

# Use centralized logger
logger = setup_logger("web-search-tools")

class WebSearchTools:
    """Web search tools for the agent"""
    
    def __init__(self, room_name: str, conversation_manager: ConversationManager):
        """
        Initialize web search tools
        
        Args:
            room_name (str): The room identifier
            conversation_manager: The conversation manager instance for logging
        """
        self.room_name = room_name
        self.conversation_manager = conversation_manager
        self.perplexity_service = PerplexityService()
    
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
    async def web_search(
        self,
        query: Annotated[str, "The structured query string formulated according to system instructions."]
    ) -> str:
        """
        Uses the Perplexity API to get answers for general web queries or job searches.
        Relies on the agent formulating a detailed, structured query.
        """
        try:
            logger.info("Performing Perplexity web search with structured query")
            # Call the Perplexity service
            result = await self.perplexity_service.web_search(query)
            self._log_tool_result(result)
            return result
        except Exception as e:
            error_msg = f"Unable to access current information due to an internal error: {str(e)}"
            logger.error(f"Web search function error: {str(e)}")
            self._log_tool_result(error_msg)
            return error_msg 