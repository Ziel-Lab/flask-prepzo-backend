from livekit.agents import llm
from knowledgebase import pinecone_search
from typing import Annotated, Optional, Dict
import logging, os, requests
from dotenv import load_dotenv

logger = logging.getLogger("user-data")
logger.setLevel(logging.INFO)

load_dotenv(dotenv_path=".env.local")

class SerpAPISearch:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://serpapi.com/search"
        if not self.api_key:
            raise ValueError("SERPAPI_KEY environment variable not set")

    async def search(self, query: str) -> Optional[Dict]:
        try:
            params = {
                "q": query,
                "api_key": self.api_key,
                "engine": "google",
                "hl": "en"
            }
            response = requests.get(self.base_url, params=params)
            response.raise_for_status()
            return self._parse_results(response.json())
        except Exception as e:
            logger.error(f"Search error: {str(e)}")
            return None

    def _parse_results(self, results: Dict) -> Dict:
        parsed = {
            "organic": [],
            "answer_box": None,
            "related_questions": []
        }
        if "organic_results" in results:
            parsed["organic"] = [
                {
                    "title": r.get("title"),
                    "link": r.get("link"),
                    "snippet": r.get("snippet")
                } for r in results["organic_results"][:3]
            ]
        if "answer_box" in results:
            parsed["answer_box"] = {
                "answer": results["answer_box"].get("answer"),
                "snippet": results["answer_box"].get("snippet")
            }
        if "related_questions" in results:
            parsed["related_questions"] = [
                {
                    "question": q.get("question"),
                    "answer": q.get("answer")
                } for q in results["related_questions"][:3]
            ]
        return parsed

# New class to handle job searches using the Google Jobs API engine
class SerpAPIJobSearch(SerpAPISearch):
    async def search(self, query: str, location: Optional[str] = None) -> Optional[Dict]:
        try:
            params = {
                "q": query,
                "api_key": self.api_key,
                "engine": "google_jobs",
                "hl": "en"
            }
            if location:
                params["location"] = location
            response = requests.get(self.base_url, params=params)
            response.raise_for_status()
            # For job searches, we return the raw JSON so that we can access "jobs_results"
            return response.json()
        except Exception as e:
            logger.error(f"Job search error: {str(e)}")
            return None


class AssistantFnc(llm.FunctionContext):
    def __init__(self):
        super().__init__()
        serpapi_key = os.getenv("SERPAPI_KEY")
        if not serpapi_key:
            raise ValueError("Missing SERPAPI_KEY environment variable")
        self.search_client = SerpAPISearch(api_key=serpapi_key)
        self.job_search_client = SerpAPIJobSearch(api_key=serpapi_key)

    def _clean_text(self, text: str) -> str:
        """Sanitize text for LLM consumption"""
        return text.replace('\n', ' ').strip()
    
    @llm.ai_callable(
            description="""Perform a websearch when realtime infprmation or current data (latest) is asked 
                        Use this when assisting with :
                        - Company information and news 
                        - Any information requiring latest data 
                        Parameters:
                        - query: Search keywords/phrase
            """
    )
    async def web_search(
        self,
        query: Annotated[str, llm.TypeInfo(description="The search query string")]
    ) -> str:
        """
         Return formated results with:
         - Direct answer (if available)
         - Top 3 relavant search results
         - Follow up questions
         - Error handling for empty search results

          Example response format:
        '📌 Direct Answer: <answer>
        
        🔍 Top Results:
        1. [Title](URL) - Snippet...
        
        ❓ People Also Ask:
        - Question 1?
        - Question 2?'

        """
        try:
            logger.info("Performing web search - query: %s", query)
            results = await self.search_client.search(query)
            if results is None:
                return "Search failed or returned no results."
            
            response = []
            if results.get("answer_box"):
                answer = results["answer_box"].get('answer') or results["answer_box"].get('snippet')
                if answer:
                    response.append(f"📌 Direct Answer: {self._clean_text(answer)}")
            
            # Organic results
            if results.get("organic"):
                response.append("🔍 Top Results:")
                for i, r in enumerate(results["organic"][:3], 1):  # Limit to top 3
                    title = self._clean_text(r.get('title', 'No title'))
                    snippet = self._clean_text(r.get('snippet', ''))
                    response.append(f"{i}. [{title}]({r.get('link', '#')})\n   {snippet}")
            
            # Related questions
            if results.get("related_questions"):
                response.append("❓ People Also Ask:")
                for q in results["related_questions"][:3]:  # Limit to 3 questions
                    question = self._clean_text(q.get('question', ''))
                    response.append(f"- {question}")
            
            return '\n\n'.join(response) or "No relevant information found"
        
        except Exception as e:
            logger.error(f"Search failed: {str(e)}")
            return "Unable to access current information. Please try again later."


    @llm.ai_callable(
        description="""Perform a job search using the SERP API.
        Parameters:
          - query: Job search keywords/phrase.
          - location: (Optional) Location to narrow the job search.
        """
    )    
    async def job_search(
        self,
        query: Annotated[str, llm.TypeInfo(description="The job search query string")],
        location: Optional[str] = None
    ) -> str:
        try:
            logger.info("Performing job search - query: %s, location: %s", query, location)
            results = await self.job_search_client.search(query, location)
            if results is None:
                return "Job search failed or returned no results."
            
            jobs = results.get("jobs_results", [])
            if not jobs:
                return "No job listings found."
            
            response_lines = ["💼 Job Listings:"]
            for i, job in enumerate(jobs[:5], 1):  # Limit to top 5 listings
                title = self._clean_text(job.get("title", "No title"))
                company = self._clean_text(job.get("company_name", "Unknown company"))
                loc = self._clean_text(job.get("location", "Unknown location"))
                snippet = self._clean_text(job.get("snippet", ""))
                link = job.get("link", "#")
                response_lines.append(
                    f"{i}. **{title}** at {company} ({loc})\n   {snippet}\n   [Apply Here]({link})"
                )
            return "\n\n".join(response_lines)
        except Exception as e:
            logger.error(f"Job search failed: {str(e)}")
            return "Unable to perform job search at the moment."
    
    
    @llm.ai_callable(
        description="Trigger email collection form on the frontend. Use when user agrees to provide email "
                "or requests email-based follow up. Returns instructions while signaling UI to show form."
    )
    async def request_email(self) -> str:
        """Signal frontend to show email form and provide user instructions"""
        try:
        # Set agent state to trigger frontend email form
            await self.set_agent_state("email_requested")
            return "Please provide your email address in the form that just appeared below."
        except Exception as e:
            logger.error(f"Failed to request email: {str(e)}")
            return "Please provide your email address so I can send you the information."
        
    @llm.ai_callable(
        description="Set the agent state marker to notify the frontend UI. " +
                    "This marker is used (for example) to trigger the email collection form when set to 'email_requested'."
    )
    async def set_agent_state(self, state: str) -> str:
        """
        Update the agent state marker.
        
        Parameters:
          - state: A string representing the new state (e.g., "email_requested").
        
        Returns:
          A confirmation message.
        """
        try:
            self.agent_state = state
            logger.info(f"Agent state set to: {state}")

            # If running in a browser, update the global marker.
            if isinstance(__import__('sys').modules.get('window'), object):
                # This check ensures we're in a browser environment.
                # Alternatively, you can use a try/except for window.
                try:
                    if hasattr(window, 'emailRequested'):
                        window.emailRequested = (state == "email_requested")
                except Exception:
                    pass  # in case window is not defined

            return f"Agent state updated: {state}"
        except Exception as e:
            logger.error(f"Error setting agent state: {str(e)}")
            return "Failed to update agent state."
        
    @llm.ai_callable(
        description="A simple test function to verify tool calling is working."
    )
    def test_tool_availability(self) -> str:
        """Simply logs a message and returns a confirmation."""
        logger.critical("%%% SIMPLE TEST TOOL CALLED SUCCESSFULLY %%%")
        return "Simple test tool executed successfully."
        
    @llm.ai_callable(   
        description="""**Crucially, use this tool first** to search the internal knowledge base whenever the user asks about coaching techniques (like STAR method), career advice, resume building, interview preparation, or specific concepts/books relevant to our coaching philosophy (e.g., 'Deep Work', 'Zero to One'), even if you think you know the answer. This tool accesses proprietary perspectives and internal documents not available publicly. This searches across all available namespaces in the knowledge base.
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
        # Call the imported function
        return await pinecone_search(query=query)
        
    