from livekit.agents import function_tool
from typing import Annotated
from ..services.pinecone_service import PineconeService
from ..utils.logging_config import setup_logger
from ..data.conversation_manager import ConversationManager

# Use centralized logger
logger = setup_logger("knowledge-tools")

class KnowledgeTools:
    """Knowledge base search tools for the agent"""
    
    def __init__(self, room_name: str, conversation_manager: ConversationManager):
        """
        Initialize knowledge base tools
        
        Args:
            room_name (str): The room identifier
            conversation_manager: The conversation manager instance for logging
        """
        self.room_name = room_name
        self.conversation_manager = conversation_manager
        self.pinecone_service = PineconeService()
    
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
    async def search_knowledge_base(
        self,
        query: Annotated[str, "The search query string for the internal knowledge base"]
    ) -> str:
        """
        Performs a similarity search across all relevant namespaces in the Pinecone vector database 
        and returns relevant text snippets.
        """
        try:
            logger.info(f"Searching knowledge base with query: {query}")
            # Call the Pinecone service
            results = await self.pinecone_service.search(query)
            logger.info(f"Knowledge base search returned {len(results)} characters")
            self._log_tool_result(results)
            return results
        except Exception as e:
            error_msg = "I encountered an error trying to search the knowledge base."
            logger.error(f"Knowledge base search failed: {str(e)}")
            self._log_tool_result(error_msg)
            return error_msg 