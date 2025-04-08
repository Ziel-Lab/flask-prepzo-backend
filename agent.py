from __future__ import annotations
import asyncio
import logging
import traceback
from typing import Any
from dotenv import load_dotenv
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    WorkerOptions,
    WorkerType,
    cli,
    llm,
    metrics,
    multimodal
)
from livekit.plugins import google
import google.generativeai as genai
from livekit import rtc
from livekit.agents.llm import ChatMessage
from prompts import prompt
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

async def entrypoint(ctx: JobContext):
    try:
        logger.info(f"Connecting to room {ctx.room.name}")
        await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

        participant = await ctx.wait_for_participant()
        logger.info(f"Starting voice assistant for participant {participant.identity}")

        logger.info(f"Creating conversation manager with session ID: {ctx.room.name}")
        conversation_manager = ConversationManager(ctx.room.name)
        await conversation_manager.initialize_session(participant.identity)

        agent = multimodal.MultimodalAgent(
            model=google.beta.realtime.RealtimeModel(
                instructions=prompt, # Restore prompt from prompts.py
                model="gemini-2.0-flash-exp", # Keep explicit model
                voice="Puck", # Changed voice to Puck
                temperature=0.8,
                modalities=["AUDIO"],
                api_key=os.getenv("GOOGLE_API_KEY"), # Keep explicit key
                # vertexai defaults to False, which is correct (not using Vertex)
            )
        )
        logger.info("Multimodal Agent created")

        @agent.on("user_speech_committed")
        def on_user_speech_committed(msg: str):
            try:
                msg_content = msg

                logger.info(f"User speech committed: '{msg_content[:50]}...'")
                message_data = conversation_manager.create_message_data(
                    ChatMessage(role="user", content=msg_content), "user"
                )

                conversation_manager.add_message(message_data)
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
                await handle_query(msg)
            except Exception as e:
                logger.error(f"Error in process_user_speech: {str(e)}")
                logger.error(traceback.format_exc())




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

       
        actual_welcome = "Hi there. I'm Prepzo. I help with career stuff..."

        welcome_msg_obj = ChatMessage(role="assistant", content=actual_welcome)
        logger.info(f"Adding conceptual welcome message to history: '{actual_welcome[:50]}...'")
        message_data = conversation_manager.create_message_data(
            welcome_msg_obj, "assistant", "initial_greeting"
        )
        conversation_manager.add_message(message_data)
        await conversation_manager.update_conversation_history()
       

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
