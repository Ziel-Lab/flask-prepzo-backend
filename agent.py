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

from livekit.agents.voice_assistant import  VoiceAssistant
from livekit.plugins import deepgram, silero, google, elevenlabs
from livekit.plugins import openai
from livekit.agents.llm import ChatMessage
from api import AssistantFnc  # Updated AssistantFnc now contains the web search functionality
from prompts import INSTRUCTIONS, WELCOME_MESSAGE
from conversation_manager import ConversationManager
import os

# os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "./gen-lang-client-0003271291-fe4c916d53c2.json"
load_dotenv(dotenv_path=".env.local")

logger = logging.getLogger("voice-agent")
logger.setLevel(logging.DEBUG)



console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
logger.addHandler(console_handler)

logger.info("Starting voice agent application")


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()
    logger.info("Loaded VAD model in prewarm")


async def entrypoint(ctx: JobContext):
    try:
        # Initialize TTS client using elevenlabs
        # tts_client = elevenlabs.tts.TTS(
        #     api_key=os.getenv("ELEVENLABS_API_KEY"),
        #     model="eleven_flash_v2_5",
        #     voice=elevenlabs.tts.Voice(
        #         id="EXAVITQu4vr4xnSDxMaL",
        #         name="Bella",
        #         category="premade",
        #         settings=elevenlabs.tts.VoiceSettings(
        #             stability=0.71,
        #             similarity_boost=0.5,
        #             style=0.0,
        #             use_speaker_boost=True
        #         ),
        #     ),
        #     language="en",
        #     streaming_latency=3,
        #     enable_ssml_parsing=False,
        #     chunk_length_schedule=[80, 120, 200, 260],
        # )
        tts_client = openai.TTS(
                    model="gpt-4o-mini-tts",
                    voice="nova",
                    instructions="Speak in a friendly and conversational tone.",
        )
        
        logger.info("LiveKit TTS client initialized")

        # Create the initial chat context with system instructions
        initial_ctx = llm.ChatContext().append(
            role="system",
            text=INSTRUCTIONS
        )

        logger.info(f"Connecting to room {ctx.room.name}")
        await ctx.connect(auto_subscribe=AutoSubscribe.SUBSCRIBE_ALL)
        # Wait for a participant to join (if your use case still requires it)
        await ctx.wait_for_participant()
        logger.info(f"Participant connected in room {ctx.room.name}")

        # Create your updated function context (which now includes web search)
        assistant_fnc = AssistantFnc()

        # (Optional) Initialize a conversation manager for logging messages
        conversation_manager = ConversationManager(ctx.room.name)
        # For example, if you wish to track conversation history:
        await conversation_manager.initialize_session(ctx.room.name)

        # Create the VoiceAssistant instance
        assistant = VoiceAssistant(
            vad=ctx.proc.userdata["vad"],
            stt=deepgram.STT(),
            llm=google.LLM(
                model="gemini-2.0-flash",
                temperature=0.8
            ),
            tts=tts_client,
            fnc_ctx=assistant_fnc,  # Your function context including the web search tool
            chat_ctx=initial_ctx
        )
        logger.info("Voice Assistant created")

        usage_collector = metrics.UsageCollector()

        @assistant.on("metrics_collected")
        def on_metrics_collected(agent_metrics: metrics.AgentMetrics):
            metrics.log_metrics(agent_metrics)
            usage_collector.collect(agent_metrics)
            logger.debug(f"Metrics collected: {agent_metrics}")

        @assistant.on("user_speech_committed")
        def on_user_speech_committed(msg: llm.ChatMessage):
            try:
                if isinstance(msg.content, list):
                    msg.content = "\n".join(str(x) for x in msg.content)
                logger.info(f"User speech committed: '{msg.content[:50]}...'")
                conversation_manager.add_message({
                    "role": "user",
                    "content": msg.content
                })
               
            except Exception as e:
                logger.error(f"Error in user_speech_committed: {str(e)}")
                logger.error(traceback.format_exc())

        @assistant.on("agent_speech_committed")
        def on_agent_speech_committed(msg: llm.ChatMessage):
            try:
                logger.info(f"Agent speech committed: '{msg.content[:50]}...'")
                conversation_manager.add_message({
                    "role": "assistant",
                    "content": msg.content
                })
               
            except Exception as e:
                logger.error(f"Error in agent_speech_committed: {str(e)}")
                logger.error(traceback.format_exc())

        @assistant.on("agent_speech_interrupted")
        def on_agent_speech_interrupted(msg: llm.ChatMessage):
            try:
                logger.info(f"Agent speech interrupted: '{msg.content[:50]}...'")
                conversation_manager.add_message({
                    "role": "assistant",
                    "content": msg.content + " (interrupted)"
                })
            except Exception as e:
                logger.error(f"Error in agent_speech_interrupted: {str(e)}")
                logger.error(traceback.format_exc())

        logger.info(f"Starting assistant in room {ctx.room.name}")
        # For VoiceAssistant, call start() with only the room name
        assistant.start(ctx.room)

      
        logger.info("Generating initial welcome message from LLM...")
        await assistant.complete_chat() # LLM generates opening based on INSTRUCTIONS
       

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
