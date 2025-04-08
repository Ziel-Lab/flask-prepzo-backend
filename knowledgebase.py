import os
import asyncio
import requests
import logging
import traceback
import google.generativeai as genai
from pinecone import Pinecone, ServerlessSpec  # Import Pinecone components

# Configure logging
logger = logging.getLogger(__name__) # Use __name__ for logger
logger.setLevel(logging.INFO) # Set appropriate level
# Add handlers if needed (e.g., console, file) - assuming basic config for now
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)


# --- Globals (initialized by init_knowledgebase) ---
pinecone_client: Pinecone = None
pinecone_index = None
genai_configured = False
serpapi_key = None

# --- Constants ---
PINECONE_INDEX_NAME = "coachingbooks"
# Ensure you are using a compatible embedding model name if not default
# For GenAI models like 'models/embedding-001' or similar
# If using OpenAI via GenAI, might be different. Let's assume a GenAI model.
EMBEDDING_MODEL_NAME = "models/text-embedding-004" # Example GenAI model
PINECONE_CLOUD = os.environ.get("PINECONE_CLOUD", "aws") # Default or from env
PINECONE_REGION = os.environ.get("PINECONE_REGION", "us-east-1") # Default or from env

# --- Initialization ---
def init_knowledgebase(google_api_key: str, pinecone_api_key: str, serp_api_key_in: str):
    """Initializes Google Generative AI, Pinecone client, and stores SerpAPI key."""
    global pinecone_client, pinecone_index, genai_configured, serpapi_key

    logger.info("Initializing Knowledge Base components...")

    # Initialize Google Generative AI
    try:
        if not google_api_key:
            raise ValueError("GOOGLE_API_KEY is required for embeddings.")
        genai.configure(api_key=google_api_key)
        # Test configuration (optional, but good practice)
        # Example: list models to check connection, adapt as needed
        models = [m for m in genai.list_models() if 'embedContent' in m.supported_generation_methods]
        if not any(EMBEDDING_MODEL_NAME in m.name for m in models):
             logger.warning(f"Specified embedding model '{EMBEDDING_MODEL_NAME}' not found or doesn't support embedContent. Available: {[m.name for m in models]}")
             # Decide whether to raise error or proceed with a default
        genai_configured = True
        logger.info("Google Generative AI configured successfully for embeddings.")
    except Exception as e:
        logger.error(f"Failed to configure Google Generative AI: {e}", exc_info=True)
        genai_configured = False # Ensure flag is False on error


    # Initialize Pinecone
    try:
        if not pinecone_api_key:
            raise ValueError("PINECONE_API_KEY is required.")

        pinecone_client = Pinecone(api_key=pinecone_api_key)
        logger.info(f"Pinecone client initialized. Checking for index '{PINECONE_INDEX_NAME}'...")

        if PINECONE_INDEX_NAME not in pinecone_client.list_indexes().names:
            logger.warning(f"Pinecone index '{PINECONE_INDEX_NAME}' not found.")
            # Optionally create the index if it doesn't exist (adjust spec as needed)
            # try:
            #     logger.info(f"Attempting to create index '{PINECONE_INDEX_NAME}'...")
            #     pinecone_client.create_index(
            #         name=PINECONE_INDEX_NAME,
            #         dimension=768, # Adjust dimension based on EMBEDDING_MODEL_NAME output
            #         metric='cosine', # Or 'euclidean', 'dotproduct'
            #         spec=ServerlessSpec(
            #             cloud=PINECONE_CLOUD,
            #             region=PINECONE_REGION
            #         )
            #     )
            #     logger.info(f"Index '{PINECONE_INDEX_NAME}' created successfully.")
            #     pinecone_index = pinecone_client.Index(PINECONE_INDEX_NAME)
            # except Exception as create_err:
            #     logger.error(f"Failed to create Pinecone index '{PINECONE_INDEX_NAME}': {create_err}", exc_info=True)
            #     pinecone_index = None # Ensure index is None if creation fails
            pinecone_index = None # Set to None if not found and not created
        else:
            pinecone_index = pinecone_client.Index(PINECONE_INDEX_NAME)
            logger.info(f"Connected to existing Pinecone index: '{PINECONE_INDEX_NAME}'")

    except Exception as e:
        logger.error(f"Failed to initialize Pinecone: {e}", exc_info=True)
        pinecone_client = None
        pinecone_index = None

    # Store SerpAPI key
    if not serp_api_key_in:
         logger.warning("SERPAPI_KEY not provided. Web search will be unavailable.")
         serpapi_key = None
    else:
        serpapi_key = serp_api_key_in
        logger.info("SerpAPI key stored.")

    if genai_configured and pinecone_index and serpapi_key:
        logger.info("Knowledge Base components initialized successfully.")
        return True
    else:
        logger.warning("Knowledge Base initialization incomplete. Some features may be disabled.")
        return False


# --- Embedding Function ---
async def get_embedding(text: str, task_type="retrieval_query") -> list[float] | None:
    """Generates embedding for the given text using Google Generative AI."""
    if not genai_configured:
        logger.error("Google Generative AI not configured. Cannot generate embeddings.")
        return None
    if not text or not isinstance(text, str):
        logger.error("Invalid text provided for embedding.")
        return None

    try:
        # Use asyncio.to_thread for the blocking genai call
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, # Use default executor
            lambda: genai.embed_content(
                model=EMBEDDING_MODEL_NAME,
                content=text,
                task_type=task_type # e.g., "retrieval_query", "semantic_similarity"
                # title="Custom title" # Optional title
            )
        )
        # logger.debug(f"Generated embedding for text: {text[:50]}...")
        return result['embedding']
    except Exception as e:
        logger.error(f"Failed to generate embedding: {e}", exc_info=True)
        return None

# --- Pinecone Query Function ---
async def query_pinecone_knowledge_base(query: str, top_k: int = 3) -> str | None:
    """Queries the Pinecone index for the given query string."""
    if not pinecone_index:
        logger.error("Pinecone index is not available.")
        return "Internal knowledge base is currently unavailable due to an index connection issue."
    if not query:
        return "Cannot query knowledge base with an empty query."

    logger.info(f"Querying knowledge base with: {query[:100]}...")
    try:
        query_embedding = await get_embedding(query, task_type="retrieval_query")
        if not query_embedding:
            return "Could not process query for knowledge base search (embedding failed)."

        # Perform the search
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(
            None,
            lambda: pinecone_index.query(
                vector=query_embedding,
                top_k=top_k,
                include_metadata=True # Fetch metadata like text chunks, source
            )
        )

        # Format results
        if not results or not results.matches:
            logger.warning(f"No relevant results found in knowledge base for query: {query[:100]}...")
            return None # Return None for no results

        formatted_results = "Found relevant information in the knowledge base:\n\n"
        for match in results.matches:
            score = match.score
            metadata = match.metadata if match.metadata else {}
            text_chunk = metadata.get('text', 'N/A') # Assuming 'text' field in metadata
            source = metadata.get('source', 'Unknown source') # Assuming 'source' field
            formatted_results += f"- Source: {source}\n"
            formatted_results += f"  Relevance Score: {score:.4f}\n"
            formatted_results += f"  Content: {text_chunk}\n\n"

        logger.info(f"Knowledge base query successful for: {query[:100]}...")
        return formatted_results.strip()

    except Exception as e:
        logger.error(f"Error querying Pinecone: {e}", exc_info=True)
        return f"An error occurred while searching the knowledge base: {e}"


# --- Web Search Function ---
async def perform_web_search(search_query: str):
    """
    Performs a web search using SerpAPI.

    Args:
        search_query (str): The search query.

    Returns:
        str: Formatted search results or an error message.
    """
    if not serpapi_key:
        logger.error("SerpAPI key not available for web search.")
        return "Web search is currently unavailable (missing API key)."
    if not search_query:
        return "Cannot perform web search with an empty query."

    logger.info(f"Performing web search for: {search_query}")
    try:
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,  # Use the default thread pool executor
            lambda: requests.get(
                "https://serpapi.com/search",
                params={
                    "q": search_query,
                    "api_key": serpapi_key,
                    "engine": "google",
                    "gl": "us", # Example: Geolocation US
                    "hl": "en"  # Example: Language English
                },
                 timeout=10 # Add a timeout
            )
        )
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

        search_data = response.json()
        results_text = ""

        # Extract and format results concisely
        if "answer_box" in search_data:
            box = search_data["answer_box"]
            if "answer" in box: results_text += f"Direct Answer: {box['answer']}\n\n"
            elif "snippet" in box: results_text += f"Featured Snippet: {box['snippet']}\n\n"

        if "organic_results" in search_data:
            results_text += "Top Search Results:\n"
            for i, result in enumerate(search_data["organic_results"][:3], 1): # Limit to top 3
                title = result.get('title', '')
                snippet = result.get('snippet', '')
                link = result.get('link', '')
                results_text += f"{i}. {title}\n   {snippet}\n   <{link}>\n" # Simplified format
            results_text += "\n"

        # Add knowledge graph summary if present and no other results yet
        if not results_text.strip() and "knowledge_graph" in search_data:
             kg = search_data["knowledge_graph"]
             title = kg.get('title', '')
             description = kg.get('description', '')
             if title or description:
                 results_text += f"Knowledge Graph Summary:\nTitle: {title}\nDescription: {description}\n"


        if not results_text.strip():
             logger.warning(f"SerpAPI returned no usable results for query: {search_query}")
             return "Web search did not return any relevant results."

        logger.info(f"Web search successful for: {search_query}")
        return results_text.strip()

    except requests.exceptions.Timeout:
        logger.error(f"SerpAPI request timed out for query: {search_query}")
        return "Web search failed: The request timed out."
    except requests.exceptions.RequestException as e:
        logger.error(f"SerpAPI request failed: {e}", exc_info=True)
        return f"Web search failed: {e}"
    except Exception as e:
        logger.error(f"Error processing SerpAPI response: {e}", exc_info=True)
        return f"Web search failed during processing: {e}"


# --- Tool Declarations (for potential future use with LLM function calling) ---
def get_web_search_tool_declaration():
    """Returns the function declaration for the web search tool."""
    return {
        "name": "perform_web_search", # Match the actual function name
        "description": (
            "Searches the web for current information on a specific topic, event, or data point "
            "when internal knowledge is insufficient, outdated, or needs verification. "
            "Use for recent events, real-time data (like stock prices, weather), or specific factual lookups."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "search_query": {
                    "type": "string",
                    "description": "The specific query to search for on the web."
                }
                # Removed include_location as the function doesn't use it directly
                # Location can be added to the query string if needed by the LLM
            },
            "required": ["search_query"]
        }
    }


def get_knowledge_base_tool_declaration():
    """Returns the function declaration for the knowledge base tool."""
    return {
        "name": "query_pinecone_knowledge_base", # Match the actual function name
        "description": (
            "Searches an internal knowledge base of coaching books and principles "
            "for established concepts, strategies, and general career advice. "
            "Prioritize this over web search for foundational or evergreen knowledge."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The specific question or topic to search for in the knowledge base."
                }
                # top_k could be added here if you want the LLM to control it
            },
            "required": ["query"]
        }
    }

