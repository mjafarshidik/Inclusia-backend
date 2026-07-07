import json
from services.gemini_service import GeminiService
from prompts.agent_prompts import DOCUMENT_ANALYSIS_PROMPT
from utils.logger import get_logger

logger = get_logger(__name__)

class DocumentAgent:
    """Agent responsible for analyzing and summarizing documents."""
    
    @staticmethod
    def analyze_document(text: str) -> dict:
        """Analyzes document text and returns summary, topics, and suggested questions."""
        prompt = DOCUMENT_ANALYSIS_PROMPT.format(text=text)
        
        logger.info("DocumentAgent analyzing document...")
        response_text = GeminiService.generate_content(
            prompt=prompt,
            response_mime_type="application/json"
        )
        
        try:
            return json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from DocumentAgent: {e}")
            # Fallback format
            return {
                "summary": "Failed to generate summary.",
                "topics": [],
                "suggested_questions": []
            }
