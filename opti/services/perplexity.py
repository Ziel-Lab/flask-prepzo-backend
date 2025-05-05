import traceback
from openai import AsyncOpenAI
from ..config import settings
from ..utils.logging_config import setup_logger

# Use centralized logger
logger = setup_logger("perplexity-service")

class PerplexityService:
    """Service for accessing Perplexity's web search API"""
    
    def __init__(self):
        """Initialize the service with Perplexity API credentials"""
        try:
            api_key = settings.PERPLEXITY_API_KEY
            if not api_key:
                logger.warning("Missing PERPLEXITY_API_KEY environment variable. Web search will not work.")
                self.client = None
            else:
                self.client = AsyncOpenAI(api_key=api_key, base_url="https://api.perplexity.ai")
                logger.info("PerplexityService initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize PerplexityService: {e}")
            logger.error(traceback.format_exc())
            self.client = None

    async def web_search(self, query: str, model_name: str = "sonar") -> str:
        """
        Performs a web search using Perplexity API
        
        Args:
            query (str): The structured query string
            model_name (str): The model to use for search (default: "sonar")
            
        Returns:
            str: The search results as a string
        """
        if not self.client:
            return "Web search is currently unavailable due to missing API credentials."
            
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