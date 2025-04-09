import os
import asyncio
import requests
import logging
import traceback
from livekit.agents import llm
import enum
from typing import Annotated, List, Optional
import logging
import google.generativeai as genai
from pinecone import Pinecone, ServerlessSpec
# import nest_asyncio # No longer needed

# nest_asyncio.apply() # No longer needed

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

# --- Constants ---
# Moved constants inside the class or init where appropriate if they depend on init params
PINECONE_INDEX_NAME = "coachingbooks"
EMBEDDING_MODEL_NAME = "models/text-embedding-004"

# --- Assistant Function Context ---

class AssistantFnc(llm.FunctionContext):
    """Provides callable functions for the LLM agent to interact with knowledge sources."""
    def __init__(self, google_api_key: str, pinecone_api_key: str, pinecone_region: str, pinecone_cloud: str, serp_api_key: str):
        super().__init__()
        self.genai_configured = False
        self.pinecone_index = None
        self.serpapi_key = None
        self.pinecone_cloud = pinecone_cloud
        self.pinecone_region = pinecone_region

        logger.info("Initializing Knowledge Base components within AssistantFnc...")

        # Initialize Google Generative AI (Synchronous part of init)
        try:
            if not google_api_key:
                raise ValueError("GOOGLE_API_KEY is required for embeddings.")
            # genai.configure is synchronous
            genai.configure(api_key=google_api_key)
            self.genai_configured = True
            logger.info("Google Generative AI configured successfully.")
        except Exception as e:
            logger.error(f"Failed to configure Google Generative AI: {e}", exc_info=True)
            self.genai_configured = False

        # Initialize Pinecone (Synchronous part of init)
        try:
            if not pinecone_api_key:
                raise ValueError("PINECONE_API_KEY is required.")
            # Pinecone client initialization is synchronous
            pinecone_client = Pinecone(api_key=pinecone_api_key)
            logger.info(f"Pinecone client initialized. Checking for index '{PINECONE_INDEX_NAME}'...")
            # Listing indexes is synchronous
            if PINECONE_INDEX_NAME not in pinecone_client.list_indexes().names:
                logger.warning(f"Pinecone index '{PINECONE_INDEX_NAME}' not found. Knowledge base search may fail.")
                self.pinecone_index = None
            else:
                # Getting index object is synchronous
                self.pinecone_index = pinecone_client.Index(PINECONE_INDEX_NAME)
                logger.info(f"Connected to existing Pinecone index: '{PINECONE_INDEX_NAME}'")
        except Exception as e:
            logger.error(f"Failed to initialize Pinecone: {e}", exc_info=True)
            self.pinecone_index = None

        # Store SerpAPI key (Synchronous part of init)
        if not serp_api_key:
             logger.warning("SERPAPI_KEY not provided. Web search will be unavailable.")
             self.serpapi_key = None
        else:
            self.serpapi_key = serp_api_key
            logger.info("SerpAPI key stored.")

        # Final check (Synchronous part of init)
        if self.genai_configured and self.pinecone_index is not None and self.serpapi_key is not None:
            logger.info("AssistantFnc knowledge components initialized successfully.")
        else:
            logger.warning("AssistantFnc knowledge initialization incomplete. Some features may be disabled.")

    # Keep _get_embedding async as it uses run_in_executor internally
    async def _get_embedding(self, text: str, task_type="retrieval_query") -> Optional[List[float]]:
        """Generates embedding for the given text using Google Generative AI."""
        if not self.genai_configured:
            logger.error("Google Generative AI not configured. Cannot generate embeddings.")
            return None
        if not text or not isinstance(text, str):
            logger.error("Invalid text provided for embedding.")
            return None
        try:
            # genai.embed_content is blocking, run in executor
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: genai.embed_content(
                    model=EMBEDDING_MODEL_NAME,
                    content=text,
                    task_type=task_type
                )
            )
            return result['embedding']
        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}", exc_info=True)
            return None

    @llm.ai_callable(
        description=(
            "Searches an internal knowledge base of coaching books and principles "
            "for established concepts, strategies, and general career advice. "
            "Use for foundational knowledge related to career coaching." # Simplified description
        )
    )
    async def query_knowledge_base( # Changed back to async def
        self,
        query: Annotated[
            str,
            llm.TypeInfo(description="The specific career coaching question or topic to search for in the knowledge base.")
        ],
        top_k: int = 3
    ) -> str:
        """Callable function to query the internal Pinecone knowledge base."""
        logger.info(f"AI Function Call: query_knowledge_base with query: {query[:100]}...")
        if not self.pinecone_index:
            logger.error("Pinecone index is not available (inside query_knowledge_base).")
            return "Internal knowledge base is currently unavailable due to an index connection issue."
        if not query:
            return "Cannot query knowledge base with an empty query."

        # Now execute async logic directly
        try:
            query_embedding = await self._get_embedding(query, task_type="retrieval_query")
            if not query_embedding:
                return "Could not process query for knowledge base search (embedding failed)."

            # Pinecone query is blocking, run in executor
            loop = asyncio.get_running_loop()
            results = await loop.run_in_executor(
                None,
                lambda: self.pinecone_index.query(
                    vector=query_embedding,
                    top_k=top_k,
                    include_metadata=True
                )
            )

            # Process results
            if not results or not results.matches:
                logger.warning(f"No relevant results found in knowledge base for query: {query[:100]}...")
                return "No relevant information found in the knowledge base."

            # Format results (same as before)
            formatted_results = "Found relevant information in the knowledge base:\n\n"
            for match in results.matches:
                score = match.score
                metadata = match.metadata if match.metadata else {}
                text_chunk = metadata.get('text', 'N/A')
                source = metadata.get('source', 'Unknown source')
                formatted_results += f"- Source: {source}\n"
                formatted_results += f"  Relevance Score: {score:.4f}\n"
                formatted_results += f"  Content: {text_chunk}\n\n"
            logger.info(f"Knowledge base query successful for: {query[:100]}...")
            return formatted_results.strip()

        except Exception as e:
             logger.error(f"Error querying Pinecone: {e}", exc_info=True)
             return f"An error occurred while searching the knowledge base: {e}"


    @llm.ai_callable(
        description=(
            "Searches the web for current information, recent events, company details, or specific facts "
            "when internal knowledge is insufficient or outdated. Use for timely information." # Simplified description
        )
    )
    async def search_web( # Changed back to async def
        self,
        search_query: Annotated[
            str,
            llm.TypeInfo(description="The specific query to search for on the web.")
        ]
    ) -> str:
        """Callable function to perform a web search using SerpAPI."""
        logger.info(f"AI Function Call: search_web with query: {search_query[:100]}...")
        if not self.serpapi_key:
            logger.error("SerpAPI key not available for web search (inside search_web).")
            return "Web search is currently unavailable (missing API key)."
        if not search_query:
            return "Cannot perform web search with an empty query."

        # Now execute async logic directly
        try:
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: requests.get(
                    "https://serpapi.com/search",
                    params={
                        "q": search_query,
                        "api_key": self.serpapi_key,
                        "engine": "google", "gl": "us", "hl": "en"
                    },
                    timeout=10
                )
            )
            response.raise_for_status()
            search_data = response.json()

            # --- NEW: Format results into a natural language summary ---
            summary_parts = []

            # 1. Prioritize Answer Box
            answer = None
            if "answer_box" in search_data:
                box = search_data["answer_box"]
                if "answer" in box:
                    answer = box['answer']
                    summary_parts.append(f"Found a direct answer: {answer}")
                elif "snippet" in box:
                    answer = box['snippet']
                    summary_parts.append(f"Found a featured snippet: {answer}")
                 # Add other answer_box types if needed (e.g., weather, dictionary)

            # 2. Use Top Organic Result if no direct answer found yet
            if not answer and "organic_results" in search_data and search_data["organic_results"]:
                top_result = search_data["organic_results"][0]
                title = top_result.get('title', '')
                snippet = top_result.get('snippet', '')
                if title and snippet:
                    summary_parts.append(f"The top search result, titled '{title}', mentioned: \"{snippet}\"")
                elif snippet:
                     summary_parts.append(f"The top search result mentioned: \"{snippet}\"")

            # 3. Optionally add Knowledge Graph info if distinct
            kg_info = None
            if "knowledge_graph" in search_data:
                 kg = search_data["knowledge_graph"]
                 kg_title = kg.get('title', '')
                 kg_description = kg.get('description', '')
                 if kg_title and kg_description:
                     kg_info = f"There was also related information about {kg_title}: {kg_description}"
                     # Avoid adding if it repeats the answer/snippet significantly
                     if answer and (kg_description in answer or answer in kg_description):
                          pass # Don't add redundant info
                     elif kg_info and len(summary_parts) < 2 : # Add if we don't have much else
                          summary_parts.append(kg_info)


            # 4. Construct the final summary
            if not summary_parts:
                 logger.warning(f"SerpAPI returned no usable results to summarize for query: {search_query}")
                 return "Web search did not return any relevant information."

            # Combine the parts into a concise summary
            final_summary = "Based on a quick web search: " + " ".join(summary_parts)
            # Limit length if necessary
            max_summary_length = 400 # Adjust as needed
            if len(final_summary) > max_summary_length:
                 final_summary = final_summary[:max_summary_length] + "..."


            logger.info(f"Web search successful for: {search_query}. Summary generated.")
            return final_summary
            # --- End NEW formatting ---

        except requests.exceptions.Timeout:
            logger.error(f"SerpAPI request timed out for query: {search_query}")
            return "Web search failed: The request timed out."
        except requests.exceptions.RequestException as e:
            logger.error(f"SerpAPI request failed: {e}", exc_info=True)
            return f"Web search failed: {e}"
        except Exception as e:
            logger.error(f"Error processing SerpAPI response: {e}", exc_info=True)
            return f"Web search failed during processing: {e}"


        