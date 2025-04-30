"""
Main agent implementation for Prepzo
"""
from typing import AsyncIterable
import logging
import traceback
from livekit.agents import (
    Agent,
    llm,
    ChatContext,
    ModelSettings,
    FunctionTool,
)
from ..tools.email_tools import EmailTools
from ..tools.web_search import WebSearchTools
from ..tools.knowledge_tools import KnowledgeTools
from ..tools.resume_tools import ResumeTools
from ..prompts.agent_prompts import AGENT_INSTRUCTIONS
from ..utils.logging_config import setup_logger
from ..data.conversation_manager import ConversationManager

# Use centralized logger
logger = setup_logger("agent")

class PrepzoAgent(Agent):
    """
    Custom agent implementation for Prepzo coaching assistant
    
    Provides career coaching and professional growth advice with
    access to real-time information, resume analysis, and knowledge base.
    """
    
    def __init__(self, room_name: str, conversation_manager: ConversationManager):
        """
        Initialize the PrepzoAgent
        
        Args:
            room_name (str): The room identifier
            conversation_manager (ConversationManager): The conversation manager instance
        """
        self.conversation_manager = conversation_manager
        
        # Initialize tool modules
        self.email_tools = EmailTools(room_name=room_name, conversation_manager=conversation_manager)
        self.web_search_tools = WebSearchTools(room_name=room_name, conversation_manager=conversation_manager)
        self.knowledge_tools = KnowledgeTools(room_name=room_name, conversation_manager=conversation_manager)
        self.resume_tools = ResumeTools(room_name=room_name, conversation_manager=conversation_manager)
        
        # Collect all tools from modules
        tools = [
            self.email_tools.get_user_email,
            self.email_tools.request_email,
            self.email_tools.set_agent_state,
            self.web_search_tools.web_search,
            self.knowledge_tools.search_knowledge_base,
            self.resume_tools.request_resume,
            self.resume_tools.get_resume_information,
        ]
        
        # Initialize the base Agent with instructions and tools
        super().__init__(instructions=AGENT_INSTRUCTIONS, tools=tools)
        logger.info(f"PrepzoAgent initialized for room: {room_name} with {len(tools)} tools.")

    async def llm_node(
        self,
        chat_ctx: llm.ChatContext,
        tools: list[llm.FunctionTool],
        model_settings: ModelSettings,
    ) -> AsyncIterable[llm.ChatChunk]:
        """
        Process LLM calls and log tool call requests
        
        Args:
            chat_ctx (llm.ChatContext): The chat context
            tools (list[llm.FunctionTool]): Available tools
            model_settings (ModelSettings): Model configuration
            
        Returns:
            AsyncIterable[llm.ChatChunk]: Stream of chat chunks
        """
        # Process the LLM stream and log tool call requests
        llm_stream = Agent.default.llm_node(self, chat_ctx, tools, model_settings)
        
        async for chunk in llm_stream:
            # Log tool call requests
            if hasattr(chunk, 'delta') and hasattr(chunk.delta, 'tool_calls') and chunk.delta.tool_calls:
                tool_calls = chunk.delta.tool_calls
                tool_calls_str = str(tool_calls)
                logger.info(f"LLM requested tool call(s): {tool_calls_str}")
                
                try:
                    self.conversation_manager.add_message({
                        "role": "tool_call",
                        "content": tool_calls_str 
                    })
                    logger.info("Logged tool call request to ConversationManager")
                except Exception as e:
                    logger.error(f"Error logging tool call request: {e}")
                    logger.error(traceback.format_exc())
            
            yield chunk 