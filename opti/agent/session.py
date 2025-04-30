"""
Agent session implementation for Prepzo
"""
import asyncio
import traceback
import logging
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    RoomInputOptions,
    ConversationItemAddedEvent, 
    AgentStateChangedEvent,
)
from livekit.plugins import deepgram, silero, google, openai
from .agent import PrepzoAgent
from ..data.conversation_manager import ConversationManager
from ..config import settings
from ..utils.logging_config import setup_logger
from ..prompts.agent_prompts import WELCOME_MESSAGE

# Use centralized logger
logger = setup_logger("agent-session")

async def initialize_session(ctx: JobContext):
    """
    Initialize and run the agent session
    
    Args:
        ctx (JobContext): The job context from LiveKit
    """
    try:
        logger.info("Initializing agent session components")
        
        # Initialize voice and LLM plugins
        vad_plugin = silero.VAD.load()
        logger.info("VAD model initialized")
        
        tts_plugin = openai.TTS(
            model=settings.DEFAULT_TTS_MODEL,
            voice=settings.DEFAULT_TTS_VOICE,
        )
        logger.info("TTS client initialized")
        
        stt_plugin = deepgram.STT()
        logger.info("STT client initialized")
        
        llm_plugin = google.LLM(
            model=settings.DEFAULT_LLM_MODEL,
            temperature=settings.DEFAULT_LLM_TEMPERATURE
        )
        logger.info("LLM client initialized")
        
        # Connect to the room
        logger.info(f"Agent JobContext received for room {ctx.room.name}")
        await ctx.connect()
        logger.info(f"Connected to room {ctx.room.name}")

        # Initialize conversation manager
        conversation_manager = ConversationManager(ctx.room.name)
        await conversation_manager.initialize_session(ctx.room.name)
        logger.info(f"ConversationManager initialized for room: {ctx.room.name}")

        # Initialize the agent
        agent = PrepzoAgent(room_name=ctx.room.name, conversation_manager=conversation_manager)

        # Create the agent session
        session = AgentSession(
            vad=vad_plugin,
            stt=stt_plugin,
            llm=llm_plugin,
            tts=tts_plugin,
        )
        logger.info("AgentSession created")
        
        # Register event handlers for session
        _register_event_handlers(session, conversation_manager)

        # Start the session
        logger.info(f"Starting AgentSession in room {ctx.room.name}")
        input_options = RoomInputOptions()
        await session.start(room=ctx.room, agent=agent, room_input_options=input_options)
        logger.info(f"AgentSession started for room {ctx.room.name}")

        # Send welcome message
        logger.info("Generating initial welcome message")
        await session.say(text=WELCOME_MESSAGE)

    except Exception as e:
        logger.error(f"Error in agent session: {str(e)}")
        logger.error(traceback.format_exc())
        raise

def _register_event_handlers(session: AgentSession, conversation_manager: ConversationManager):
    """
    Register event handlers for the agent session
    
    Args:
        session (AgentSession): The agent session
        conversation_manager (ConversationManager): The conversation manager
    """
    @session.on("conversation_item_added")
    def on_conversation_item_added(event: ConversationItemAddedEvent):
        if not hasattr(event, 'item'):
            logger.warning("'conversation_item_added' event missing 'item' attribute")
            return
            
        item = event.item
        role_str = ""
        item_role = getattr(item, 'role', None)
        
        if item_role == "user":
            role_str = "user"
        elif item_role == "assistant":
            if hasattr(item, 'tool_calls') and item.tool_calls: 
                return  # Skip tool calls as they're logged separately
            role_str = "assistant"
        else:
            return  # Ignore other roles

        content = getattr(item, 'text_content', None)
        if role_str and content:
            logger.info(f"Conversation item added ({role_str}): '{content[:50]}...'")
            try:
                conversation_manager.add_message({"role": role_str, "content": content})
                logger.info(f"Logged {role_str} message to ConversationManager")
            except Exception as e:
                logger.error(f"Error logging {role_str} message: {str(e)}")
                logger.error(traceback.format_exc())
        elif role_str:
            logger.warning(f"Received event for role '{role_str}' with empty content")

    @session.on("agent_state_changed")
    def on_agent_state_changed(event: AgentStateChangedEvent):
        old_state = getattr(event, 'old_state', 'Unknown')
        new_state = getattr(event, 'new_state', 'Unknown')
        logger.info(f"Agent state changed from {old_state} to {new_state}") 