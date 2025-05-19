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
from livekit.plugins import deepgram, silero, google, openai, elevenlabs, noise_cancellation
from .agent import PrepzoAgent
from .dynamic_llm import DynamicLLM
from ..data.conversation_manager import ConversationManager
from ..config import settings
from ..utils.logging_config import setup_logger
# Import the new client and default instructions for fallback
from ..data.supabase_client import SupabaseAgentConfigClient
from ..prompts.agent_prompts import AGENT_INSTRUCTIONS as DEFAULT_AGENT_INSTRUCTIONS

# Use centralized logger
logger = setup_logger("agent-session")

async def initialize_session(ctx: JobContext):
    """
    Initialize and run the agent session
    
    Args:
        ctx (JobContext): The job context from LiveKit
    """
    try:
        logger.info(f"Agent JobContext received for room {ctx.room.name}")

        # ---- Add Shutdown Hook ----
        async def _shutdown_hook():
            logger.info(f"Agent for room {ctx.room.name} is shutting down.")
            # Add any other cleanup logic here if needed (e.g., flushing conversation manager)
            if 'conversation_manager' in locals() and conversation_manager:
                await conversation_manager.flush_and_close() # Example cleanup
                logger.info(f"ConversationManager for room {ctx.room.name} flushed and closed.")

        ctx.add_shutdown_callback(_shutdown_hook)
        logger.info(f"Shutdown hook registered for room {ctx.room.name}")
        # ---- End Shutdown Hook ----

        logger.info("Initializing agent session components")
        
        # Initialize voice and LLM plugins
        # Run potentially blocking VAD loading in a separate thread
        vad_plugin = await asyncio.to_thread(silero.VAD.load)
        logger.info("VAD model initialized")
        
        # Initialize TTS plugin based on settings
        if hasattr(settings, 'TTS_PROVIDER') and settings.TTS_PROVIDER == "google":
            try:
                # Ensure Google TTS settings are available
                if not all(hasattr(settings, attr) for attr in ['GOOGLE_TTS_LANGUAGE', 'GOOGLE_TTS_VOICE_NAME', 'GOOGLE_TTS_GENDER']):
                    logger.error("Google TTS provider selected, but required settings (GOOGLE_TTS_LANGUAGE, GOOGLE_TTS_VOICE_NAME, GOOGLE_TTS_GENDER) are missing. Falling back to OpenAI TTS.")
                    raise AttributeError("Missing Google TTS settings")

                tts_plugin = google.TTS(
                    language=settings.GOOGLE_TTS_LANGUAGE,
                    voice_name=settings.GOOGLE_TTS_VOICE_NAME,
                    gender=settings.GOOGLE_TTS_GENDER
                )
                logger.info(f"TTS client initialized with Google TTS (Language: {settings.GOOGLE_TTS_LANGUAGE}, Voice: {settings.GOOGLE_TTS_VOICE_NAME}, Gender: {settings.GOOGLE_TTS_GENDER}, Speaking Rate: {getattr(settings, 'GOOGLE_TTS_SPEAKING_RATE', 1.0)})")
            except Exception as e:
                logger.error(f"Failed to initialize Google TTS with specified settings: {e}. Falling back to OpenAI TTS.")
                # Fallback to OpenAI if Google TTS initialization fails
                tts_plugin = openai.TTS(
                    model=getattr(settings, 'OPENAI_TTS_MODEL', 'tts-1'), # Provide default if not set
                    voice=getattr(settings, 'OPENAI_TTS_VOICE', 'nova')   # Provide default if not set
                )
                logger.info(f"TTS client initialized with fallback OpenAI TTS (Model: {getattr(settings, 'OPENAI_TTS_MODEL', 'tts-1')}, Voice: {getattr(settings, 'OPENAI_TTS_VOICE', 'nova')})")
        
        elif hasattr(settings, 'TTS_PROVIDER') and settings.TTS_PROVIDER == "elevenlabs":
            tts_plugin = elevenlabs.TTS(
                model=getattr(settings, 'ELEVENLABS_MODEL', 'eleven_multilingual_v2'),
                voice_id=getattr(settings, 'ELEVENLABS_VOICE_ID', 'EXAVITQu4vr4xnSDxMaL'),  # Default voice ID
                api_key=settings.ELEVENLABS_API_KEY
            )
            logger.info(f"TTS client initialized with OpenAI TTS (Model: {getattr(settings, 'OPENAI_TTS_MODEL', 'tts-1')}, Voice: {getattr(settings, 'OPENAI_TTS_VOICE', 'nova')})")
        
        else: # Default or if TTS_PROVIDER is not set or invalid
            logger.warning(f"TTS_PROVIDER setting is missing or invalid ('{getattr(settings, 'TTS_PROVIDER', 'Not Set')}'). Defaulting to OpenAI TTS.")
            tts_plugin = openai.TTS(
                model=getattr(settings, 'OPENAI_TTS_MODEL', 'tts-1'),
                voice=getattr(settings, 'OPENAI_TTS_VOICE', 'nova')
            )
            logger.info(f"TTS client initialized with default OpenAI TTS (Model: {getattr(settings, 'OPENAI_TTS_MODEL', 'tts-1')}, Voice: {getattr(settings, 'OPENAI_TTS_VOICE', 'nova')})")
        
        stt_plugin = deepgram.STT(
            model="nova-2-conversationalai",
            # interim_results=True,
            # smart_format=True,
            # punctuate=True,
            # filler_words=True,
            # profanity_filter=False,
            keywords=[("LiveKit", 1.5)],
            language="en-US",
            endpointing_ms=25,
            no_delay=True,
            numerals=True
        )
        logger.info("STT client initialized")
        
        llm_plugin = google.LLM(
            model=settings.DEFAULT_LLM_MODEL,
            temperature=settings.DEFAULT_LLM_TEMPERATURE
        )
        # agent_config_client = SupabaseAgentConfigClient()
        # supabase_client = agent_config_client.client

        # llm_plugin = DynamicLLM(supabase_client)
        # await llm_plugin._refresh()  
        logger.info("LLM client initialized")
        
        # Connect to the room
        logger.info(f"Agent JobContext received for room {ctx.room.name}")
        await ctx.connect()
        logger.info(f"Connected to room {ctx.room.name}")

        # Initialize conversation manager
        conversation_manager = ConversationManager(ctx.room.name)
        await conversation_manager.initialize_session(ctx.room.name)
        logger.info(f"ConversationManager initialized for room: {ctx.room.name}")

        # Initialize SupabaseAgentConfigClient to fetch system prompt
        agent_config_client = SupabaseAgentConfigClient()

        agent_name_to_fetch = "homepage"
        system_prompt = await agent_config_client.get_system_prompt(agent_name=agent_name_to_fetch)

        system_prompt_to_use: str
        if system_prompt:
            system_prompt_to_use = system_prompt
            logger.info(f"Successfully fetched and will use system prompt for agent '{agent_name_to_fetch}'.")
        else:
            system_prompt_to_use = DEFAULT_AGENT_INSTRUCTIONS
            logger.warning(f"Failed to fetch system prompt for '{agent_name_to_fetch}'. Falling back to default AGENT_INSTRUCTIONS.")

        # Initialize the agent with the fetched or fallback prompt
        agent = PrepzoAgent(
            room_name=ctx.room.name, 
            conversation_manager=conversation_manager,
            instructions=system_prompt_to_use # Pass the fetched or fallback instructions
        )

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
        input_options = RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC()
        )
        await session.start(room=ctx.room, agent=agent, room_input_options=input_options)
        logger.info(f"AgentSession started for room {ctx.room.name}")


    except Exception as e:
        logger.error(f"Error in agent session: {str(e)}")
        logger.error(traceback.format_exc())
        # Ensure agent attempts to shutdown gracefully even on initialization error
        # though if ctx.connect() hasn't happened, it might not be fully effective.
        # Consider if a more specific shutdown is needed here.
        # For now, re-raising will let LiveKit handle termination.
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