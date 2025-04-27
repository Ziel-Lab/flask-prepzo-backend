from livekit.agents import llm, function_tool
from livekit.agents.llm import ToolContext
from typing import Annotated, Optional, Dict, Literal
import logging, os, requests
from knowledgebase import pinecone_search
from dotenv import load_dotenv
from openai import OpenAI
import json
from supabase_client import SupabaseEmailClient
import asyncio
from livekit.rtc import RemoteParticipant
import traceback
from conversation_manager import ConversationManager


logger = logging.getLogger("user-data")
logger.setLevel(logging.INFO)

load_dotenv(dotenv_path=".env.local")

class PerplexityService:
    def __init__(self, client: OpenAI):
        """Initializes the service with the configured OpenAI client."""
        self.client = client

    async def web_search(self, query: str, model_name: str = "sonar") -> str:
        """
        Performs a general web search using Perplexity and returns the direct answer.
        Accepts a potentially structured query formulated by the agent.
        """
        try:
            messages = [
                {"role": "system", "content": "You are a helpful assistant providing concise answers based on the user's detailed request."},
                {"role": "user", "content": query},
            ]
            logger.info(f"Sending web search request to Perplexity model: {model_name} with query:\n{query}")
            response = self.client.chat.completions.create(
                model=model_name,
                messages=messages,
            )

            if response.choices and response.choices[0].message:
                answer = response.choices[0].message.content.strip()
                logger.info("Perplexity web search successful.")
                return answer
            else:
                 logger.error("Perplexity API returned an unexpected response structure for web search.")
                 return "Sorry, I couldn't get an answer due to an API issue."

        except Exception as e:
            logger.error(f"Perplexity web search error: {str(e)}")
            return f"Sorry, an error occurred during the web search: {str(e)}"


class AssistantFnc:
    def __init__(self, ctx: ToolContext, room_name: str):
        perplexity_api_key = os.getenv("PERPLEXITY_API_KEY")
        
        self.ctx = ctx
        self.room = ctx.room
        self.local = ctx.room.local_participant
        self.room_name = ctx.room.name

        self.room_name = room_name
        self.supabase = SupabaseEmailClient()
        self._session_emails = {} # Cache for session emails

        # Initialize Perplexity client
        if not perplexity_api_key:
            raise ValueError("Missing PERPLEXITY_API_KEY environment variable")
        self.perplexity_client = OpenAI(api_key=perplexity_api_key, base_url="https://api.perplexity.ai")

        # Initialize the consolidated Perplexity service
        self.perplexity_service = PerplexityService(client=self.perplexity_client)

        # Agent state attribute
        self.agent_state = None
        logger.info(f"AssistantFnc helper class initialized for room: {room_name}")

    def _clean_text(self, text: str) -> str:
        """Sanitize text for LLM consumption"""
        return text.replace('\n', ' ').strip()

    @function_tool()
    async def request_resume(self) -> str:
        """Signal frontend to show resume upload form and provide user instructions"""
        try:
            await self.set_agent_state("resume_upload_requested")
            return "Please upload your resume using the form that just appeared below."
        except Exception as e:
            logger.error(f"Failed to request resume: {str(e)}")
            # Fallback instruction if state setting fails
            return "Please upload your resume so I can provide personalized recommendations."


    @function_tool()
    async def get_user_email(self) -> str:
        """Returns stored email or empty string"""
        try:
            # First check local cache
            roomName = self.room_name
            logger.info(f"Checking email for room: {roomName}")
            if roomName in self._session_emails:
                return self._session_emails[roomName]
            
            # Query Supabase
            email = await self.supabase.get_email_for_session(roomName)
            if email:
                self._session_emails[roomName] = email
                return email
            return "email not found"
        except Exception as e:
            logger.error(f"Email lookup failed: {str(e)}")
            return ""

    @function_tool()
    async def web_search(
        self,
        query: Annotated[str, "The structured query string formulated according to system instructions."]
    ) -> str:
        """
        Uses the Perplexity API via PerplexityService to get answers for general web queries or job searches.
        Relies on the agent formulating a detailed, structured query.
        """
        try:
            logger.info("Performing Perplexity web search with structured query.")
            # Call the consolidated service method
            result = await self.perplexity_service.web_search(query)
            return result
        except Exception as e:
            logger.error(f"Web search function error: {str(e)}")
            return "Unable to access current information due to an internal error."
 
    
    @function_tool()
    async def request_email(self) -> str:
        """Signal frontend to show email form and provide user instructions"""
        try:
            await self.set_agent_state("email_requested")
            return "Please provide your email address in the form that just appeared below."
        except Exception as e:
            logger.error(f"Failed to request email: {str(e)}")
            # Fallback instruction if state setting fails
            return "Please provide your email address so I can send you the information."
        
    @function_tool()
    async def set_agent_state(self, state: str) -> str:
        """
        Update the agent state marker. The frontend listens for changes to this state.
        
        Parameters:
          - state: A string representing the new state (e.g., "email_requested", "JOB_RESULTS_MARKDOWN:::[...]").
        
        Returns:
          A confirmation message or raises an error.
        """
        try:
            self.agent_state = state 
            logger.info(f"Agent state set to: {state[:50]}..." if len(state) > 50 else f"Agent state set to: {state}")
            
            # Create metadata payload
            metadata = json.loads(self.local.metadata or '{}')
            metadata["agent_state"] = state
            
            # Set the metadata on the local participant
            await self.local.set_metadata(json.dumps(metadata))
            logger.info(f"Agent metadata updated with new state: {state}")
            
            return f"Agent state updated to {state}"
        except Exception as e:
            logger.error(f"Error setting agent state: {str(e)}")
            # Re-raise or handle as appropriate for the framework
            raise # Or return a specific error message



    @function_tool()
    async def search_knowledge_base(
        self,
        query: Annotated[str, "The search query string for the internal knowledge base"]
    ) -> str:
        """
        Wrapper method to call the imported pinecone_search function.
        Performs a similarity search across all relevant namespaces in the Pinecone vector database 
        and returns relevant text snippets.
        """
        try:
            logger.info(f"Searching knowledge base with query: {query}")
            # Call the imported function
            results = await pinecone_search(query=query)
            logger.info(f"Knowledge base search returned {len(results)} characters.")
            return results
        except Exception as e:
            logger.error(f"Knowledge base search failed: {str(e)}")
            return "I encountered an error trying to search the knowledge base."

    async def on_participant_update(self, participant: RemoteParticipant):
        """Handle participant metadata updates (like when email is submitted)"""
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
                await self.supabase.store_email_for_session(self.room_name, email)
                
                # Cache the email in assistant_fnc
                self._session_emails[self.room_name] = email
                
            # Handle resume upload metadata
            if 'resumeUploaded' in data and data['resumeUploaded']:
                logger.info(f"Resume upload detected in metadata from participant: {participant.identity}")
                logger.info(f"Resume metadata: name={data.get('resumeName', 'unknown')}, size={data.get('resumeSize', 'unknown')}")
                
                # Set agent state to acknowledge resume upload
                await self.set_agent_state("resume_received")
                
                # The actual resume content should be coming through the byte stream
                # This metadata handling is just to acknowledge receipt
                
        except Exception as e:
            logger.error(f"Error handling participant update: {str(e)}")

    @function_tool()
    async def process_resume_content(self, resume_name: str = "") -> str:
        """Process resume content and provide recommendations based on it."""
        try:
            logger.info(f"Processing resume content for {resume_name}")
            
            # 0. If we have a cached analysis from Gemini, use it directly
            if hasattr(self, '_last_resume_analysis') and self._last_resume_analysis:
                analysis = self._last_resume_analysis
                logger.info(f"Using cached resume analysis ({len(analysis)} chars)")
                return f"I've analyzed your resume {resume_name or 'the uploaded file'} in detail. Here's my feedback and suggestions:\n\n{analysis}"  
            
            # Try multiple approaches to get the resume analysis
            resume_analysis = None
            
            # 1. Try the conversation manager directly
            if hasattr(self.ctx, 'conversation_manager'):
                try:
                    logger.info("Trying to retrieve analysis from conversation manager")
                    messages = await self.ctx.conversation_manager.get_messages_async()
                    
                    if messages:
                        logger.info(f"Found {len(messages)} messages in conversation manager")
                        # Find resume analysis in messages
                        for message in reversed(messages):
                            if (message.get('role') == 'system' and 
                                'RESUME ANALYSIS' in message.get('content', '')):
                                resume_analysis = message['content']
                                logger.info(f"Found resume analysis in conversation manager ({len(resume_analysis)} chars)")
                                break
                except Exception as cm_error:
                    logger.error(f"Error accessing conversation manager: {str(cm_error)}")
                    logger.error(traceback.format_exc())
            
            # 2. Try the conversation backup files if conversation manager failed
            if not resume_analysis:
                backup_dir = os.path.join(os.getcwd(), "conversation_backups")
                backup_file = os.path.join(backup_dir, f"conversation_{self.room_name}.json")
                
                if os.path.exists(backup_file):
                    try:
                        logger.info(f"Found conversation backup at {backup_file}")
                        with open(backup_file, "r") as f:
                            messages = json.load(f)
                            
                        # Find resume analysis in messages
                        for message in reversed(messages):
                            if (message.get('role') == 'system' and 
                                'RESUME ANALYSIS' in message.get('content', '')):
                                resume_analysis = message['content']
                                logger.info(f"Found resume analysis in backup file ({len(resume_analysis)} chars)")
                                break
                    except Exception as backup_error:
                        logger.error(f"Error reading conversation backup: {str(backup_error)}")
                        logger.error(traceback.format_exc())
            
            # 3. Try database approach
            if not resume_analysis:
                try:
                    from conversation_manager import ConversationManager, supabase
                    
                    # Try to directly query the database
                    logger.info(f"Querying database for resume analysis for room {self.room_name}")
                    result = None
                    
                    try:
                        result = await supabase.table("conversations").select("conversation").eq("session_id", self.room_name).limit(1).execute()
                    except Exception as query_error:
                        logger.error(f"Error querying database: {str(query_error)}")
                        logger.error(traceback.format_exc())
                    
                    if result and result.data and len(result.data) > 0:
                        logger.info(f"Found conversation in database")
                        conversation_data = result.data[0]["conversation"]
                        
                        # Parse conversation data
                        messages = []
                        if isinstance(conversation_data, str):
                            messages = json.loads(conversation_data)
                        else:
                            messages = conversation_data
                        
                        logger.info(f"Found {len(messages)} messages in conversation history")
                        
                        # Find resume analysis in messages
                        for message in reversed(messages):
                            if (message.get('role') == 'system' and 
                                'RESUME ANALYSIS' in message.get('content', '')):
                                resume_analysis = message['content']
                                logger.info(f"Found resume analysis in conversation history ({len(resume_analysis)} chars)")
                                break
                except Exception as db_error:
                    logger.error(f"Error retrieving conversation from database: {str(db_error)}")
                    logger.error(traceback.format_exc())
            
            # If we found an analysis, format a response
            if resume_analysis:
                # Format a response
                message = (
                    f"I've analyzed your resume {resume_name or 'you uploaded'} in detail. "
                    "Here's my feedback and personalized recommendations based on your profile:\n\n"
                )
                
                # Extract the actual analysis from the system message if needed
                if 'RESUME ANALYSIS' in resume_analysis:
                    analysis_parts = resume_analysis.split('RESUME ANALYSIS')
                    if len(analysis_parts) > 1:
                        parts = analysis_parts[1].split(':', 1)
                        if len(parts) > 1:
                            clean_analysis = parts[1].strip()
                            message += clean_analysis
                        else:
                            message += analysis_parts[1].strip()
                    else:
                        message += resume_analysis
                else:
                    message += resume_analysis
                
                message += "\n\nWould you like me to elaborate on any specific aspect or discuss potential career opportunities based on your background?"
                
                # Make sure it's in the conversation manager
                if hasattr(self.ctx, 'conversation_manager'):
                    try:
                        current_messages = await self.ctx.conversation_manager.get_messages_async()
                        # Check if we already have a response for this
                        has_response = False
                        for msg in current_messages:
                            if msg.get('role') == 'assistant' and "I've analyzed your resume" in msg.get('content', ''):
                                has_response = True
                                break
                                
                        if not has_response:
                            # Add the assistant response to the conversation
                            self.ctx.conversation_manager.add_message({
                                "role": "assistant",
                                "content": message
                            })
                            logger.info("Added resume feedback response to conversation")
                    except Exception as add_error:
                        logger.error(f"Error adding response to conversation: {str(add_error)}")
                        
                return message
            
            # Complete fallback message if all else fails
            logger.warning("No resume analysis found in any storage")
            return (
                f"I see your resume {resume_name or ''} has been uploaded, but I'm having trouble accessing the detailed analysis. "
                "I can still help you with job recommendations. Could you tell me about your key skills and the types of roles you're interested in?"
            )
            
        except Exception as e:
            logger.error(f"Error processing resume content: {str(e)}")
            logger.error(traceback.format_exc())
            return (
                "I encountered an issue while processing your resume. "
                "Could you tell me about your background and the types of roles you're interested in?"
            )

    @function_tool()
    async def fetch_resume_raw(self) -> str:
        """Return the raw resume PDF content in base64 encoding."""
        try:
            messages = await self.ctx.conversation_manager.get_messages_async()
            for msg in messages:
                metadata = msg.get("metadata", {})
                if metadata.get("type") == "resume_raw":
                    return msg.get("content", "")
            return ""  # No raw resume found
        except Exception as e:
            logger.error(f"Error fetching raw resume: {e}")
            return ""

    @function_tool()
    async def fetch_resume_analysis(self) -> str:
        """Return the text of the resume analysis generated by Gemini."""
        try:
            messages = await self.ctx.conversation_manager.get_messages_async()
            for msg in reversed(messages):
                if msg.get("role") == "system" and msg.get("content", "").startswith("RESUME ANALYSIS"):
                    return msg.get("content", "")
            return ""  # No analysis found
        except Exception as e:
            logger.error(f"Error fetching resume analysis: {e}")
            return ""





