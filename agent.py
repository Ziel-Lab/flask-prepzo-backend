from __future__ import annotations
import asyncio
import logging
import traceback
import json # Import json for formatting tool calls
# Import AsyncIterable from typing
from typing import AsyncIterable
from dotenv import load_dotenv

# Updated imports for v1.0+
from livekit import agents
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    WorkerOptions,
    cli,
    llm,
    ChatContext,
    RoomInputOptions,
    function_tool,
    FunctionTool,
    ModelSettings,
    ConversationItemAddedEvent,
    AgentStateChangedEvent
)
from livekit.plugins import deepgram, silero, google, openai # Keep relevant plugins
from livekit.agents.llm import ChatMessage, ChatRole # May not be needed if using event.message directly
from api import AssistantFnc
from prompts import INSTRUCTIONS, WELCOME_MESSAGE
from conversation_manager import ConversationManager
import os

load_dotenv(dotenv_path=".env.local")

logger = logging.getLogger("voice-agent")
logger.setLevel(logging.DEBUG)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
logger.addHandler(console_handler)

logger.info("Starting voice agent application (v1.0+ structure)")

# Prewarm function is generally not needed in this way with AgentSession
# def prewarm(proc: JobProcess):
#     proc.userdata["vad"] = silero.VAD.load()
#     logger.info("Loaded VAD model in prewarm")


# Define the custom Agent class
class PrepzoAgent(Agent):
    def __init__(self, room_name: str, conversation_manager: ConversationManager):
        self.assistant_fnc = AssistantFnc(room_name=room_name)
        self.conversation_manager = conversation_manager # Store ConversationManager instance

        tools = [
            self.assistant_fnc.get_user_email,
            self.assistant_fnc.web_search,
            self.assistant_fnc.request_email,
            self.assistant_fnc.set_agent_state,
            self.assistant_fnc.search_knowledge_base,
        ]
        super().__init__(instructions=INSTRUCTIONS, tools=tools)
        logger.info(f"PrepzoAgent initialized for room: {room_name} with {len(tools)} tools.")

    # Override llm_node to intercept tool calls and results
    async def llm_node(
        self,
        chat_ctx: llm.ChatContext,
        tools: list[llm.FunctionTool],
        model_settings: ModelSettings,
    ) -> AsyncIterable[llm.ChatChunk]:
        llm_stream = Agent.default.llm_node(self, chat_ctx, tools, model_settings)
        
        async for chunk in llm_stream:
            if hasattr(chunk, 'delta') and hasattr(chunk.delta, 'tool_calls') and chunk.delta.tool_calls:
                tool_calls = chunk.delta.tool_calls
                # Log the raw string representation of the tool_calls object
                tool_calls_str = str(tool_calls)
                logger.info(f"LLM requested tool call(s): {tool_calls_str}") # Keep terminal log for comparison
                try:
                    # Log the raw string representation to ConversationManager
                    self.conversation_manager.add_message({
                        "role": "tool_call",
                        "content": tool_calls_str 
                    })
                    logger.info("Logged raw tool call request string to ConversationManager.")
                except Exception as e:
                    logger.error(f"Error logging raw tool call request string: {e}")
            
            yield chunk


async def entrypoint(ctx: JobContext):
    try:
        logger.info("Initializing VAD model")
        vad_plugin = silero.VAD.load()

        logger.info("Initializing TTS client")
        tts_plugin = openai.TTS(
            model="gpt-4o-mini-tts",
            voice="nova",
        )

        logger.info("Initializing STT client")
        stt_plugin = deepgram.STT()

        logger.info("Initializing LLM client")
        llm_plugin = google.LLM(
            model="gemini-2.0-flash",
            temperature=0.8
        )

        logger.info(f"Agent JobContext received for room {ctx.room.name}")
        await ctx.connect()
        logger.info(f"Connected to room {ctx.room.name}")

        # Instantiate ConversationManager first
        conversation_manager = ConversationManager(ctx.room.name)
        await conversation_manager.initialize_session(ctx.room.name)
        logger.info(f"ConversationManager initialized and session started for room: {ctx.room.name}")

        # Instantiate the custom agent, passing the conversation_manager
        agent = PrepzoAgent(room_name=ctx.room.name, conversation_manager=conversation_manager)

        session = AgentSession(
            vad=vad_plugin,
            stt=stt_plugin,
            llm=llm_plugin,
            tts=tts_plugin,
        )
        logger.info("AgentSession created")

        # Define Event Handlers using documented events and string names
        @session.on("conversation_item_added")
        def on_conversation_item_added(event: ConversationItemAddedEvent):
            item = event.item
            role_str = ""
            if item.role == "user":
                role_str = "user"
            elif item.role == "assistant":
                role_str = "assistant"
            
            # Use text_content attribute as per documentation
            content = item.text_content 
            
            if role_str and content:
                logger.info(f"Conversation item added ({role_str}): '{content[:50]}...'")
                try:
                    conversation_manager.add_message({
                        "role": role_str,
                        "content": content
                    })
                    logger.info(f"Logged {role_str} message to ConversationManager.")
                except Exception as e:
                    logger.error(f"Error in on_conversation_item_added handler: {str(e)}")
                    logger.error(traceback.format_exc())
            elif role_str:
                 logger.warning(f"Received ConversationItemAddedEvent for role '{role_str}' with empty text content.")

        @session.on("agent_state_changed")
        def on_agent_state_changed(event: AgentStateChangedEvent):
            logger.info(f"Agent state changed from {event.old_state} to {event.new_state}")

        # --- End Event Handlers ---

        logger.info(f"Starting AgentSession in room {ctx.room.name}")
        input_options = RoomInputOptions()
        await session.start(room=ctx.room, agent=agent, room_input_options=input_options)
        logger.info(f"AgentSession started for room {ctx.room.name}")

        logger.info("Generating initial welcome message...")
        await session.say(text=WELCOME_MESSAGE)

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
            ),
        )
    except Exception as e:
        logger.error(f"Application error: {str(e)}")
        logger.error(traceback.format_exc())
