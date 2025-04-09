from __future__ import annotations
import asyncio
import logging
import traceback
import re
from typing import Any, AsyncIterable
from dotenv import load_dotenv
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    WorkerOptions,
    WorkerType,
    cli,
    llm,
    metrics,
)
from livekit.agents.pipeline import VoicePipelineAgent
from livekit.plugins import google, deepgram, silero
from livekit import rtc
from livekit.agents.llm import ChatMessage
from prompts import prompt
from conversation_manager import ConversationManager
import os
import json
# Import knowledge base functions
from knowledgebase import AssistantFnc

# Load environment variables from .env.local
load_dotenv(dotenv_path=".env.local")

# Configure logging
logger = logging.getLogger("voice-agent")
logger.setLevel(logging.DEBUG)


# Also log to console
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
logger.addHandler(console_handler)

logger.info("Starting voice agent application")

async def entrypoint(ctx: JobContext):
    try:
        logger.info(f"Connecting to room {ctx.room.name}")
        await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
        participant = await ctx.wait_for_participant()
        logger.info(f"Starting voice assistant for participant {participant.identity}")
        logger.info(f"Creating conversation manager with session ID: {ctx.room.name}")
        conversation_manager = ConversationManager(ctx.room.name)
        await conversation_manager.initialize_session(participant.identity)

        logger.info("Instantiating AssistantFnc for knowledge base and web search...")
        try:
            assistant_fnc = AssistantFnc(
                google_api_key=os.environ["GEMINI_API_KEY"],
                pinecone_api_key=os.environ["PINECONE_API_KEY"],
                pinecone_region=os.environ["PINECONE_REGION"],
                pinecone_cloud=os.getenv("PINECONE_CLOUD", "aws"),
                serp_api_key=os.environ["SERPAPI_KEY"]
            )
            logger.info("AssistantFnc instantiated successfully.")
        except KeyError as e:
            logger.error(f"Missing required environment variable for AssistantFnc: {e}")
            raise
        except Exception as e:
            logger.error(f"Error instantiating AssistantFnc: {e}", exc_info=True)
            raise

        # Define initial chat context
        # CRITICAL: prompts.py MUST be updated for native function calling
        # (Remove TOOL_CALL::, describe capabilities naturally)
        initial_ctx = llm.ChatContext().append(
            role="system",
            text=prompt # This prompt needs to be suitable for native function calling
        )

        # Instantiate pipeline components
        vad = silero.VAD.load() # Assuming VAD is needed again
        stt = deepgram.STT(
            model="nova-2",
            language="en-US",
            interim_results=True,
            punctuate=True,
        )
        google_llm_instance = google.LLM(
            model="gemini-2.0-flash",
            temperature=0.8,
            # functions argument removed previously
        )
        logger.info("Google LLM initialized.")

        tts = google.TTS(
            language="en-US",
            gender="female",
            voice_name="en-US-Chirp-HD-F"
        )

        # Create the Voice Pipeline Agent WITHOUT the callback
        agent = VoicePipelineAgent(
            vad=vad, # Added VAD back
            stt=stt,
            llm=google_llm_instance,
            tts=tts,
            chat_ctx=initial_ctx,
            allow_interruptions=True,
            min_endpointing_delay=0.5,
            max_endpointing_delay=5.0,
            # REMOVED before_tts_cb
        )
        logger.info("Voice Pipeline Agent created.")

        # --- Attempt to set fncCtx property ---
        try:
            # This is the experimental part based on Node.js docs hint
            agent.fncCtx = assistant_fnc
            logger.info("Successfully set agent.fncCtx property.")
        except AttributeError:
            logger.error("!!! VoicePipelineAgent instance does not have 'fncCtx' property in this Python version. Native function calling via this method likely won't work. !!!")
        except Exception as e:
            logger.error(f"Error attempting to set agent.fncCtx: {e}", exc_info=True)
        # --- End attempt ---

        # --- Event Handlers --- (Remain the same)
        @agent.on("user_speech_committed")
        def on_user_speech_committed(msg: llm.ChatMessage):
            try:
                logger.info(f"User speech committed: '{msg.content[:50]}...'")
                message_data = conversation_manager.create_message_data(msg, "user")
                conversation_manager.add_message(message_data)
                # Let the pipeline handle calling the LLM now
            except Exception as e:
                logger.error(f"Error in user_speech_committed: {str(e)}", exc_info=True)

        @agent.on("agent_speech_committed")
        def on_agent_speech_committed(msg: llm.ChatMessage):
            try:
                logger.info(f"Agent speech committed: '{msg.content[:50]}...'")
                message_data = conversation_manager.create_message_data(msg, "assistant", "agent_speech_committed")
                conversation_manager.add_message(message_data)
            except Exception as e:
                logger.error(f"Error in agent_speech_committed: {str(e)}", exc_info=True)

        @agent.on("agent_speech_interrupted")
        def on_agent_speech_interrupted(msg: llm.ChatMessage):
            try:
                logger.info(f"Agent speech interrupted: '{msg.content[:50]}...'")
                message_data = conversation_manager.create_message_data(msg, "assistant", "agent_speech_interrupted")
                conversation_manager.add_message(message_data)
            except Exception as e:
                logger.error(f"Error in agent_speech_interrupted: {str(e)}", exc_info=True)

        logger.info(f"Starting agent in room {ctx.room.name}")
        agent.start(ctx.room, participant)
        # await agent.say(WELCOME_MESSAGE, allow_interruptions=True) # Optional welcome

    except Exception as e:
        logger.error(f"Error in entrypoint: {str(e)}")
        logger.error(traceback.format_exc())
        raise

if __name__ == "__main__":
    cli.run_app(
        WorkerOptions( entrypoint_fnc=entrypoint )
    )
