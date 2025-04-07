from __future__ import annotations
import asyncio
import logging
import traceback
from dotenv import load_dotenv
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
    llm,
    metrics,
)
from livekit.agents.pipeline import VoicePipelineAgent
from livekit.plugins import cartesia, openai, deepgram, silero
from livekit import rtc
from livekit.agents.llm import ChatMessage
from api import AssistantFnc
from prompts import WELCOME_MESSAGE, LOOKUP_PROFILE_MESSAGE
from conversation_manager import ConversationManager
import os
import json

# Load environment variables from .env.local
load_dotenv(dotenv_path=".env.local")

# Configure logging
logger = logging.getLogger("voice-agent")
logger.setLevel(logging.DEBUG)

# Create a file handler for agent logs
file_handler = logging.FileHandler('agent_logs.log')
file_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Also log to console
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

logger.info("Starting voice agent application")

def prewarm(proc: JobProcess):
    """
    Preload the voice activity detector (VAD) from Silero.
    """
    proc.userdata["vad"] = silero.VAD.load()
    logger.info("Loaded VAD model in prewarm")

async def entrypoint(ctx: JobContext):
    try:
        # Set up the initial system prompt.
        initial_ctx = llm.ChatContext().append(
            role="system",
            text=(
                "You are a voice assistant created by LiveKit. "
                "Keep responses short and use clear language."
            ),
        )

        logger.info(f"Connecting to room {ctx.room.name}")
        await ctx.connect(auto_subscribe=AutoSubscribe.SUBSCRIBE_ALL)

        participant = await ctx.wait_for_participant()
        logger.info(f"Starting voice assistant for participant {participant.identity}")

        assistant_fnc = AssistantFnc()
        
        # Use room name as the session ID
        logger.info(f"Creating conversation manager with session ID: {ctx.room.name}")
        conversation_manager = ConversationManager(ctx.room.name)
        await conversation_manager.initialize_session(participant.identity)

        agent = VoicePipelineAgent(
            vad=ctx.proc.userdata["vad"],
            stt=deepgram.STT(),
            llm=openai.LLM(model="gpt-4o-mini"),
            tts=cartesia.TTS(),
            min_endpointing_delay=0.5,
            max_endpointing_delay=5.0,
            chat_ctx=initial_ctx
        )
        logger.info("Voice Pipeline Agent created")

        usage_collector = metrics.UsageCollector()

        @agent.on("metrics_collected")
        def on_metrics_collected(agent_metrics: metrics.AgentMetrics):
            metrics.log_metrics(agent_metrics)
            usage_collector.collect(agent_metrics)
            logger.debug(f"Metrics collected: {agent_metrics}")

        @agent.on("user_speech_committed")
        def on_user_speech_committed(msg: llm.ChatMessage):
            try:
                if isinstance(msg.content, list):
                    msg.content = "\n".join(str(x) for x in msg.content)
                
                logger.info(f"User speech committed: '{msg.content[:50]}...'")
                message_data = conversation_manager.create_message_data(msg, "user")
                
                # Add message and update conversation history
                conversation_manager.add_message(message_data)
                
                # Process user speech in a separate task
                asyncio.create_task(process_user_speech(msg))
            except Exception as e:
                logger.error(f"Error in user_speech_committed: {str(e)}")
                logger.error(traceback.format_exc())

        @agent.on("agent_speech_committed")
        def on_agent_speech_committed(msg: llm.ChatMessage):
            try:
                logger.info(f"Agent speech committed: '{msg.content[:50]}...'")
                message_data = conversation_manager.create_message_data(
                    msg, "assistant", "agent_speech_committed"
                )
                
                # Add message and update conversation history
                conversation_manager.add_message(message_data)
            except Exception as e:
                logger.error(f"Error in agent_speech_committed: {str(e)}")
                logger.error(traceback.format_exc())

        @agent.on("agent_speech_interrupted")
        def on_agent_speech_interrupted(msg: llm.ChatMessage):
            try:
                logger.info(f"Agent speech interrupted: '{msg.content[:50]}...'")
                message_data = conversation_manager.create_message_data(
                    msg, "assistant", "agent_speech_interrupted"
                )
                
                # Add message and update conversation history
                conversation_manager.add_message(message_data)
            except Exception as e:
                logger.error(f"Error in agent_speech_interrupted: {str(e)}")
                logger.error(traceback.format_exc())

        async def process_user_speech(msg: llm.ChatMessage):
            try:
                if hasattr(assistant_fnc, "has_profile"):
                    try:
                        if await assistant_fnc.has_profile():
                            await handle_query(msg)
                        else:
                            await find_profile(msg)
                    except Exception as e:
                        logger.error(f"Error in has_profile: {e}")
                        await handle_query(msg)
                else:
                    await handle_query(msg)
            except Exception as e:
                logger.error(f"Error in process_user_speech: {str(e)}")
                logger.error(traceback.format_exc())

        async def find_profile(msg: llm.ChatMessage):
            logger.info("Finding user profile")
            agent.session.conversation.item.create(
                ChatMessage(
                    role="system",
                    content=LOOKUP_PROFILE_MESSAGE(msg)
                )
            )
            agent.session.response.create()

        async def handle_query(msg: llm.ChatMessage):
            logger.info("Handling user query")
            agent.session.conversation.item.create(
                ChatMessage(
                    role="user",
                    content=msg.content
                )
            )
            agent.session.response.create()

        logger.info(f"Starting agent in room {ctx.room.name}")
        agent.start(ctx.room, participant)
        
        # Add initial welcome message to conversation storage
        welcome_msg = ChatMessage(role="assistant", content=WELCOME_MESSAGE)
        logger.info(f"Sending welcome message: '{WELCOME_MESSAGE[:50]}...'")
        
        # Create and store welcome message
        message_data = conversation_manager.create_message_data(
            welcome_msg, "assistant", "agent_speech_committed"
        )
        conversation_manager.add_message(message_data)
        
        # Force an immediate update of the conversation history
        await conversation_manager.update_conversation_history()
        
        # Say the welcome message
        await agent.say(WELCOME_MESSAGE, allow_interruptions=True)
        logger.info("Welcome message sent")
        
    except Exception as e:
        logger.error(f"Error in entrypoint: {str(e)}")
        logger.error(traceback.format_exc())
        raise

if __name__ == "__main__":
    try:
        logger.info("Starting application")
        cli.run_app(
            WorkerOptions(
                entrypoint_fnc=entrypoint,
                prewarm_fnc=prewarm,
            ),
        )
    except Exception as e:
        logger.error(f"Application error: {str(e)}")
        logger.error(traceback.format_exc())
