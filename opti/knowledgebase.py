"""
Compatibility module for the old knowledgebase.py interface

This module provides backward compatibility with the old knowledgebase API
by redirecting calls to the new pinecone_service module.
"""
import asyncio
from typing import Optional
import logging
import traceback
from .services.pinecone_service import PineconeService
from .utils.logging_config import setup_logger

# Setup logger
logger = setup_logger("knowledge-compat")

# Create singleton instance
_pinecone_service = None

def get_pinecone_service() -> PineconeService:
    """Get or create the Pinecone service singleton"""
    global _pinecone_service
    if _pinecone_service is None:
        _pinecone_service = PineconeService()
    return _pinecone_service

async def pinecone_search(query: str, top_k: int = 3) -> str:
    """
    Legacy compatibility function for pinecone_search
    
    Redirects to the new PineconeService.search method
    
    Args:
        query (str): The search query
        top_k (int): Number of results to retrieve
        
    Returns:
        str: The search results as text
    """
    try:
        logger.info(f"Legacy pinecone_search called with query: {query}")
        service = get_pinecone_service()
        result = await service.search(query, top_k)
        return result
    except Exception as e:
        logger.error(f"Error in legacy pinecone_search: {str(e)}")
        logger.error(traceback.format_exc())
        return "Sorry, I encountered an error while searching the knowledge base." 