from livekit.agents import llm
# Remove: from livekit.agents import function_tool
from typing import Annotated, Optional, Dict
import logging, os, requests
from knowledgebase import pinecone_search
from dotenv import load_dotenv
from openai import OpenAI
import json

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


class AssistantFnc(llm.FunctionContext):
    def __init__(self):
        super().__init__()
        # Removed SerpAPI key loading/client init as it's replaced
        # serpapi_key = os.getenv("SERPAPI_KEY")
        perplexity_api_key = os.getenv("PERPLEXITY_API_KEY")

        # Initialize Perplexity client
        if not perplexity_api_key:
            raise ValueError("Missing PERPLEXITY_API_KEY environment variable")
        self.perplexity_client = OpenAI(api_key=perplexity_api_key, base_url="https://api.perplexity.ai")

        # Initialize the consolidated Perplexity service
        self.perplexity_service = PerplexityService(client=self.perplexity_client)

        # Agent state attribute
        self.agent_state = None

    def _clean_text(self, text: str) -> str:
        """Sanitize text for LLM consumption"""
        return text.replace('\n', ' ').strip()

    @llm.ai_callable(
            description="""Use this primary tool to access external, real-time information from the web via Perplexity.
                        Handles general web searches (facts, news, company info) AND specific job searches (listings, trends, salaries).
                        The query provided to this tool MUST be structured according to the main system prompt instructions.
                        Parameters:
                        - query: A structured query string detailing the context, request, and desired output format.
            """
    )
    async def web_search(
        self,
        query: Annotated[str, llm.TypeInfo(description="The structured query string formulated according to system instructions.")]
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
 
    
    @llm.ai_callable(
        description="Trigger email collection form on the frontend. Use when user agrees to provide email "
                "or requests email-based follow up. Returns instructions while signaling UI to show form."
    )
    async def request_email(self) -> str:
        """Signal frontend to show email form and provide user instructions"""
        try:
            await self.set_agent_state("email_requested")
            return "Please provide your email address in the form that just appeared below."
        except Exception as e:
            logger.error(f"Failed to request email: {str(e)}")
            # Fallback instruction if state setting fails
            return "Please provide your email address so I can send you the information."
        
    @llm.ai_callable(
        description="Set the agent state marker to notify the frontend UI. " +
                    "This marker is used (for example) to trigger the email collection form when set to 'email_requested'."
    )
    async def set_agent_state(self, state: str) -> str:
        """
        Update the agent state marker. The frontend listens for changes to this state.
        
        Parameters:
          - state: A string representing the new state (e.g., "email_requested", "JOB_RESULTS_MARKDOWN:::[...]").
        
        Returns:
          A confirmation message or raises an error.
        """
        try:
            # In a real scenario, this might need to interact with the livekit agent context 
            # or a shared state manager if this function needs to be callable externally AND modify state.
            # If called internally like from job_search, modifying self.agent_state might suffice IF 
            # the frontend framework is observing changes to this specific AssistantFnc instance's state.
            # A more robust method might involve context.emit_event or similar.
            self.agent_state = state 
            logger.info(f"Agent state set to: {state[:50]}..." if len(state) > 50 else f"Agent state set to: {state}")
            
            # The original code had browser-specific JS execution here. 
            # This is generally not recommended from the backend Python code.
            # State changes should be communicated through the agent framework mechanisms.

            return f"Agent state updated."
        except Exception as e:
            logger.error(f"Error setting agent state: {str(e)}")
            # Re-raise or handle as appropriate for the framework
            raise # Or return a specific error message



    @llm.ai_callable(   
        description="""**ALWAYS, USE THIS TOOL FIRST** to search the internal knowledge base whenever the user asks about LEADERSHIP, TEAM DYNAMICS, ENTREPRENEURSHIP, LIFE DECISIONS,SARTUPS, MINDSET, GROWTH HACKING,coaching techniques (like STAR method), career advice, or specific concepts/books relevant to our coaching philosophy (e.g., 'Deep Work', 'Zero to One'),
        EVEN IF YOU THINK YOU KNOW THE ANSWER. 
        This tool accesses proprietary perspectives and internal documents not available publicly. 
        This searches across all available namespaces in the knowledge base.
            Parameters:
                - query: The search keywords/phrase based on the user's question about coaching, careers, resumes, interviews, or relevant concepts/books.
        """
    )
    async def search_knowledge_base(
        self,
        query: Annotated[str, llm.TypeInfo(description="The search query string for the internal knowledge base")]
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





