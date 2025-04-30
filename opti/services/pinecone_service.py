"""
Pinecone vector database service for knowledge retrieval
"""
import asyncio
import traceback
from typing import List
from pinecone import ServerlessSpec, Pinecone
from openai import AsyncOpenAI
from ..config import settings
from ..utils.logging_config import setup_logger

# Use centralized logger
logger = setup_logger("pinecone-service")

class PineconeService:
    """Service for interacting with Pinecone vector database"""
    
    def __init__(self):
        """Initialize the Pinecone service with credentials from settings"""
        try:
            # Initialize Pinecone client
            self.pc = Pinecone(api_key=settings.PINECONE_API_KEY, environment=settings.PINECONE_REGION)
            self.index_name = settings.PINECONE_INDEX_NAME
            
            # Initialize OpenAI client for embeddings
            self.openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            
            # Create index if it doesn't exist
            self._ensure_index_exists()
            
            logger.info(f"PineconeService initialized with index: {self.index_name}")
        except Exception as e:
            logger.error(f"Failed to initialize PineconeService: {e}")
            logger.error(traceback.format_exc())
            raise
            
    def _ensure_index_exists(self):
        """Ensure the Pinecone index exists, creating it if needed"""
        try:
            if not self.pc.has_index(self.index_name):
                logger.info(f"Creating Pinecone index: {self.index_name}")
                self.pc.create_index(
                    name=self.index_name,
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
                logger.info(f"Created Pinecone index: {self.index_name}")
            else:
                logger.info(f"Pinecone index {self.index_name} already exists")
        except Exception as e:
            logger.error(f"Error ensuring index exists: {e}")
            logger.error(traceback.format_exc())
            raise
    
    async def get_embedding(self, text: str) -> List[float]:
        """
        Convert text into an embedding using OpenAI's text-embedding-3-small model
        
        Args:
            text (str): The input text to be embedded
            
        Returns:
            List[float]: A list representing the embedding vector
        """
        text = text.strip()
        if not text:
            raise ValueError("Input text cannot be empty for embedding.")
            
        response = await self.openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=text
        )
        embedding = response.data[0].embedding 
        return embedding
        
    async def upsert_document(self, doc_id: str, text: str, metadata: dict):
        """
        Insert or update a document with its embedding in Pinecone
        
        Args:
            doc_id (str): The unique document identifier
            text (str): The document text
            metadata (dict): Additional metadata for the document
        """
        try:
            embedding = await self.get_embedding(text)
            
            # Add text to metadata for retrieval
            metadata['text'] = text
            vector = {
                "id": doc_id,
                "values": embedding,
                "metadata": metadata
            }
            
            # Get the index and upsert the vector
            index = self.pc.Index(self.index_name)
            
            # Run upsert in a thread to avoid blocking
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: index.upsert(vectors=[vector]))
            
            logger.info(f"Document {doc_id} upserted with embedding")
        except Exception as e:
            logger.error(f"Error upserting document {doc_id}: {e}")
            logger.error(traceback.format_exc())
            raise
            
    async def search(self, query: str, top_k: int = 3) -> str:
        """
        Search the Pinecone index for similar documents
        
        Args:
            query (str): The search query
            top_k (int): Number of results to return
            
        Returns:
            str: The concatenated text of the most relevant documents
        """
        POOL_THREADS = 30
        CONNECTION_POOL_MAXSIZE = 30
        
        try:
            logger.info(f"Performing knowledge base search - query: {query}")
            loop = asyncio.get_running_loop()

            query_embedding = await self.get_embedding(query)

            index = self.pc.Index(
                self.index_name,
                pool_threads=POOL_THREADS,
                connection_pool_maxsize=CONNECTION_POOL_MAXSIZE
            )

            # Get namespaces with vectors
            namespaces_to_query = []
            try:
                stats = await loop.run_in_executor(None, index.describe_index_stats)
                if stats.namespaces:
                    namespaces_to_query = [ns for ns, info in stats.namespaces.items() if info.vector_count > 0]
                if not namespaces_to_query:
                    logger.warning("No non-empty namespaces found, querying default namespace only")
                    namespaces_to_query = [""]
                logger.info(f"Querying namespaces: {namespaces_to_query}")
            except Exception as stats_e:
                logger.error(f"Failed to get index stats, querying default namespace only: {stats_e}")
                namespaces_to_query = [""]

            # Execute the query
            query_results = await loop.run_in_executor(
                None, 
                lambda: index.query_namespaces(
                    vector=query_embedding,
                    top_k=top_k,
                    include_metadata=True,
                    namespaces=namespaces_to_query,
                    metric="cosine"
                )
            )
            
            # Process results
            matches = query_results.get('matches', [])
            if not matches:
                return "I couldn't find specific information on that topic in the knowledge base."

            retrieved_texts = [
                match.metadata['text']
                for match in matches
                if hasattr(match, 'metadata') and match.metadata is not None and 'text' in match.metadata
            ]

            if not retrieved_texts:
                logger.warning("Knowledge base query returned matches, but no 'text' found in metadata")
                return "I found some related entries, but couldn't retrieve the specific text snippets."

            context = "\n\n---\n\n".join(retrieved_texts)
            response = f"Based on the knowledge:\n\n{context}"
            logger.info(f"Returning knowledge base results ({len(retrieved_texts)} documents)")
            return response

        except Exception as e:
            logger.error(f"Knowledge base search failed: {str(e)}")
            logger.error(traceback.format_exc())
            return "Sorry, I encountered an error while searching the knowledge base." 