from __future__ import annotations
import asyncio
import logging
import traceback
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
from livekit.plugins import google, silero
from livekit import rtc
from livekit.agents.llm import ChatMessage
from prompts import prompt
from conversation_manager import ConversationManager
import os
import json
# Import knowledge base functions
from knowledgebase import query_pinecone_knowledge_base, perform_web_search

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

# --- Tool Handling Callback ---
async def handle_tool_calls_before_tts(assistant: VoicePipelineAgent, text: str | AsyncIterable[str]) -> str | AsyncIterable[str]:
    """Checks LLM output for tool calls and executes them."""
    # Handle potential AsyncIterable - for now, assume str for tool calls
    # A more robust solution might iterate through the async iterable if needed
    if isinstance(text, AsyncIterable):
        # For now, if it's iterable, pass it through without checking for tool calls.
        # Tool calls are expected to be single string responses from the LLM.
        logger.warning("Received AsyncIterable in before_tts_cb, skipping tool check.")
        return text

    # Proceed assuming text is a string
    if text.startswith("TOOL_CALL::"):
        logger.info(f"Detected tool call format: {text}")
        parts = text.split("::", 2)
        if len(parts) == 3:
            _, tool_name, query = parts
            query = query.strip()
            logger.info(f"Attempting to call tool '{tool_name}' with query: '{query[:50]}...'")

            try:
                if tool_name == "query_pinecone_knowledge_base":
                    result = await query_pinecone_knowledge_base(query)
                    if result:
                        # We don't want the agent to SAY the whole KB result.
                        # Instead, we'll add it to the context *later* (or assume the LLM
                        # will use it in the *next* turn). For now, just give a confirmation.
                        logger.info("Knowledge base query successful.")
                        # Change placeholder to be more generic
                        return "Okay, one moment." # Generic placeholder response
                    else:
                        logger.warning(f"Knowledge base query '{tool_name}' returned no results.")
                        return "Sorry, I couldn't find specific details on that in my knowledge base." # Error response
                elif tool_name == "perform_web_search":
                    result = await perform_web_search(query)
                    if result and not result.startswith("Web search failed") and not result.startswith("Web search is currently unavailable"):
                        # Similar to KB, don't read out search results directly.
                        logger.info("Web search successful.")
                        # Change placeholder to be more generic
                        return "Okay, one moment." # Generic placeholder response
                    else:
                        logger.warning(f"Web search '{tool_name}' failed or returned no results: {result}")
                        return result if result else "Sorry, I wasn't able to find current information on that." # Error response
                else:
                    logger.error(f"Received unknown tool name: {tool_name}")
                    return f"Sorry, I encountered an issue with an internal tool ({tool_name})."
            except Exception as e:
                logger.error(f"Error executing tool '{tool_name}': {e}", exc_info=True)
                return f"Sorry, I ran into an error while trying to use my {tool_name.replace('_', ' ')} tool."
        else:
            logger.error(f"Malformed TOOL_CALL received: {text}")
            return "Sorry, I had a little trouble processing that request."
    else:
        # No tool call detected, pass the original text through to TTS
        return text

async def entrypoint(ctx: JobContext):
    try:
        logger.info(f"Connecting to room {ctx.room.name}")
        await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

        participant = await ctx.wait_for_participant()
        logger.info(f"Starting voice assistant for participant {participant.identity}")

        logger.info(f"Creating conversation manager with session ID: {ctx.room.name}")
        conversation_manager = ConversationManager(ctx.room.name)
        await conversation_manager.initialize_session(participant.identity)

        # Define initial chat context with system prompt
        initial_ctx = llm.ChatContext().append(
            role="system",
            text=prompt
        )

        # Instantiate pipeline components
        vad = silero.VAD.load()
        stt = google.STT(
            model="long",
            spoken_punctuation=True,
        )
        google_llm = google.LLM(
            model="gemini-2.0-flash-exp", # Keep explicit model
            temperature=0.8,
            api_key=os.getenv("GOOGLE_API_KEY"), # Keep explicit key
            vertexai=False # Explicitly use Google AI, not Vertex
        )
        tts = google.TTS(
            language="en-US", # Example language
            gender="female", # Changed voice gender preference
            # Changed voice from Standard to Neural2 for better quality/latency
            voice_name="en-US-Chirp-HD-F" # Example male Neural2 voice
             # Credentials assumed to be handled by environment variables/ADC
        )

        # Replace MultimodalAgent with VoicePipelineAgent
        agent = VoicePipelineAgent(
            vad=vad,
            stt=stt,
            llm=google_llm,
            tts=tts,
            chat_ctx=initial_ctx,
            allow_interruptions=True,
            # interrupt_speech_duration=0.5, # Default
            # interrupt_min_words=0, # Default
            min_endpointing_delay=0.5, # Default
            # Add the callback to intercept LLM responses before TTS
            before_tts_cb=handle_tool_calls_before_tts
        )
        logger.info("Voice Pipeline Agent created")

        # Update event handler signature for user speech
        @agent.on("user_speech_committed")
        def on_user_speech_committed(msg: llm.ChatMessage): # Changed signature from str to ChatMessage
            try:
                # msg is already a ChatMessage object
                logger.info(f"User speech committed: '{msg.content[:50]}...'")
                message_data = conversation_manager.create_message_data(
                    msg, "user" # msg is already ChatMessage
                )

                conversation_manager.add_message(message_data)
                # No need to manually call process_user_speech, pipeline handles it
                # asyncio.create_task(process_user_speech(msg))
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

        # Removed process_user_speech and handle_query as pipeline handles flow
        # async def process_user_speech(msg: llm.ChatMessage): ...
        # async def handle_query(msg: llm.ChatMessage): ...

        logger.info(f"Starting agent in room {ctx.room.name}")
        agent.start(ctx.room, participant)

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
                worker_type=WorkerType.ROOM
            ),
        )
    except Exception as e:
        logger.error(f"Application error: {str(e)}")
        logger.error(traceback.format_exc())
