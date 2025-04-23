from livekit.agents import llm
from livekit.agents import function_tool
from typing import Annotated, Optional, Dict, Literal
import logging, os, requests
from knowledgebase import pinecone_search
from dotenv import load_dotenv
from openai import OpenAI
import json
from supabase_client import SupabaseEmailClient
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
    def __init__(self, room_name: str, conversation_manager: ConversationManager):
        perplexity_api_key = os.getenv("PERPLEXITY_API_KEY")
        self.room_name = room_name
        self.supabase = SupabaseEmailClient()
        self._session_emails = {} # Cache for session emails
        self.conversation_manager = conversation_manager # Store the manager

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
            error_msg = "Please provide your email address so I can send you the information."
            logger.error(f"Failed to request email: {str(e)}")
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
            # Log result before returning
            self._log_tool_result(results)
            return results
        except Exception as e:
            error_msg = "I encountered an error trying to search the knowledge base."
            logger.error(f"Knowledge base search failed: {str(e)}")
            # Log error message as result
            self._log_tool_result(error_msg)
            return error_msg

    # Helper method to log tool results consistently
    def _log_tool_result(self, result_content: str):
        if self.conversation_manager:
            try:
                self.conversation_manager.add_message({
                    "role": "tool_result",
                    "content": str(result_content) # Ensure it's a string
                })
                logger.info(f"Logged tool result from function: {str(result_content)[:100]}...")
            except Exception as log_e:
                logger.error(f"Error logging tool result from function: {log_e}")
        else:
            logger.warning("ConversationManager not available in AssistantFnc for logging tool result.")





