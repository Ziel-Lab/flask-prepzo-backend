from livekit.agents import llm
from livekit.agents import function_tool
from typing import Annotated, Optional, Dict, Literal, TYPE_CHECKING
import logging, os, requests
import asyncio
import pathlib
import aiofiles
from io import BytesIO
from knowledgebase import pinecone_search
from dotenv import load_dotenv
from openai import OpenAI
import json
from supabase_client import SupabaseEmailClient
from conversation_manager import ConversationManager
import traceback
import google.generativeai as genai
from google.cloud import documentai_v1 as documentai
import shutil # Added for directory removal



logger = logging.getLogger("user-data")
logger.setLevel(logging.INFO)

load_dotenv(dotenv_path=".env.local")

UPLOAD_FOLDER = pathlib.Path('./uploads') # Make sure this matches server.py

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
    def __init__(self, room_name: str, conversation_manager: ConversationManager):
        perplexity_api_key = os.getenv("PERPLEXITY_API_KEY")
        google_api_key = os.getenv("GOOGLE_API_KEY") # Get Google API Key for Gemini (if still used)
        # Get Document AI config
        self.docai_project_id = os.getenv("GOOGLE_PROJECT_ID") # Use the variable name user specified
        self.docai_location = os.getenv("DOCAI_LOCATION")
        self.docai_summarizer_processor_id = os.getenv("DOCAI_SUMMARIZER_PROCESSOR_ID")

        self.room_name = room_name
        self.supabase = SupabaseEmailClient()
        self._session_emails = {} # Cache for session emails
        self.conversation_manager = conversation_manager # Store the manager

        # Initialize Perplexity client
        if not perplexity_api_key:
            # Changed from raise ValueError to log warning for flexibility
            logger.warning("Missing PERPLEXITY_API_KEY environment variable. Web search may fail.")
            self.perplexity_client = None
            self.perplexity_service = None
        else:
            self.perplexity_client = OpenAI(api_key=perplexity_api_key, base_url="https://api.perplexity.ai")
            self.perplexity_service = PerplexityService(client=self.perplexity_client)

        # Initialize Google Generative AI client (Gemini) - Keep for now if needed elsewhere
        self.genai_client = None
        if genai and google_api_key:
            try:
                genai.configure(api_key=google_api_key)
                self.genai_client = genai # Store the configured module
                logger.info("Google Generative AI client configured successfully.")
            except Exception as e:
                 logger.error(f"Failed to configure Google Generative AI client: {e}")
        elif not genai:
            logger.warning("Google Generative AI SDK not installed. Gemini features disabled.")
        else: # genai exists but no key
             logger.warning("Missing GOOGLE_API_KEY environment variable. Gemini features disabled.")

        # Initialize Document AI client
        self.docai_client = None
        self.is_docai_summarizer_configured = False
        if documentai and self.docai_project_id and self.docai_location and self.docai_summarizer_processor_id:
            try:
                opts = {"api_endpoint": f"{self.docai_location}-documentai.googleapis.com"}
                self.docai_client = documentai.DocumentProcessorServiceClient(client_options=opts)
                self.is_docai_summarizer_configured = True
                logger.info(f"Document AI Summarizer client configured for project {self.docai_project_id}, location {self.docai_location}.")
            except Exception as e:
                 logger.error(f"Failed to configure Document AI client: {e}. Check credentials and config.")
        else:
            missing_config = []
            if not documentai: missing_config.append("google-cloud-documentai library")
            if not self.docai_project_id: missing_config.append("GOOGLE_PROJECT_ID env var")
            if not self.docai_location: missing_config.append("DOCAI_LOCATION env var")
            if not self.docai_summarizer_processor_id: missing_config.append("DOCAI_SUMMARIZER_PROCESSOR_ID env var")
            logger.warning(f"Document AI Summarizer features disabled. Missing configuration: {', '.join(missing_config)}")

        # Agent state attribute
        self.agent_state = None
        logger.info(f"AssistantFnc helper class initialized for room: {room_name}")

    def _clean_text(self, text: str) -> str:
        """Sanitize text for LLM consumption"""
        # Also handle potential None input from parsing
        if text is None:
            return ""
        return text.replace('\n', ' ').strip()

    @function_tool()
    async def get_user_email(self) -> str:
        """Returns stored email or empty string"""
        try:
            # First check local cache
            roomName = self.room_name
            logger.info(f"Checking email for room: {roomName}")
            if roomName in self._session_emails:
                email = self._session_emails[roomName]
                # Log result before returning
                self._log_tool_result(f"get_user_email result: {email}")
                return email
            
            # Query Supabase
            email = await self.supabase.get_email_for_session(roomName)
            if email:
                self._session_emails[roomName] = email
                # Log result before returning
                self._log_tool_result(f"get_user_email result: {email}")
                return email
            result = "email not found"
            self._log_tool_result(f"get_user_email result: {result}")
            return result
        except Exception as e:
            logger.error(f"Email lookup failed: {str(e)}")
            self._log_tool_result(f"get_user_email error: {str(e)}")
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
            # Log result before returning
            self._log_tool_result(result)
            return result
        except Exception as e:
            error_msg = f"Unable to access current information due to an internal error: {str(e)}"
            logger.error(f"Web search function error: {str(e)}")
            # Log error message as result
            self._log_tool_result(error_msg)
            return error_msg
 
    
    @function_tool()
    async def request_email(self) -> str:
        """Signal frontend to show email form and provide user instructions"""
        try:
            await self.set_agent_state("email_requested")
            result = "Please provide your email address in the form that just appeared below."
            # Log result before returning
            self._log_tool_result(result)
            return result
        except Exception as e:
            # Updated error message to be more generic
            error_msg = "There was an issue requesting your email. Please let me know your email address directly."
            logger.error(f"Failed to request email: {str(e)}")
            # Log error message as result
            self._log_tool_result(error_msg)
            return error_msg
        
    @function_tool()
    async def request_resume(self) -> str:
        """Signal frontend to show resume upload form and provide user instructions"""
        try:
            await self.set_agent_state("resume_requested")
            result = "Please upload your resume in the form that just appeared below."
            # Log result before returning
            self._log_tool_result(result)
            return result
        except Exception as e:
            # Updated error message to be more generic
            error_msg = "There was an issue requesting your resume. Could you describe your experience or paste relevant parts of your resume here?"
            logger.error(f"Failed to request resume: {str(e)}")
            # Log error message as result
            self._log_tool_result(error_msg)
            return error_msg
        
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
            result = f"Agent state updated."
            # Log result before returning
            self._log_tool_result(result)
            return result
        except Exception as e:
            logger.error(f"Error setting agent state: {str(e)}")
            # Log error message as result
            error_msg = f"Internal error setting agent state: {str(e)}"
            self._log_tool_result(error_msg)
            # Let the LLM know something went wrong without crashing
            return f"I encountered an internal issue updating my state."

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
            # Log result before returning
            self._log_tool_result(results)
            return results
        except Exception as e:
            error_msg = "I encountered an error trying to search the knowledge base."
            logger.error(f"Knowledge base search failed: {str(e)}")
            # Log error message as result
            self._log_tool_result(error_msg)
            return error_msg

    @function_tool()
    async def get_resume_information(self) -> str:
        """
        Analyzes the user's previously uploaded resume using the Google Cloud Document AI Summarizer
        to extract key information. Call this when the user asks to analyze, summarize, or get details
        from their resume. Finds the resume file locally, sends it to the Document AI API,
        and returns the extracted information (often as a summary).
        """
        # --- Cleanup Logic Start ---
        try:
            if UPLOAD_FOLDER.exists() and UPLOAD_FOLDER.is_dir():
                items = list(UPLOAD_FOLDER.iterdir())
                if len(items) >= 10:
                    logger.warning(f"Uploads directory reached {len(items)} items. Cleaning up...")
                    for item_path in items:
                        try:
                            if item_path.is_file():
                                item_path.unlink() # More idiomatic Pathlib way
                                logger.info(f"Deleted file: {item_path}")
                            elif item_path.is_dir():
                                shutil.rmtree(item_path)
                                logger.info(f"Deleted directory: {item_path}")
                        except Exception as cleanup_err:
                            logger.error(f"Error deleting item {item_path}: {cleanup_err}")
                    logger.info("Uploads directory cleanup complete.")
        except Exception as e:
            logger.error(f"Error during upload directory cleanup check: {e}")
        # --- Cleanup Logic End ---

        if not self.is_docai_summarizer_configured:
            logger.warning("Document AI Summarizer client not available for get_resume_information.")
            result = "I cannot analyze the resume at the moment because the required Document AI service is not configured or available."
            self._log_tool_result(result)
            return result

        session_id = self.room_name
        logger.info(f"(DocAI Summarizer) Attempting to find resume for session: {session_id} for summarization.")
        found_file_path = None
        file_mime_type = None

        try:
            # Find the local file path
            # Prioritize PDF, then DOCX (common resume formats)
            supported_formats = {
                '.pdf': 'application/pdf',
                '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                # Add other Document AI supported types if needed, e.g., .txt: 'text/plain'
            }
            for ext, mime_type in supported_formats.items():
                potential_path = UPLOAD_FOLDER / f"{session_id}_resume{ext}"
                # Use synchronous os.path.isfile
                if os.path.isfile(potential_path):
                    found_file_path = potential_path
                    file_mime_type = mime_type
                    break

            if not found_file_path:
                logger.warning(f"(DocAI Summarizer) No local resume file found for session: {session_id} in {UPLOAD_FOLDER} with supported extensions ({', '.join(supported_formats.keys())})")
                result = "I could not find an uploaded resume for this session to summarize. Please upload it first (PDF or DOCX preferred), or confirm the upload was successful."
                self._log_tool_result(result)
                return result

            logger.info(f"(DocAI Summarizer) Found local resume file: {found_file_path} (Type: {file_mime_type})")

            # Process with Document AI Summarizer
            try:
                logger.info("(DocAI Summarizer) Processing document with Document AI...")
                document_result = await self._process_resume_with_docai(found_file_path, file_mime_type)

                # The Summarizer processor typically returns the summary in the main 'text' field
                summary = document_result.text.strip()

                if not summary:
                     logger.warning(f"(DocAI Summarizer) Document AI returned an empty summary for {found_file_path}.")
                     result = "I was able to process the resume file, but the Document AI service did not return a summary."
                     self._log_tool_result(result)
                     return result

                logger.info(f"(DocAI Summarizer) Received summary from Document AI ({len(summary)} chars).")
                # Log the result before returning
                self._log_tool_result(f"DocAI summary result ({len(summary)} chars): {summary[:200]}...") # Log start of result
                return f"Here is a summary of the resume:\n\n{summary}"

            except Exception as docai_err:
                logger.error(f"(DocAI Summarizer) Error during Document AI processing for {found_file_path}: {docai_err}")
                logger.error(traceback.format_exc())
                error_detail = str(docai_err)
                result = f"I encountered an error while trying to summarize the resume ({found_file_path.name}) with the Document AI service. Details: {error_detail}"
                self._log_tool_result(result)
                return result

        except Exception as e:
            logger.error(f"(DocAI Summarizer) Unexpected error in get_resume_information: {str(e)}")
            logger.error(traceback.format_exc())
            result = "An unexpected error occurred while attempting to retrieve and summarize the resume information."
            self._log_tool_result(result)
            return result

    async def _process_resume_with_docai(self, file_path: pathlib.Path, mime_type: str) -> documentai.Document:
        """
        Helper function to process a resume file using the configured Document AI Summarizer.
        Handles synchronous file reading and Document AI API call within an async context.
        """
        try:
            # Construct the full resource name of the processor
            resource_name = self.docai_client.processor_path(
                self.docai_project_id, self.docai_location, self.docai_summarizer_processor_id
            )

            # Read the file content synchronously
            # loop = asyncio.get_event_loop()
            # content = await loop.run_in_executor(None, file_path.read_bytes)

            # Simplified synchronous read - may block event loop briefly for large files,
            # consider run_in_executor for very large files if needed.
            with open(file_path, "rb") as file:
                content = file.read()


            # Load Binary Data into Document AI RawDocument Object
            raw_document = documentai.RawDocument(content=content, mime_type=mime_type)

            # Configure the process request
            # Specific configurations for Summarizer can be added here if needed
            # processor_config = documentai.ProcessorConfig(...)
            request = documentai.ProcessRequest(
                name=resource_name,
                raw_document=raw_document,
                # skip_human_review=True # Set to True if you don't require human review
                # process_options=documentai.ProcessOptions(...) # More options if needed
            )

            logger.info(f"(DocAI Summarizer) Sending request to processor: {resource_name}")

            # Use the Document AI client to process the document synchronously within executor
            # This is often recommended for SDK client calls in async code
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self.docai_client.process_document, request)

            # # Alternatively, if the client itself supports async directly (check library docs)
            # result = await self.docai_client.process_document(request=request) # Check if awaitable

            logger.info("(DocAI Summarizer) Received response from Document AI.")
            return result.document

        except Exception as e:
            logger.error(f"(DocAI Summarizer) Error in _process_resume_with_docai: {e}")
            # Re-raise the exception to be caught by the caller
            raise

    # Helper method to log tool results consistently
    def _log_tool_result(self, result_content: str):
        if self.conversation_manager:
            try:
                self.conversation_manager.add_message({
                    "role": "tool_result",
                    "content": str(result_content) # Ensure it's a string
                })
                logger.info(f"Logged tool result: {str(result_content)[:100]}...")
            except Exception as log_e:
                logger.error(f"Error logging tool result: {log_e}")
        else:
            logger.warning("ConversationManager not available in AssistantFnc for logging tool result.")





