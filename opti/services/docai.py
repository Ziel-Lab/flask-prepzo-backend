import asyncio
import pathlib
import traceback
import shutil
import os
import json
import base64
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import google.generativeai as genai
from tenacity import retry as tenacity_retry, stop_after_attempt, wait_exponential
from ..config import settings
from ..utils.logging_config import setup_logger

logger = setup_logger("gemini-resume-service")

# Load credentials
genai.configure(api_key=settings.GEMINI_API_KEY)

class ResumeAnalysisService:
    """Enhanced resume analysis service with Gemini API"""
    
    MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
    SUPPORTED_MIME_TYPES = {
        '.pdf': 'application/pdf',
        '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        '.doc': 'application/msword',
        '.png': 'image/png',          # Add PNG support
        '.jpg': 'image/jpeg',         # Add JPG support
        '.jpeg': 'image/jpeg'         # Add JPEG support (uses same MIME type as JPG)
    }

    def __init__(self):
        """Initialize with configuration validation"""
        self.is_configured = False
        
        if not self._validate_config():
            return
            
        try:
            self._initialize_gemini()
            self.is_configured = True
        except Exception as e:
            logger.error(f"Initialization failed: {str(e)}")
            logger.error(traceback.format_exc())

    def _validate_config(self) -> bool:
        """Validate all required configuration parameters"""
        required_config = {
            "GEMINI_API_KEY": settings.GEMINI_API_KEY,
            "UPLOAD_FOLDER": settings.UPLOAD_FOLDER
        }
        
        missing = [key for key, value in required_config.items() if not value]
        if missing:
            logger.error(f"Missing configuration: {', '.join(missing)}")
            return False
            
        if not settings.UPLOAD_FOLDER.exists():
            logger.error(f"Upload folder does not exist: {settings.UPLOAD_FOLDER}")
            return False
            
        return True

    def _initialize_gemini(self):
        """Initialize Gemini model"""
        # Test connection to Gemini API
        try:
            self.model = genai.GenerativeModel('gemini-2.0-flash')
            # Simple test to verify API is working
            response = self.model.generate_content("Hello, test connection")
            if not response:
                raise ValueError("Could not connect to Gemini API")
            logger.info("Successfully connected to Gemini API")
        except Exception as e:
            logger.error(f"Gemini API initialization failed: {str(e)}")
            raise

    @tenacity_retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True
    )
    async def analyze_resume(self, session_id: str) -> Dict:
        """Main analysis workflow with enhanced error handling"""
        try:
            file_info = await self._locate_resume_file(session_id)
            if not file_info:
                return {"error": "No valid resume found"}

            # Add debug logging
            logger.info(f"Processing file: {file_info['path']} (size: {file_info['size']} bytes, type: {file_info['mime_type']})")
            
            # Read the file and analyze with Gemini's multimodal capabilities
            analysis = await self._analyze_resume_file(
                file_path=file_info["path"], 
                mime_type=file_info["mime_type"]
            )
            return analysis
            
        except Exception as e:
            logger.error(f"Analysis failed: {str(e)}")
            logger.error(traceback.format_exc())
            return {"error": f"Analysis failed: {str(e)}"}

    async def _locate_resume_file(self, session_id: str) -> Optional[Dict]:
        """Find and validate resume file with enhanced checks"""
        # Add debug logging of all files in the upload folder
        try:
            files_in_dir = list(settings.UPLOAD_FOLDER.iterdir())
            logger.debug(f"Files in upload dir: {[f.name for f in files_in_dir]}")
        except Exception as e:
            logger.warning(f"Could not list directory contents: {str(e)}")
        
        for ext, mime_type in self.SUPPORTED_MIME_TYPES.items():
            file_path = settings.UPLOAD_FOLDER / f"{session_id}_resume{ext}"
            logger.debug(f"Checking for file: {file_path}")
            
            if not file_path.exists():
                continue
                
            try:
                file_size = file_path.stat().st_size
                if file_size == 0:
                    logger.warning(f"File exists but is empty: {file_path}")
                    continue
                    
                if file_size > self.MAX_FILE_SIZE:
                    logger.warning(f"File too large: {file_size} bytes")
                    continue
                
                # Add more detailed logging
                logger.info(f"Found valid resume: {file_path} ({file_size} bytes)")
                
                # Test file readability
                with open(file_path, "rb") as f:
                    test_read = f.read(100)  # Try to read first 100 bytes
                    if not test_read:
                        logger.warning(f"File exists but could not read content: {file_path}")
                        continue
                
                return {
                    "path": file_path,
                    "mime_type": mime_type,
                    "size": file_size
                }
            except OSError as e:
                logger.warning(f"File access error: {str(e)}")
                
        logger.warning(f"No valid resume found for session {session_id}")
        return None

    async def _analyze_resume_file(self, file_path: pathlib.Path, mime_type: str) -> Dict:
        """Analyze resume directly using Gemini's multimodal capabilities"""
        try:
            # Read file data
            with open(file_path, "rb") as f:
                file_data = f.read()
            
            # Encode the file as base64
            base64_data = base64.b64encode(file_data).decode('utf-8')
            logger.info(f"Base64 data length: {len(base64_data)} characters")
            
            # Define the analysis prompt
            analysis_prompt = """
            You are a professional resume analyzer. Please analyze this resume in detail and extract the following specific information:

            1. Key skills and technologies (list them individually)
            2. Years of experience (estimate based on work history)
            3. Education details (including degrees, institutions, and years)
            4. Work experience summary
            5. Areas of expertise
            6. An ATS compatibility score (0-100) based on formatting, keywords, and completeness
            7. Three specific suggestions to improve this resume
            
            Format your response as a structured, detailed analysis under clear headings. Include all the information you can find, but don't invent details that aren't present in the resume.
            """
            
            # Use executor to avoid blocking the event loop
            return await asyncio.get_running_loop().run_in_executor(
                None, 
                self._run_multimodal_analysis, 
                analysis_prompt, 
                base64_data, 
                mime_type
            )
            
        except Exception as e:
            logger.error(f"Resume file analysis failed: {str(e)}")
            logger.error(traceback.format_exc())
            raise
    
    def _run_multimodal_analysis(self, prompt: str, base64_data: str, mime_type: str) -> Dict:
        """Execute multimodal analysis with Gemini"""
        try:
            logger.info("Requesting resume analysis from Gemini...")
            
            # Create content parts for the multimodal request
            content_parts = [
                {"text": prompt},
                {
                    "inline_data": {
                        "mime_type": mime_type,
                        "data": base64_data
                    }
                }
            ]
            
            # Configure generation parameters
            generation_config = {
                "temperature": 0.2,
                "candidate_count": 1,
                "max_output_tokens": 4096,
                "top_p": 0.8,
                "top_k": 40
            }
            
            # Call Gemini with multimodal content
            response = self.model.generate_content(
                content_parts,
                generation_config=generation_config
            )
            
            if not response or not response.text:
                raise ValueError("Empty response from Gemini API")
                
            resume_analysis = response.text
            logger.info(f"Resume analysis complete (length: {len(resume_analysis)} chars)")
            
            # Return the narrative analysis
            return {
                "analysis": resume_analysis,
                "format": "narrative"
            }
                
        except Exception as e:
            logger.error(f"Multimodal Gemini processing failed: {str(e)}")
            logger.error(traceback.format_exc())
            raise

    def _cleanup_old_uploads(self, max_age_hours: int = 24, max_files: int = 20):
        """Improved cleanup with age-based removal"""
        now = datetime.now()
        deleted = 0
        
        for item in settings.UPLOAD_FOLDER.iterdir():
            try:
                item_age = datetime.fromtimestamp(item.stat().st_mtime)
                if (now - item_age) > timedelta(hours=max_age_hours):
                    if item.is_file():
                        item.unlink()
                        deleted += 1
                    elif item.is_dir():
                        shutil.rmtree(item)
                        deleted += 1
            except Exception as e:
                logger.warning(f"Failed to delete {item}: {str(e)}")
                
        logger.info(f"Cleaned up {deleted} old files")
        
        # Fallback count-based cleanup if still too many files
        remaining = list(settings.UPLOAD_FOLDER.iterdir())
        if len(remaining) > max_files:
            for item in remaining[:len(remaining)-max_files]:
                try:
                    item.unlink()
                except Exception as e:
                    logger.warning(f"Emergency cleanup failed for {item}: {str(e)}")

    # Add a new method for manual document inspection
    async def inspect_document(self, session_id: str) -> Dict:
        """Inspect document without full processing for debugging"""
        try:
            file_info = await self._locate_resume_file(session_id)
            if not file_info:
                return {"error": "No valid resume found"}
                
            # Basic file metadata
            result = {
                "file_path": str(file_info["path"]),
                "mime_type": file_info["mime_type"],
                "size_bytes": file_info["size"],
                "exists": file_info["path"].exists(),
                "readable": os.access(file_info["path"], os.R_OK)
            }
            
            # Try to read first few bytes
            try:
                with open(file_info["path"], "rb") as f:
                    header = f.read(50)
                    result["header_hex"] = header.hex()
                    result["header_ascii"] = ''.join(chr(b) if 32 <= b < 127 else '.' for b in header)
            except Exception as e:
                result["read_error"] = str(e)
                
            return result
            
        except Exception as e:
            logger.error(f"Document inspection failed: {str(e)}")
            return {"error": f"Inspection failed: {str(e)}"}