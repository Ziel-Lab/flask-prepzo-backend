import traceback
from openai import AsyncOpenAI
from ..config import settings
from ..utils.logging_config import setup_logger

# Use centralized logger
logger = setup_logger("perplexity-service")

PERPLEXITY_API_URL = "https://api.perplexity.ai"

class PerplexityService:
    """Service for accessing Perplexity's web search API"""
    
    def __init__(self):
        """Initialize the service with Perplexity API credentials and client"""
        self.api_key = settings.PERPLEXITY_API_KEY
        self.client = None # Initialize client attribute
        self.is_configured = False

        if not self.api_key:
            logger.error("Perplexity API key is missing. PerplexityService will not be functional.")
            return
        
        try:
            self.client = AsyncOpenAI(api_key=self.api_key, base_url=PERPLEXITY_API_URL)
            self.is_configured = True
            logger.info("PerplexityService initialized successfully with client.")
        except Exception as e:
            logger.error(f"Failed to initialize PerplexityService client: {e}")
            # self.client remains None, self.is_configured remains False

    async def web_search(self, query: str, model_name: str = "sonar") -> str: 
        """
        Performs a web search using Perplexity API
        
        Args:
            query (str): The structured query string
            model_name (str): The model to use for search (default: "sonar")
            
        Returns:
            str: The search results as a string
        """
        if not self.is_configured or not self.client: # Check if configured and client exists
            logger.warning("PerplexityService not configured or client not initialized. Web search unavailable.")
            return "Web search is currently unavailable due to a configuration issue."
            
        try:
            messages = [
                {"role": "system", "content": "You are a helpful assistant providing concise answers based on the user's detailed request."},
                {"role": "user", "content": query},
            ]
            logger.info(f"Sending web search request to Perplexity model: {model_name}")
            logger.info(f"Query: {query}")
            
            response = await self.client.chat.completions.create(
                model=model_name,
                messages=messages,
            )

            if response.choices and response.choices[0].message:
                answer = response.choices[0].message.content.strip()
                logger.info("Perplexity web search successful")
                return answer
            else:
                logger.error("Perplexity API returned an unexpected response structure")
                return "Sorry, I couldn't get an answer due to an API issue."

        except Exception as e:
            logger.error(f"Perplexity web search error: {str(e)}")
            logger.error(traceback.format_exc())
            return f"Sorry, an error occurred during the web search: {str(e)}" 