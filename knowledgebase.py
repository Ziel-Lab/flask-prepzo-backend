from livekit.agents import llm
from typing import Annotated, Optional, Dict, List
import logging, os, requests, asyncio
from dotenv import load_dotenv
from openai import OpenAI, AsyncOpenAI
from pinecone import ServerlessSpec, Pinecone
import traceback
import aiohttp
import json

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

load_dotenv()
pinecone_index_name = "coachingbooks"

PINECONE_API_KEY = os.environ["PINECONE_API_KEY"]
region = os.environ["PINECONE_REGION"]
pc = Pinecone(api_key=PINECONE_API_KEY, environment=region)
openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY")) 

stats = pc.Index(pinecone_index_name).describe_index_stats()

if not pc.has_index(pinecone_index_name):
    pc.create_index(
        name=pinecone_index_name,
        vector_type="dense",
        dimension=1536,
        metric="cosine",
        spec=ServerlessSpec(
            cloud="aws",
            region="us-east-1"
        ),
        deletion_protection="disabled",
        tags={
            "environment": "development"
        }
    )
def get_embedding(text: str) -> List[float]:
    """
    Convert text into an embedding using OpenAI's text-embedding-3-small model.
    
    Args:
        text (str): The input text to be embedded.
    
    Returns:
        List[float]: A list representing the embedding vector.
    """
    # Ensure the input text is not empty or just whitespace
    text = text.strip()
    if not text:
        raise ValueError("Input text cannot be empty for embedding.")
        
    # Create the embedding using the updated v1.0+ syntax
    response = openai.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    # Extract and return the embedding from the response
    # Access data using .data notation
    embedding = response.data[0].embedding 
    return embedding

def upsert_document_with_embedding(doc_id: str, text: str, metadata: dict):
    # Get the embedding for the text
    embedding = get_embedding(text)

    metadata['text'] = text

    # Format the vector data for Pinecone
    vector = {
        "id": doc_id,
        "values": embedding,
        "metadata": metadata
    }
    # Upsert into the index
    index = pc.Index(pinecone_index_name)
    index.upsert(vectors=[vector])
    print(f"Document {doc_id} upserted with embedding.")

async def query_pinecone_knowledge_base(query: str, top_k: int = 3) -> str:
    """Query Pinecone index with OpenAI embeddings"""
    if not pinecone_index_name:
        return "Knowledge base unavailable"
    
    try:
        embedding = await get_embedding(query)
        if not embedding:
            return "Could not process query"

        results = pc.Index(pinecone_index_name).query(
            vector=embedding,
            top_k=top_k,
            include_metadata=True,
            namespace="the_lean_startup"
        )

        formatted = []
        for match in results.matches:
            if match.score < 0.5:
                continue
                
            meta = match.metadata or {}
            formatted.append(
                f"• {meta.get('text', 'No text available')}\n"
                f"  Source: {meta.get('source', 'Unknown')}\n"
                f"  Confidence: {match.score:.2f}"
            )
            
        return "\n\n".join(formatted) if formatted else "No relevant results found"

    except Exception as e:
        logger.error(f"Knowledge base query failed: {str(e)}")
        return "Error querying knowledge base"
    
def get_knowledge_base_tool_declaration():
    """Returns the function declaration for the knowledge base tool."""
    return {
        "name": "query_pinecone_knowledge_base", # Match the actual function name
        "description": (
            "ACCESS INTERNAL KNOWLEDGE FIRST. Contains verified information about "
            "coaching methodologies, leadership principles, and professional development strategies. "
            "Use for: conceptual questions, historical context, established frameworks."
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

@llm.ai_callable(
    description="""Search the internal knowledge base for specific information about coaching techniques, 
               internal documents, or proprietary data that is not typically found on the public web. 
               Use this when the user asks about specific concepts, methods, or content likely stored internally.
               This searches across all available namespaces in the knowledge base.
               Parameters:
                 - query: The search keywords/phrase based on the user's question.
              """
)
async def pinecone_search(
    query: Annotated[str, llm.TypeInfo(description="The search query string for the internal knowledge base")]
) -> str:
    """
    Performs a similarity search across all relevant namespaces in the Pinecone vector database 
    and returns relevant text snippets.
    """
    # Define recommended pooling settings for query_namespaces
    POOL_THREADS = 30
    CONNECTION_POOL_MAXSIZE = 30
    TOP_K_RESULTS = 5

    try:
        logger.info(f"Performing knowledge base search across namespaces - query: {query}")

        # 1. Get embedding for the query
        # Assume get_embedding is synchronous for now based on its definition
        # If it needs to be async, use await get_embedding(query)
        query_embedding = get_embedding(query)

        # 2. Initialize index object with pooling settings
        # Use the global pc object initialized earlier
        index = pc.Index(
            pinecone_index_name,
            pool_threads=POOL_THREADS,
            connection_pool_maxsize=CONNECTION_POOL_MAXSIZE
        )

        # 3. Get list of namespaces to query
        namespaces_to_query = []
        try:
            stats = index.describe_index_stats()
            if stats.namespaces:
                # Query non-empty namespaces, including the default ("" if present)
                namespaces_to_query = [ns for ns, info in stats.namespaces.items() if info.vector_count > 0]
            if not namespaces_to_query:
                 # Fallback to default namespace if stats fail or all namespaces are empty
                 logger.warning("No non-empty namespaces found or failed to get stats, querying default namespace only.")
                 namespaces_to_query = [""] # Pinecone uses empty string for default
            logger.info(f"Querying namespaces: {namespaces_to_query}")
        except Exception as stats_e:
             logger.error(f"Failed to get index stats, querying default namespace only: {stats_e}")
             namespaces_to_query = [""]

        # 4. Query Pinecone across namespaces
        query_results = index.query_namespaces(
            vector=query_embedding,
            top_k=TOP_K_RESULTS,
            include_metadata=True,
            namespaces=namespaces_to_query
            # metric="cosine", # Usually inherited from index, but can specify
            # include_values=False # Default is False
        )
        logger.debug(f"Pinecone query_namespaces results: {query_results}")

        # 5. Process results (same logic as before)
        matches = query_results.get('matches', [])
        if not matches:
            return "I couldn't find specific information on that topic in the knowledge base across the relevant sections."

        retrieved_texts = [
            match['metadata']['text']
            for match in matches
            if 'metadata' in match and 'text' in match['metadata']
        ]

        if not retrieved_texts:
            logger.warning("Knowledge base query returned matches, but no 'text' found in metadata.")
            return "I found some related entries, but couldn't retrieve the specific text snippets."

        # 6. Format and return response
        context = "\n\n---\n\n".join(retrieved_texts)
        response = f"Based on the knowledge base:\n\n{context}"
        logger.info(f"Returning knowledge base results: {response[:100]}...")
        return response

    except Exception as e:
        logger.error(f"Knowledge base search failed: {str(e)}")
        logger.error(traceback.format_exc())
        return "Sorry, I encountered an error while searching the knowledge base."