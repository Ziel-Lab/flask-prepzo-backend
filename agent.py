from __future__ import annotations
import asyncio
import logging
import traceback
import json # Import json for formatting tool calls
# Import AsyncIterable from typing
from typing import AsyncIterable
from dotenv import load_dotenv

# For resume processing
# Required package: pip install google-generativeai
import tempfile
import os
import google.generativeai as genai
from google.generativeai import GenerativeModel
import base64
import datetime

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
from livekit import rtc
from livekit.rtc import ByteStreamReader, RemoteParticipant  # Add ByteStreamReader
from livekit.plugins import deepgram, silero, google, openai # Keep relevant plugins
from livekit.agents.llm import ChatMessage, ChatRole # May not be needed if using event.message directly
from api import AssistantFnc
from prompts import INSTRUCTIONS, WELCOME_MESSAGE
from conversation_manager import ConversationManager

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
    def __init__(self, ctx: JobContext, room_name: str, conversation_manager: ConversationManager):
        self.ctx = ctx
        self.assistant_fnc = AssistantFnc(ctx=ctx, room_name=room_name)
        tools = [
            self.assistant_fnc.get_user_email,
            self.assistant_fnc.web_search,
            self.assistant_fnc.request_email,
            self.assistant_fnc.request_resume,
            self.assistant_fnc.process_resume_content,
            self.assistant_fnc.set_agent_state,
            self.assistant_fnc.search_knowledge_base,
            self.assistant_fnc.fetch_resume_raw,
            self.assistant_fnc.fetch_resume_analysis,
        ]
        super().__init__(instructions=INSTRUCTIONS, tools=tools)
        logger.info(f"PrepzoAgent initialized for room: {room_name} with {len(tools)} tools.")
        
        self.conversation_manager = conversation_manager
        # Share conversation manager with assistant function
        self.assistant_fnc.ctx.conversation_manager = conversation_manager
        
        # Resume tracking
        self.resume_analysis_loaded = False
        self.resume_metadata = {
            "name": None,
            "type": None,
            "size": None,
            "analyzed": False
        }
        self._agent_session_ref = None  # Internal reference to session
    
    async def ensure_resume_analysis_loaded(self):
        """Make sure the resume analysis is loaded into the conversation context if available"""
        if self.resume_analysis_loaded:
            logger.info("Resume analysis already loaded in conversation context")
            return True
            
        try:
            logger.info("Attempting to load resume analysis from conversation context")
            
            # Check the conversation manager
            messages = self.conversation_manager.get_messages()
            
            # Check if we already have this analysis in the conversation
            analysis_exists = False
            resume_analysis = None
            
            for message in messages:
                if message.get('role') == 'system' and 'RESUME ANALYSIS' in message.get('content', ''):
                    analysis_exists = True
                    resume_analysis = message.get('content', '')
                    logger.info(f"Resume analysis already exists in conversation ({len(resume_analysis)} chars)")
                    break
            
            if analysis_exists and resume_analysis:
                self.resume_analysis_loaded = True
                self.resume_metadata["analyzed"] = True
                return True
                
            # Try the conversation backup files as fallback
            backup_dir = os.path.join(os.getcwd(), "conversation_backups")
            backup_file = os.path.join(backup_dir, f"conversation_{self.ctx.room.name}.json")
            
            if os.path.exists(backup_file):
                try:
                    logger.info(f"Checking conversation backup at {backup_file}")
                    with open(backup_file, "r") as f:
                        backup_messages = json.load(f)
                        
                    # Find resume analysis in messages
                    for message in reversed(backup_messages):
                        if (message.get('role') == 'system' and 
                            'RESUME ANALYSIS' in message.get('content', '')):
                            resume_analysis = message['content']
                            logger.info(f"Found resume analysis in backup file ({len(resume_analysis)} chars)")
                            
                            # Add to conversation if not already there
                            self.conversation_manager.add_message({
                                "role": "system",
                                "content": resume_analysis
                            })
                            
                            self.resume_analysis_loaded = True
                            self.resume_metadata["analyzed"] = True
                            return True
                except Exception as backup_error:
                    logger.error(f"Error reading conversation backup: {str(backup_error)}")
                    logger.error(traceback.format_exc())
            
            logger.warning("No resume analysis found in conversation context")
            return False
                
        except Exception as e:
            logger.error(f"Error ensuring resume analysis is loaded: {str(e)}")
            logger.error(traceback.format_exc())
            return False
    
    async def on_participant_update(self, ctx: JobContext, participant: rtc.RemoteParticipant):
        """Handle participant metadata updates (like when email or resume is submitted)"""
        try:
            if not participant.metadata:
                return
                
            data = json.loads(participant.metadata)
            logger.info(f"Participant update received: {participant.identity}, metadata: {data}")
            
            # Handle email submission
            if 'userEmail' in data:
                email = data['userEmail']
                logger.info(f"Email received from participant: {participant.identity}")
                
                # Store email using supabase client
                await self.assistant_fnc.supabase.store_email_for_session(ctx.room.name, email)
                
                # Cache the email in assistant_fnc
                self.assistant_fnc._session_emails[ctx.room.name] = email
                
                # Update conversation manager
                self.conversation_manager.add_message({
                    "role": "system",
                    "content": f"User has provided email: {email}"
                })
                
                # Request resume after email is provided
                await self.request_resume(ctx)
            
            # Handle resume upload directly from metadata (when byte stream fails or was not received)
            if 'resumeUploaded' in data and data['resumeUploaded']:
                logger.info(f"🔍 IMPORTANT: Resume upload detected from metadata for participant: {participant.identity}")
                resumeName = data.get('resumeName', 'Unknown Resume')
                resumeSize = data.get('resumeSize', 'unknown size')
                resumeType = data.get('resumeType', 'unknown type')
                logger.info(f"🔍 Resume metadata details: name={resumeName}, size={resumeSize}, type={resumeType}")
                
                # Update our internal metadata tracking
                self.resume_metadata = {
                    "name": resumeName,
                    "type": resumeType,
                    "size": resumeSize,
                    "analyzed": data.get('resumeAnalyzed', False)
                }
                logger.info(f"Updated internal resume metadata tracking: {self.resume_metadata}")
                
                # Add a system message to the conversation manager if it doesn't already exist
                self.conversation_manager.add_message({
                    "role": "system",
                    "content": f"Resume received: {resumeName}. Please provide resume feedback based on what you can see in the file."
                })
                
                # Update participant metadata only if we have a RemoteParticipant object
                if isinstance(participant, RemoteParticipant):
                    logger.info(f"Updating participant metadata for {participant.identity}")
                    try:
                        current_metadata = json.loads(participant.metadata or '{}')
                        logger.info(f"Current metadata: {current_metadata}")
                        
                        current_metadata.update({
                            'resumeUploaded': True,
                            'resumeName': resumeName,
                            'resumeSize': resumeSize,
                            'resumeType': resumeType
                        })
                        
                        # Set the updated metadata using set_metadata instead of update_metadata
                        logger.info(f"Setting new metadata: {current_metadata}")
                        await participant.set_attributes(json.dumps(current_metadata))
                    except Exception as metadata_error:
                        logger.error(f"Error updating participant metadata: {str(metadata_error)}")
                        logger.error(traceback.format_exc())
                else:
                    logger.info(f"Skipping metadata update for participant {participant.identity} (not a RemoteParticipant)")
                
                # Trigger resume analysis check
                await self.ensure_resume_analysis_loaded()
                
                # Manually trigger the LLM to respond about the resume analysis if needed
                try:
                    # Check if we need to generate a response about the resume
                    if self.resume_metadata["analyzed"]:
                        # Create a clear prompt for reference
                        response_prompt = f"Based on the resume analysis, provide personalized feedback for {resumeName}"
                        logger.info(f"Resume is analyzed, triggering response about it: {response_prompt}")
                        
                        # Trigger resume processing via the tool
                        response = await self.assistant_fnc.process_resume_content(resume_name=resumeName)
                        
                        # If we have a reference to the agent session, use it to respond
                        if self._agent_session_ref and response:
                            logger.info(f"Delivering resume analysis via agent session (length: {len(response)})")
                            await self._agent_session_ref.say(response)
                    else:
                        logger.info("Resume uploaded but not yet analyzed. Waiting for analysis to complete.")
                except Exception as e:
                    logger.error(f"Error handling resume response: {str(e)}")
                    logger.error(traceback.format_exc())
        except Exception as e:
            logger.error(f"Error handling participant update: {str(e)}")
            logger.error(traceback.format_exc())
    
    async def request_resume(self, ctx: JobContext):
        """Request resume upload from user"""
        try:
            message = "I'll need your resume to provide personalized job recommendations. Please upload it using the form that just appeared."
            await ctx.room.local_participant.publish_data(message.encode(), topic="agent_message")
            
            # Update participant metadata to show resume upload form
            await ctx.room.local_participant.update_metadata({
                "show_resume_upload": True
            })
        except Exception as e:
            logger.error(f"Error requesting resume: {str(e)}")
            logger.error(traceback.format_exc())

    
    # Override llm_node to intercept tool calls and results
    async def llm_node(
        self,
        chat_ctx: llm.ChatContext,
        tools: list[llm.FunctionTool],
        model_settings: ModelSettings,
    ) -> AsyncIterable[llm.ChatChunk]:
        # First make sure any resume analysis is loaded
        await self.ensure_resume_analysis_loaded()
        
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

    async def check_raw_resumes(self):
        """This method is kept for compatibility but no longer processes raw resume files"""
        logger.info("check_raw_resumes called but no longer processes raw files as requested")
        return await self.ensure_resume_analysis_loaded()


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

        # Instantiate the custom agent, passing the conversation_manager and ctx
        agent = PrepzoAgent(ctx=ctx, room_name=ctx.room.name, conversation_manager=conversation_manager)
        
        # Check for resume analysis in conversation
        try:
            # Load any existing resume analysis from conversation context
            await agent.ensure_resume_analysis_loaded()
        except Exception as setup_error:
            logger.error(f"Error checking for resume analysis: {str(setup_error)}")
            logger.error(traceback.format_exc())

        @ctx.room.on("participant_metadata_changed")
        def on_metadata_changed(participant: rtc.RemoteParticipant):
            # Log metadata changes
            try:
                logger.info(f"🔍 DEBUG: Participant metadata changed for {participant.identity}")
                if participant.metadata:
                    logger.info(f"🔍 DEBUG: New metadata content: {participant.metadata}")
                    metadata_obj = json.loads(participant.metadata)
                    logger.info(f"🔍 DEBUG: Parsed metadata: {json.dumps(metadata_obj, indent=2)}")
                    
                    # Check if this contains resume info
                    if 'resumeUploaded' in metadata_obj:
                        logger.info(f"🔍 DEBUG: RESUME INFO DETECTED in metadata!")
                    
                    # Check if agent state changed to resume_analyzed
                    if metadata_obj.get('agent_state') == "resume_analyzed":
                        logger.info("Agent state changed to resume_analyzed, ensuring response is delivered")
                        
                        # Use an async task to deliver the response
                        async def deliver_resume_analysis():
                            try:
                                response = await agent.assistant_fnc.process_resume_content()
                                if response:
                                    logger.info(f"Delivering resume analysis response via session.say() (length: {len(response)})")
                                    await session.say(response)
                            except Exception as e:
                                logger.error(f"Error delivering resume analysis: {str(e)}")
                                logger.error(traceback.format_exc())
                        
                        asyncio.create_task(deliver_resume_analysis())
                else:
                    logger.info("🔍 DEBUG: Metadata is empty")
            except Exception as e:
                logger.error(f"Error logging metadata: {str(e)}")
                
            # Use async task to handle the update
            asyncio.create_task(agent.on_participant_update(ctx, participant))

        # Set up resume upload handler
        async def handle_resume_upload(reader: ByteStreamReader, participant_info: str | RemoteParticipant, session: AgentSession):
            try:
                # Get participant identity safely
                participant_id = participant_info.identity if hasattr(participant_info, 'identity') else str(participant_info)
                logger.info(f"✨✨✨ RESUME UPLOAD STARTED from {participant_id} ✨✨✨")
                
                # Get metadata from reader.info
                file_name = getattr(reader.info, 'name', 'resume.pdf')
                file_type = getattr(reader.info, 'mime_type', 'application/pdf')
                file_size = getattr(reader.info, 'size', 0)
                logger.info(f"📄 Resume metadata from info: name={file_name}, type={file_type}, size={file_size}")
                
                # Read the file data
                logger.info("Starting to read resume file chunks...")
                chunks = []
                chunk_count = 0
                try:
                    async for chunk in reader:
                        chunks.append(chunk)
                        chunk_count += 1
                        if len(chunks) % 10 == 0:
                            total_size = sum(len(chunk) for chunk in chunks)
                            logger.info(f"Read {chunk_count} chunks, {total_size/1024:.1f}KB so far...")
                    
                    logger.info(f"Finished reading chunks: {chunk_count} chunks received")
                except Exception as chunk_error:
                    logger.error(f"Error reading chunks: {str(chunk_error)}")
                    logger.error(traceback.format_exc())
                    error_msg = "Error while reading your resume file. Please try uploading again."
                    await ctx.room.local_participant.publish_data(error_msg.encode(), topic="agent_message")
                    return
                
                file_data = b''.join(chunks)
                if not file_data:
                    logger.error("No file data received")
                    error_msg = "No file data received. Please try uploading your resume again."
                    await ctx.room.local_participant.publish_data(error_msg.encode(), topic="agent_message")
                    return
                
                logger.info(f"✅ Resume fully received: {len(file_data)} bytes")

                # Persist raw PDF in conversation history for later access
                try:
                    raw_b64 = base64.b64encode(file_data).decode('utf-8')
                    # Keep last raw resume PDF in memory for API retrieval
                    agent.assistant_fnc._last_resume_raw = raw_b64
                    logger.info("Stored raw resume PDF in assistant_fnc._last_resume_raw")
                except Exception as persist_error:
                    logger.error(f"Error storing raw PDF in conversation history: {persist_error}")
                
                # Process with Gemini
                try:
                    gemini_api_key = os.environ.get("GEMINI_API_KEY")
                    if not gemini_api_key:
                        logger.error("GEMINI_API_KEY not found in environment variables")
                        error_msg = "I'm having trouble analyzing your resume. Let me ask you about your background instead."
                        await ctx.room.local_participant.publish_data(error_msg.encode(), topic="agent_message")
                        return

                    genai.configure(api_key=gemini_api_key)
                    model = GenerativeModel('gemini-2.0-flash')
                    
                    analysis_prompt = """
                    You are a professional resume analyzer. Please analyze this resume in detail and provide:
                    1. A detailed summary of the person's background, skills, and experience
                    2. Key strengths and standout points identified in the resume
                    3. Specific areas for improvement or suggestions to enhance the resume
                    4. Job roles and positions this person would be most suited for based on their experience
                    5. Any notable achievements or certifications
                    
                    Please be specific and detailed in your analysis, citing actual information from the resume.
                    Format your response in a clear, structured way.
                    """
                    
                    logger.info("Requesting resume analysis from Gemini...")
                    try:
                        # Prepare the request with the file data in base64
                        base64_data = base64.b64encode(file_data).decode('utf-8')
                        logger.info(f"Base64 data length: {len(base64_data)} characters")
                        
                        response = await model.generate_content_async(
                            [
                                {"text": analysis_prompt},
                                {
                                    "inline_data": {
                                        "mime_type": file_type,
                                        "data": base64_data
                                    }
                                }
                            ],
                            generation_config={
                                "temperature": 0.2,
                                "candidate_count": 1,
                                "max_output_tokens": 4096,
                                "top_p": 0.8,
                                "top_k": 40
                            }
                        )
                        
                        if response and response.text:
                            resume_analysis = response.text
                            logger.info(f"Resume analysis complete (length: {len(resume_analysis)} chars)")
                            
                            # Store analysis in conversation and in memory for direct access
                            conversation_manager.add_message({
                                "role": "system",
                                "content": f"RESUME ANALYSIS for {file_name}:\n\n{resume_analysis}"
                            })
                            # Keep last analysis in AssistantFnc for direct retrieval
                            agent.assistant_fnc._last_resume_analysis = resume_analysis
                            
                            # Force immediate save to database
                            try:
                                await conversation_manager._save_conversation()
                                logger.info("Successfully saved resume analysis to database")
                            except Exception as save_error:
                                logger.error(f"Error force-saving conversation: {str(save_error)}")
                                logger.error(traceback.format_exc())
                            
                            # Add a user message to trigger the agent's response
                            conversation_manager.add_message({
                                "role": "user",
                                "content": "Could you provide feedback on my resume and suggest potential career opportunities based on my background?"
                            })
                            
                            # Update participant metadata
                            if isinstance(participant_info, RemoteParticipant):
                                logger.info(f"Updating participant metadata for {participant_id}")
                                try:
                                    current_metadata = json.loads(participant_info.metadata or '{}')
                                    logger.info(f"Current metadata: {current_metadata}")
                                    
                                    current_metadata.update({
                                        'resumeUploaded': True,
                                        'resumeName': file_name,
                                        'resumeSize': len(file_data),
                                        'resumeType': file_type,
                                        'resumeAnalyzed': True  # Add flag to indicate analysis is complete
                                    })
                                    
                                    logger.info(f"Setting new metadata: {current_metadata}")
                                    await participant_info.set_metadata(json.dumps(current_metadata))
                                    
                                    # Also update local participant metadata to ensure state consistency
                                    await ctx.room.local_participant.set_metadata(json.dumps({
                                        'resumeAnalyzed': True,
                                        'resumeName': file_name,
                                        'resumeAnalysisLength': len(resume_analysis)
                                    }))
                                except Exception as metadata_error:
                                    logger.error(f"Error updating participant metadata: {str(metadata_error)}")
                                    logger.error(traceback.format_exc())
                            else:
                                logger.info(f"Skipping metadata update for participant {participant_id} (not a RemoteParticipant)")
                            
                            # Update agent state to trigger response
                            logger.info("Setting agent state to 'resume_analyzed'")
                            await agent.assistant_fnc.set_agent_state("resume_analyzed")
                            
                            # Send a message directly to the user indicating analysis is complete
                            notify_msg = f"I've analyzed your resume '{file_name}' and I'll now provide feedback and recommendations."
                            await ctx.room.local_participant.publish_data(notify_msg.encode(), topic="agent_message")
                            
                            # Trigger the resume processing tool
                            try:
                                logger.info("Triggering resume processing tool")
                                # Go through assistant_fnc to ensure the response reaches the conversation
                                response = await agent.assistant_fnc.process_resume_content(resume_name=file_name)
                                if response:
                                    logger.info(f"Tool returned response of length: {len(response)}")
                                    # Publish data message for debugging
                                    await ctx.room.local_participant.publish_data(response.encode(), topic="agent_message")
                                    
                                    # IMPORTANT: Also say the response using the session to ensure it's delivered as speech
                                    if session:
                                        logger.info("Delivering resume analysis as speech via session.say()")
                                        await session.say(response)
                                else:
                                    logger.error("Resume processing tool returned empty response")
                                    fallback_msg = "I've analyzed your resume and I'm preparing my feedback. What specific aspects would you like me to focus on?"
                                    await ctx.room.local_participant.publish_data(fallback_msg.encode(), topic="agent_message")
                                    await session.say(fallback_msg)
                            except Exception as tool_error:
                                logger.error(f"Error triggering resume processing tool: {str(tool_error)}")
                                logger.error(traceback.format_exc())
                                
                                # Fallback: send the analysis directly if tool fails
                                fallback_msg = f"I've analyzed your resume and here's my feedback:\n\n{resume_analysis[:500]}...\n\nWould you like me to elaborate on any particular aspect?"
                                await ctx.room.local_participant.publish_data(fallback_msg.encode(), topic="agent_message")
                        else:
                            logger.warning("No text content in Gemini response")
                            error_msg = "I apologize, but I was unable to generate a detailed analysis of your resume. Would you mind telling me about your background and experience?"
                            await ctx.room.local_participant.publish_data(error_msg.encode(), topic="agent_message")
                    except Exception as analysis_error:
                        logger.error(f"Error generating content with Gemini: {str(analysis_error)}")
                        logger.error(traceback.format_exc())
                        error_msg = "I encountered an issue analyzing your resume in detail. Let me ask you about your background instead."
                        await ctx.room.local_participant.publish_data(error_msg.encode(), topic="agent_message")
                except Exception as e:
                    logger.error(f"Error in resume handling: {str(e)}")
                    logger.error(traceback.format_exc())
                    error_msg = "Sorry, there was an error processing your resume. Please try again or tell me about your background directly."
                    await ctx.room.local_participant.publish_data(error_msg.encode(), topic="agent_message")
            except Exception as e:
                logger.error(f"Error in resume upload handler: {str(e)}")
                logger.error(traceback.format_exc())
                error_msg = "Sorry, there was an error processing your resume. Please try again."
                await ctx.room.local_participant.publish_data(error_msg.encode(), topic="agent_message")

        # Handler for resume info stream
        async def handle_resume_info(reader: ByteStreamReader, info: RemoteParticipant):
            try:
                logger.info(f"Resume info received from {info.identity}")
                data = await reader.read_all()
                if data:
                    logger.info(f"Resume info data: {data[:100]}...")
            except Exception as e:
                logger.error(f"Error handling resume info: {str(e)}")
                logger.error(traceback.format_exc())
                
        # Register handlers for various potential resume upload topics to ensure we catch it
        logger.info("Registering byte stream handlers for resume uploads")
        
        # The primary handler for the exact topic used in the React component
        logger.info("Registering primary handler for 'resume_data' topic")
        ctx.room.register_byte_stream_handler("resume_data", lambda reader, info: asyncio.create_task(handle_resume_upload(reader, info, session)))
        logger.info("✅ 'resume_data' handler registered successfully")
        
        # Added debug hook to detect any byte stream on any topic
        async def debug_any_byte_stream(reader: ByteStreamReader, participant_info: RemoteParticipant):
            try:
                logger.info(f"🔍 DEBUG: RECEIVED BYTE STREAM on topic: {reader.info.topic} from {participant_info.identity}")
                logger.info(f"🔍 DEBUG: Stream info: id={reader.info.id}, name={getattr(reader.info, 'name', 'unknown')}")
                
                # Get more details about the stream
                try:
                    metadata = {}
                    if hasattr(reader.info, 'metadata') and reader.info.metadata:
                        metadata = json.loads(reader.info.metadata)
                    logger.info(f"🔍 DEBUG: Stream metadata: {metadata}")
                except Exception as metadata_error:
                    logger.error(f"Error parsing stream metadata: {str(metadata_error)}")
                    
                # Log the size if available
                if hasattr(reader.info, 'size'):
                    logger.info(f"🔍 DEBUG: Stream size: {reader.info.size} bytes")
            except Exception as e:
                logger.error(f"Error in debug byte stream handler: {str(e)}")
                logger.error(traceback.format_exc())
        
        # Register a debug handler that will catch any byte stream on any topic
        ctx.room.register_byte_stream_handler("*", lambda reader, info: asyncio.create_task(debug_any_byte_stream(reader, info)))
        logger.info("✅ Wildcard byte stream debug handler registered successfully")
        
        # Register backup handlers for other potential topics as a fallback
        backup_topics = {
            "resume": handle_resume_upload,
            "resume_upload": handle_resume_upload,
            "resumeData": handle_resume_upload,
            "file_upload": handle_resume_upload,
        }
        
        for topic, handler in backup_topics.items():
            logger.info(f"Registering backup handler for topic: {topic}")
            ctx.room.register_byte_stream_handler(topic, lambda reader, info, h=handler: asyncio.create_task(h(reader, info, session)))
            logger.info(f"✅ Backup handler for '{topic}' registered successfully")
            
        # Register info handler
        ctx.room.register_byte_stream_handler("resume_info", lambda reader, info: asyncio.create_task(handle_resume_info(reader, info)))
        logger.info("✅ 'resume_info' handler registered successfully")

        session = AgentSession(
            vad=vad_plugin,
            stt=stt_plugin,
            llm=llm_plugin,
            tts=tts_plugin,
        )
        logger.info("AgentSession created")

        # Store session reference in agent
        agent._agent_session_ref = session
        logger.info("Stored session reference in agent")

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
