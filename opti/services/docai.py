# # """
# # Google Document AI service for resume parsing and summarization
# # """
# # import asyncio
# # import pathlib
# # import traceback
# # from google.cloud import documentai_v1 as documentai
# # import shutil
# # from ..config import settings
# # from ..utils.logging_config import setup_logger

# # # Use centralized logger
# # logger = setup_logger("docai-service")

# # class DocumentAIService:
# #     """Service for processing documents using Google Document AI"""
    
# #     def __init__(self):
# #         """Initialize the Document AI service with credentials from settings"""
# #         # Check if Document AI settings are configured
# #         self.is_configured = False
        
# #         if not (settings.GOOGLE_PROJECT_ID and settings.DOCAI_LOCATION and settings.DOCAI_SUMMARIZER_PROCESSOR_ID):
# #             missing_config = []
# #             if not settings.GOOGLE_PROJECT_ID: missing_config.append("GOOGLE_PROJECT_ID")
# #             if not settings.DOCAI_LOCATION: missing_config.append("DOCAI_LOCATION")
# #             if not settings.DOCAI_SUMMARIZER_PROCESSOR_ID: missing_config.append("DOCAI_SUMMARIZER_PROCESSOR_ID")
            
# #             logger.warning(f"Document AI service not fully configured. Missing: {', '.join(missing_config)}")
# #             return
            
# #         try:
# #             # Initialize Document AI client
# #             client_options = {"api_endpoint": f"{settings.DOCAI_LOCATION}-documentai.googleapis.com"}
# #             self.client = documentai.DocumentProcessorServiceClient(client_options=client_options)
            
# #             # Store configuration
# #             self.project_id = settings.GOOGLE_PROJECT_ID
# #             self.location = settings.DOCAI_LOCATION
# #             self.processor_id = settings.DOCAI_SUMMARIZER_PROCESSOR_ID
            
# #             self.is_configured = True
# #             logger.info(f"Document AI service initialized for processor: {self.processor_id}")
# #         except Exception as e:
# #             logger.error(f"Failed to initialize Document AI service: {e}")
# #             logger.error(traceback.format_exc())
            
# #     async def summarize_resume(self, session_id: str) -> str:
# #         """
# #         Analyze and summarize a resume using Document AI
        
# #         Args:
# #             session_id (str): The unique session identifier to find the resume file
            
# #         Returns:
# #             str: Summary of the resume
# #         """
# #         if not self.is_configured:
# #             return "Resume analysis is not available because the Document AI service is not properly configured."
            
# #         # Clean up old files if needed
# #         try:
# #             self._cleanup_old_uploads()
# #         except Exception as e:
# #             logger.error(f"Error during upload directory cleanup: {e}")
# #             # Continue processing even if cleanup fails
        
# #         found_file_path = None
# #         file_mime_type = None
        
# #         try:
# #             # Find the uploaded resume file
# #             supported_formats = {
# #                 '.pdf': 'application/pdf',
# #                 '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
# #                 # Add other Document AI supported types if needed
# #             }
            
# #             for ext, mime_type in supported_formats.items():
# #                 potential_path = settings.UPLOAD_FOLDER / f"{session_id}_resume{ext}"
# #                 if potential_path.is_file():
# #                     found_file_path = potential_path
# #                     file_mime_type = mime_type
# #                     break

# #             if not found_file_path:
# #                 logger.warning(f"No resume file found for session: {session_id}")
# #                 return "I could not find an uploaded resume to analyze. Please upload it first (PDF or DOCX preferred)."

# #             logger.info(f"Found resume file: {found_file_path} (Type: {file_mime_type})")

# #             # Process with Document AI
# #             document_result = await self._process_document(found_file_path, file_mime_type)
            
# #             # Extract summary from result
# #             summary = document_result.text.strip()
            
# #             if not summary:
# #                 logger.warning(f"Document AI returned an empty summary")
# #                 return "I was able to process the resume file, but couldn't generate a useful summary."

# #             logger.info(f"Received summary from Document AI ({len(summary)} chars)")
# #             return f"Here is a summary of the resume:\n\n{summary}"
            
# #         except Exception as e:
# #             logger.error(f"Error analyzing resume: {str(e)}")
# #             logger.error(traceback.format_exc())
# #             return f"I encountered an error while analyzing the resume: {str(e)}"
    
# #     async def _process_document(self, file_path: pathlib.Path, mime_type: str) -> documentai.Document:
# #         """
# #         Process a document with Document AI
        
# #         Args:
# #             file_path (pathlib.Path): Path to the document file
# #             mime_type (str): MIME type of the document
            
# #         Returns:
# #             documentai.Document: The processed document
# #         """
# #         try:
# #             # Construct processor resource name
# #             processor_name = self.client.processor_path(
# #                 self.project_id, self.location, self.processor_id
# #             )
            
# #             # Read file content
# #             with open(file_path, "rb") as file:
# #                 content = file.read()
                
# #             # Create raw document
# #             raw_document = documentai.RawDocument(content=content, mime_type=mime_type)
            
# #             # Configure the process request
# #             request = documentai.ProcessRequest(
# #                 name=processor_name,
# #                 raw_document=raw_document,
# #             )
            
# #             logger.info(f"Sending document to processor: {processor_name}")
            
# #             # Process document in executor to avoid blocking
# #             loop = asyncio.get_running_loop()
# #             result = await loop.run_in_executor(None, self.client.process_document, request)
            
# #             logger.info("Received response from Document AI")
# #             return result.document
            
# #         except Exception as e:
# #             logger.error(f"Error in Document AI processing: {e}")
# #             logger.error(traceback.format_exc())
# #             raise
    
# #     def _cleanup_old_uploads(self):
# #         """Remove old files from the uploads directory if there are too many"""
# #         upload_folder = settings.UPLOAD_FOLDER
        
# #         if upload_folder.exists() and upload_folder.is_dir():
# #             items = list(upload_folder.iterdir())
# #             if len(items) >= 10:
# #                 logger.warning(f"Uploads directory reached {len(items)} items. Cleaning up...")
# #                 for item_path in items:
# #                     try:
# #                         if item_path.is_file():
# #                             item_path.unlink()
# #                             logger.info(f"Deleted file: {item_path}")
# #                         elif item_path.is_dir():
# #                             shutil.rmtree(item_path)
# #                             logger.info(f"Deleted directory: {item_path}")
# #                     except Exception as e:
# #                         logger.error(f"Error deleting item {item_path}: {e}")
# #                 logger.info("Uploads directory cleanup complete") 


# import asyncio
# import pathlib
# import traceback
# from google import genai
# from google.genai.types import HttpOptions, Part
# import shutil
# from ..config import settings
# from ..utils.logging_config import setup_logger

# logger = setup_logger("gemini-service")

# class GeminiService:
#     """Service for processing resumes using Vertex AI Gemini models"""

#     def __init__(self):
#         self.is_configured = False
#         if not (settings.GOOGLE_PROJECT_ID and settings.GOOGLE_CLOUD_LOCATION):
#             missing = []
#             if not settings.GOOGLE_PROJECT_ID: missing.append("GOOGLE_CLOUD_PROJECT")
#             if not settings.GOOGLE_CLOUD_LOCATION: missing.append("GOOGLE_CLOUD_LOCATION")
#             logger.warning(f"Gemini service not configured. Missing: {', '.join(missing)}")
#             return

#         try:
#             # Initialize Gen AI client for Vertex AI
#             client_opts = HttpOptions(api_version="v1")
#             self.client = genai.Client(http_options=client_opts)
#             self.model = settings.GEMINI_MODEL_ID or "gemini-2.5-flash"  # default model
#             self.is_configured = True
#             logger.info(f"Gemini service initialized with model: {self.model}")  # :contentReference[oaicite:5]{index=5}
#         except Exception as e:
#             logger.error(f"Failed to initialize Gemini client: {e}")
#             logger.error(traceback.format_exc())

#     async def summarize_resume(self, session_id: str) -> str:
#         """Summarize a resume file using Gemini"""
#         if not self.is_configured:
#             return "Resume summarization service is not configured."

#         try:
#             self._cleanup_old_uploads()
#         except Exception as e:
#             logger.error(f"Error cleaning uploads: {e}")

#         # Locate the uploaded resume
#         supported = {'.pdf': 'application/pdf', '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}
#         file_path = None
#         mime_type = None
#         for ext, mtype in supported.items():
#             path = settings.UPLOAD_FOLDER / f"{session_id}_resume{ext}"
#             if path.is_file():
#                 file_path, mime_type = path, mtype
#                 break

#         if not file_path:
#             logger.warning(f"No resume found for session {session_id}")
#             return "Please upload a PDF or DOCX resume first."

#         logger.info(f"Using file {file_path} for summarization")  # :contentReference[oaicite:6]{index=6}

#         try:
#             # Prepare multipart content: file part then prompt
#             file_part = Part.from_path(str(file_path), mime_type=mime_type)  # :contentReference[oaicite:7]{index=7}
#             prompt = (
#                 "You are a professional resume summarization specialist. "
#                 "Provide a concise summary highlighting skills, experience, and achievements."
#             )
#             # Send request to Gemini
#             response = self.client.models.generate_content(
#                 model=self.model,
#                 contents=[file_part, prompt]
#             )  # :contentReference[oaicite:8]{index=8}

#             summary = response.text.strip()
#             if not summary:
#                 logger.warning("Gemini returned empty summary")
#                 return "Gemini processed the resume but did not return a summary."

#             logger.info(f"Received summary ({len(summary)} chars)")
#             return f"Resume Summary:\n\n{summary}"

#         except Exception as e:
#             logger.error(f"Error summarizing resume: {e}")
#             logger.error(traceback.format_exc())
#             return f"Error during summarization: {e}"

#     def _cleanup_old_uploads(self):
#         """Cleanup logic unchanged"""
#         upload_folder = settings.UPLOAD_FOLDER
#         if upload_folder.exists() and upload_folder.is_dir():
#             items = list(upload_folder.iterdir())
#             if len(items) >= 10:
#                 logger.warning(f"Cleaning up {len(items)} old items")
#                 for item in items:
#                     try:
#                         if item.is_file():
#                             item.unlink()
#                         else:
#                             shutil.rmtree(item)
#                     except Exception as e:
#                         logger.error(f"Failed to delete {item}: {e}")
#                 logger.info("Cleanup complete")


# import asyncio
# import pathlib
# import traceback
# import shutil
# from io import BytesIO
# from pdf2image import convert_from_path
# from PIL import Image
# from google.cloud import documentai_v1 as documentai
# from google.cloud import vision
# from ..config import settings
# from ..utils.logging_config import setup_logger
# from google.oauth2 import service_account

# logger = setup_logger("docai-vision-service")
# creds = service_account.Credentials.from_service_account_file(
#     r"D:\prepzo\prepzo-backend\flask-prepzo-backend\opti\cred.json"
# )
# class ResumeAnalysisService:
#     """Service for parsing and analyzing resumes using Document AI and Vision API"""

#     def __init__(self):
#         """Initialize clients and configuration"""
#         self.is_configured = False
#         missing = []
#         # Document AI config
#         if not (settings.GOOGLE_PROJECT_ID and settings.DOCAI_LOCATION and settings.DOCAI_LAYOUT_PROCESSOR_ID):
#             if not settings.GOOGLE_PROJECT_ID: missing.append("GOOGLE_PROJECT_ID")
#             if not settings.DOCAI_LOCATION: missing.append("DOCAI_LOCATION")
#             if not settings.DOCAI_LAYOUT_PROCESSOR_ID: missing.append("DOCAI_LAYOUT_PROCESSOR_ID")
#         # Vision API requires only credentials
#         if missing:
#             logger.warning(f"ResumeAnalysisService missing config: {', '.join(missing)}")
#             return

#         # Document AI client
#         try:
#             endpoint = f"{settings.DOCAI_LOCATION}-documentai.googleapis.com"


#             self.dai_client = documentai.DocumentProcessorServiceClient(
#                 client_options={"api_endpoint": endpoint},
#                 credentials=creds
#             )
#             self.layout_processor = self.dai_client.processor_path(
#                 settings.GOOGLE_PROJECT_ID,
#                 settings.DOCAI_LOCATION,
#                 settings.DOCAI_LAYOUT_PROCESSOR_ID,
#             )
#             # Vision client
#             # self.vision_client = vision.ImageAnnotatorClient()

#             self.is_configured = True
#             logger.info("ResumeAnalysisService initialized successfully")
#         except Exception as e:
#             logger.error(f"Error initializing services: {e}")
#             logger.error(traceback.format_exc())

#     async def analyze_resume(self, session_id: str) -> dict:
#         """
#         End-to-end resume analysis:
#           - Document AI layout parsing
#           - Vision API visual analysis
#           - Section, formatting, ATS scoring
#         Returns a JSON report
#         """
#         if not self.is_configured:
#             return {"error": "Service not configured"}

#         # cleanup older uploads
#         try:
#             self._cleanup_old_uploads()
#         except Exception:
#             logger.exception("Cleanup failed")

#         # locate resume file
#         supported = {
#             '.pdf': 'application/pdf',
#             '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
#         }
#         file_path = None
#         mime = None
#         for ext, m in supported.items():
#             path = settings.UPLOAD_FOLDER / f"{session_id}_resume{ext}"
#             if path.is_file():
#                 file_path, mime = path, m
#                 break
#         if not file_path:
#             logger.warning("No resume found to analyze")
#             return {"error": "No resume uploaded"}

#         # 1) Layout parsing
#         layout = await asyncio.get_running_loop().run_in_executor(
#             None, self._process_layout, file_path, mime
#         )

#         # 2) Convert first page to image
#         image = self._convert_first_page(file_path)
#         # 3) Visual analysis
#         visuals = self._analyze_visuals(image)

#         # 4) Build report
#         report = {
#             "sections": self._identify_sections(layout),
#             "formatting": self._check_formatting(layout),
#             "logo_analysis": self._validate_logos(visuals["logos"]),
#             "color_score": self._calculate_color_score(visuals["dominant_colors"]),
#             "ats_score": self._calculate_ats_score(layout)
#         }
#         return report

#     def _process_layout(self, file_path: pathlib.Path, mime_type: str) -> dict:
#         """Call Document AI to extract layout"""
#         with open(file_path, "rb") as f:
#             raw = documentai.RawDocument(content=f.read(), mime_type=mime_type)
#         request = documentai.ProcessRequest(name=self.layout_processor, raw_document=raw)
#         result = self.dai_client.process_document(request)
#         doc = result.document
#         layout = {"pages": []}
#         for page in doc.pages:
#             blocks = []
#             for blk in page.blocks:
#                 blocks.append({
#                     "text": blk.layout.text_anchor.content,
#                     "bbox": [(v.x, v.y) for v in blk.layout.bounding_poly.vertices]
#                 })
#             layout["pages"].append({"blocks": blocks})
#         return layout

#     def _convert_first_page(self, pdf_path: pathlib.Path) -> Image.Image:
#         images = convert_from_path(str(pdf_path), dpi=200, first_page=1, last_page=1)
#         return images[0]

#     def _analyze_visuals(self, image: Image.Image) -> dict:
#         buffer = BytesIO()
#         image.save(buffer, format="PNG")
#         img = vision.Image(content=buffer.getvalue())
#         # logos
#         logos_resp = self.vision_client.logo_detection(image=img)
#         logos = [{
#             "name": a.description,
#             "score": a.score,
#             "bbox": [(v.x, v.y) for v in a.bounding_poly.vertices]
#         } for a in logos_resp.logo_annotations]
#         # colors
#         props = self.vision_client.image_properties(image=img)
#         colors = [{
#             "rgb": (c.color.red, c.color.green, c.color.blue),
#             "score": c.score,
#             "pixel_fraction": c.pixel_fraction
#         } for c in props.image_properties_annotation.dominant_colors.colors]
#         return {"logos": logos, "dominant_colors": colors}

#     def _identify_sections(self, layout: dict, gap: float = 20.0) -> list:
#         sections = []
#         for pi, pg in enumerate(layout["pages"]):
#             prev_y = None
#             for bi, blk in enumerate(pg["blocks"]):
#                 y = blk["bbox"][0][1]
#                 if prev_y and y - prev_y > gap:
#                     sections.append({"page": pi, "block": bi})
#                 prev_y = y
#         return sections

#     def _check_formatting(self, layout: dict) -> dict:
#         # stub for token-level formatting
#         return {"consistent": True}

#     def _validate_logos(self, logos: list) -> dict:
#         header = [l for l in logos if l["bbox"][0][1] < 100]
#         return {"total": len(logos), "header": len(header)}

#     def _calculate_color_score(self, colors: list) -> float:
#         return sum(c["score"] for c in colors) / max(1, len(colors))

#     def _calculate_ats_score(self, layout: dict) -> int:
#         # simple deduction
#         score = 100
#         return max(0, score - 10)

#     def _cleanup_old_uploads(self):
#         folder = settings.UPLOAD_FOLDER
#         if folder.exists():
#             items = list(folder.iterdir())
#             if len(items) > 10:
#                 for item in items:
#                     try:
#                         if item.is_file(): item.unlink()
#                         else: shutil.rmtree(item)
#                     except: pass
#                 logger.info("Old uploads cleaned")



import asyncio
import pathlib
import traceback
import shutil
from google.cloud import documentai_v1 as documentai
from ..config import settings
from ..utils.logging_config import setup_logger
from google.oauth2 import service_account

logger = setup_logger("docai-service")
# Load credentials for Document AI
creds = service_account.Credentials.from_service_account_file(
    r"D:\prepzo\prepzo-backend\flask-prepzo-backend\opti\cred.json"
)

class ResumeAnalysisService:
    """Service for parsing and analyzing resumes using Document AI"""

    def __init__(self):
        """Initialize clients and configuration"""
        self.is_configured = False
        missing = []
        if not (settings.GOOGLE_PROJECT_ID and settings.DOCAI_LOCATION and settings.DOCAI_LAYOUT_PROCESSOR_ID):
            if not settings.GOOGLE_PROJECT_ID: missing.append("GOOGLE_PROJECT_ID")
            if not settings.DOCAI_LOCATION: missing.append("DOCAI_LOCATION")
            if not settings.DOCAI_LAYOUT_PROCESSOR_ID: missing.append("DOCAI_LAYOUT_PROCESSOR_ID")

        if missing:
            logger.warning(f"ResumeAnalysisService missing config: {', '.join(missing)}")
            return

        try:
            endpoint = f"{settings.DOCAI_LOCATION}-documentai.googleapis.com"
            self.client = documentai.DocumentProcessorServiceClient(
                client_options={"api_endpoint": endpoint},
                credentials=creds
            )
            self.processor_name = self.client.processor_path(
                settings.GOOGLE_PROJECT_ID,
                settings.DOCAI_LOCATION,
                settings.DOCAI_LAYOUT_PROCESSOR_ID
            )
            self.is_configured = True
            logger.info("ResumeAnalysisService initialized successfully with Document AI")
        except Exception as e:
            logger.error(f"Error initializing Document AI client: {e}")
            logger.error(traceback.format_exc())

    async def analyze_resume(self, session_id: str) -> dict:
        """
        End-to-end resume analysis using Document AI only:
          - Layout parsing
          - Section detection
          - Formatting & ATS scoring
        """
        if not self.is_configured:
            return {"error": "Service not configured"}

        # Cleanup old uploads
        try:
            self._cleanup_old_uploads()
        except Exception:
            logger.exception("Cleanup failed")

        # Locate resume file
        supported = {
            '.pdf': 'application/pdf',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        }
        file_path = None
        mime = None
        for ext, m in supported.items():
            path = settings.UPLOAD_FOLDER / f"{session_id}_resume{ext}"
            if path.is_file():
                file_path, mime = path, m
                break
        if not file_path:
            logger.warning("No resume found to analyze")
            return {"error": "No resume uploaded"}

        # 1) Parse layout via Document AI
        layout = await asyncio.get_running_loop().run_in_executor(
            None, self._process_layout, file_path, mime
        )

        # 2) Build report with structural insights
        report = {
            "sections": self._identify_sections(layout),
            "formatting": self._check_formatting(layout),
            "ats_score": self._calculate_ats_score(layout)
        }
        return report

    def _process_layout(self, file_path: pathlib.Path, mime_type: str) -> dict:
        """Call Document AI to extract text blocks and bounding boxes"""
        with open(file_path, "rb") as f:
            raw = documentai.RawDocument(content=f.read(), mime_type=mime_type)
        request = documentai.ProcessRequest(name=self.processor_name, raw_document=raw)
        result = self.client.process_document(request)
        doc = result.document

        layout = {"pages": []}
        for page in doc.pages:
            blocks = []
            for blk in page.blocks:
                blocks.append({
                    "text": blk.layout.text_anchor.content,
                    "bbox": [(v.x, v.y) for v in blk.layout.bounding_poly.vertices]
                })
            layout["pages"].append({"blocks": blocks})
        return layout

    def _identify_sections(self, layout: dict, gap: float = 20.0) -> list:
        """Detect section breaks by large vertical gaps between blocks"""
        sections = []
        for pi, pg in enumerate(layout["pages"]):
            prev_y = None
            for bi, blk in enumerate(pg["blocks"]):
                y = blk["bbox"][0][1]
                if prev_y is not None and y - prev_y > gap:
                    sections.append({"page": pi, "block": bi})
                prev_y = y
        return sections

    # def _check_formatting(self, layout: dict) -> dict:
    #     """Stub: analyze text styles and font sizes (if available)"""
    #     # Document AI v1 layout does not expose font_size by default
    #     # Extend here if using custom processor
    #     return {"consistent": True}

    def _calculate_ats_score(self, layout: dict) -> int:
        """Heuristic ATS scoring based on structure"""
        score = 100
        # e.g., penalize missing sections or overlapping blocks
        # Add custom rules here
        return max(0, score)

    def _cleanup_old_uploads(self):
        """Remove old files if uploads folder exceeds threshold"""
        folder = settings.UPLOAD_FOLDER
        if folder.exists() and folder.is_dir():
            items = list(folder.iterdir())
            if len(items) > 10:
                for item in items:
                    try:
                        if item.is_file():
                            item.unlink()
                        else:
                            shutil.rmtree(item)
                    except Exception:
                        pass
                logger.info("Old uploads cleaned")
