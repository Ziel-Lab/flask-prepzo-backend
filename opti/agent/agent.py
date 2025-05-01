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
        # Removed faulty logging block
            
        # Process the LLM stream and log tool call requests
        llm_stream = Agent.default.llm_node(self, chat_ctx, tools, model_settings)
        
        chunk_index = 0 
        buffer = ""
        suppress_output_this_turn = False # Flag to suppress all output for this LLM turn once trigger is detected
        
        async for chunk in llm_stream:
            # Log every chunk for debugging
            try:
                chunk_str = str(chunk)
                logger.info(f"LLM Chunk [{chunk_index}]: {chunk_str}")
            except Exception as log_err:
                logger.error(f"Error logging raw LLM chunk [{chunk_index}]: {log_err}")

            # Buffer content if delta exists
            if chunk.delta and chunk.delta.content:
                 # Only buffer if not suppressing (to avoid buffering unrelated text after trigger)
                 if not suppress_output_this_turn:
                    buffer += chunk.delta.content
                    # Check if the trigger phrase is now in the buffer
                    if "SYSTEM_TRIGGER_RESUME_REQUEST" in buffer.strip():
                        logger.info("Detected SYSTEM_TRIGGER_RESUME_REQUEST phrase. Suppressing output and triggering tool.")
                        suppress_output_this_turn = True # Suppress all further output for this turn
                        try:
                            # Manually call the tool function (must be async)
                            await self.resume_tools.request_resume()
                            logger.info("Manually called request_resume tool.")
                            self.conversation_manager.add_message({
                                "role": "system_tool_trigger", 
                                "content": "Manually triggered request_resume based on LLM phrase."
                            })
                            
                            # **** ADDED: Manually generate the desired verbal response ****
                            logger.info("Manually generating verbal confirmation for resume request.")
                            await self.session.say(text="Okay, please upload your resume now.")
                            logger.info("Completed manual generation of verbal confirmation.")
                            # **** END ADDED ****
                            
                        except Exception as tool_err:
                            logger.error(f"Error manually calling request_resume or generating speech: {tool_err}")
                        # Buffer is implicitly discarded as we won't yield anything further this turn
            
            # Only yield chunks if suppression is NOT active for this turn
            if not suppress_output_this_turn:
                 yield chunk
            # else: # Optional: Log suppression
                # logger.debug(f"LLM Chunk [{chunk_index}] suppressed.")

            chunk_index += 1

        # Enhanced logging specifically for tool_calls attribute
        if hasattr(chunk, 'delta') and hasattr(chunk.delta, 'tool_calls'):
            try:
                tool_calls_obj = chunk.delta.tool_calls
                # Log type and content even if it might be None or empty
                logger.info(f"LLM Chunk [{chunk_index}] - tool_calls type: {type(tool_calls_obj)}")
                logger.info(f"LLM Chunk [{chunk_index}] - tool_calls content: {str(tool_calls_obj)}")
                
                # Optional: Log to conversation manager if needed
                # self.conversation_manager.add_message({
                #     "role": "tool_call_debug", 
                #     "content": f"Type: {type(tool_calls_obj)}, Content: {str(tool_calls_obj)}"
                # })
            except Exception as tool_log_err:
                 logger.error(f"Error logging tool_calls details for chunk [{chunk_index}]: {tool_log_err}") 