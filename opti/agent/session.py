import asyncio
import traceback
import logging
import boto3
import json
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    RoomInputOptions,
    ConversationItemAddedEvent, 
    AgentStateChangedEvent,
)
from livekit.plugins import deepgram, silero, google,groq, openai, elevenlabs, noise_cancellation
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


def get_llm_plugin_from_aws():
    """
    Pulls LLM_PROVIDER (and any model/API‑key details) every time
    this is called, so that each new session picks up the latest secret.
    """
    client = boto3.client('secretsmanager', region_name=settings.AWS_REGION)
    resp = client.get_secret_value(SecretId='llm-config')
    secret = json.loads(resp['SecretString'])
    provider = secret.get('LLM_PROVIDER', '').lower()

    if provider == 'google':
        logger.info("Using Google LLM (from AWS Secret)")
        return google.LLM(
            model=secret.get('MODEL', settings.DEFAULT_LLM_MODEL),
            temperature=float(secret.get('TEMPERATURE', settings.DEFAULT_LLM_TEMPERATURE)),
        )

    elif provider == 'groq':
        logger.info("Using Groq LLM (from AWS Secret)")
        return groq.LLM(
            model=secret.get('MODEL', settings.GROQ_LLM_MODEL),
            temperature=float(secret.get('TEMPERATURE', settings.GROQ_TEMPERATURE)),
            api_key=secret.get('API_KEY', settings.GROQ_API_KEY),
        )

    elif provider == 'openai':
        logger.info("Using OpenAI LLM (from AWS Secret)")
        return openai.LLM(
            model=secret.get('MODEL', settings.OPENAI_MODEL),
            temperature=float(secret.get('TEMPERATURE', settings.OPENAI_TEMPERATURE)),
            api_key=secret.get('API_KEY', settings.OPENAI_API_KEY),
        )

    else:
        raise ValueError(f"Unsupported LLM provider in secret: {provider!r}")

def get_tts_plugin_from_aws():
    """
    Fetches TTS settings from AWS Secrets Manager on each call,
    and returns an initialized TTS plugin instance.
    """
    client = boto3.client('secretsmanager', region_name=settings.AWS_REGION)
    resp = client.get_secret_value(SecretId='llm-config')
    secret = json.loads(resp['SecretString'])
    provider = secret.get('TTS_PROVIDER', 'openai').lower()

    if provider == 'elevenlabs':
        # Required keys: ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID, ELEVENLABS_MODEL
        api_key  = secret['ELEVENLABS_API_KEY']
        voice_id = secret.get('ELEVENLABS_VOICE_ID', settings.ELEVENLABS_VOICE_ID)
        model    = secret.get('ELEVENLABS_MODEL', settings.ELEVENLABS_MODEL)
        logger.info("Initializing ElevenLabs TTS from AWS secret")
        return elevenlabs.TTS(model=model, voice_id=voice_id, api_key=api_key)

    elif provider == 'openai':
        # Required keys: OPENAI_API_KEY, DEFAULT_TTS_MODEL, DEFAULT_TTS_VOICE
        api_key = secret['OPENAI_TTS_API_KEY']
        model   = secret.get('OPENAI_TTS_MODEL', settings.OPENAI_TTS_MODEL)
        voice   = secret.get('OPENAI_TTS_VOICE', settings.OPENAI_TTS_VOICE)
        logger.info("Initializing OpenAI TTS from AWS secret")
        return openai.TTS(model=model, voice=voice, api_key=api_key)

    else:
        error = f"Unsupported TTS provider in secret: {provider}"
        logger.error(error)
        raise ValueError(error)

def get_stt_plugin_from_aws():
    """
    Fetches STT settings from AWS Secrets Manager on each call,
    and returns an initialized STT plugin instance.
    """
    client = boto3.client('secretsmanager', region_name=settings.AWS_REGION)
    resp = client.get_secret_value(SecretId='llm-config')
    secret = json.loads(resp['SecretString'])

    api_key       = secret['DEEPGRAM_API_KEY']
    model         = secret.get('STT_MODEL', 'nova-2-conversationalai')
    language      = secret.get('LANGUAGE', 'en-US')

    logger.info("Initializing Deepgram STT from AWS secret")
    return deepgram.STT(
            api_key=api_key,
            model=model,
            language=language,
    
        )
    
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
        
        tts_task = asyncio.to_thread(get_tts_plugin_from_aws)
        stt_task = asyncio.to_thread(get_stt_plugin_from_aws)
        llm_task = asyncio.to_thread(get_llm_plugin_from_aws)

        results = await asyncio.gather(
            tts_task, stt_task, llm_task,
            return_exceptions=True
        )
        def _fallback(name):
            if name == 'tts':
                return openai.TTS(
                    model=settings.DEFAULT_TTS_MODEL,
                    voice=settings.DEFAULT_TTS_VOICE,
                    api_key=settings.OPENAI_API_KEY
                )
            if name == 'stt':
                return deepgram.STT(
                    api_key=settings.DEEPGRAM_API_KEY,
                    model='nova-2-conversationalai',
                    language='en-US'
                )
            if name == 'llm':
                return google.LLM(
                    model=settings.DEFAULT_LLM_MODEL,
                    temperature=settings.DEFAULT_LLM_TEMPERATURE
                )
        
        plugins = []
        for name, res in zip(['tts','stt','llm'], results):
            if isinstance(res, Exception):
                logger.error(f"{name.upper()} init failed: {res}")
                plugins.append(_fallback(name))
            else:
                plugins.append(res)

        tts_plugin, stt_plugin, llm_plugin = plugins

        
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