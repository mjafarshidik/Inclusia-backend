import os
import json
import traceback
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from services.firebase_service import FirebaseService
from services.gemini_service import GeminiService
from services.section_service import SectionService
from agents.document_agent import DocumentAgent
from utils.logger import get_logger

logger = get_logger(__name__)

class DocumentProcessingService:
    def __init__(self, firebase_service: FirebaseService):
        """Initializes DocumentProcessingService with the injected FirebaseService."""
        self.firebase_service = firebase_service

    def process_document(self, document_id: str) -> None:
        """
        Orchestrates the complete document processing pipeline using ADK:
        QUEUED -> EXTRACTING -> EXTRACTED -> PROCESSING_AI -> PROCESSING_SECTIONS -> READY / FAILED
        """
        import asyncio
        import os
        from datetime import datetime, timezone
        from google.adk.apps import App
        from google.adk.runners import InMemoryRunner
        from google.genai import types
        from agents.workflow import document_pipeline

        try:
            # 1. Update status = QUEUED
            logger.info(f"queued. document_id: {document_id}")
            now = datetime.now(timezone.utc)
            self.firebase_service.save_document(document_id, {
                "status": "QUEUED",
                "updatedAt": now
            })

            # Ensure GOOGLE_API_KEY is mapped from GEMINI_API_KEY in the environment for ADK
            if "GEMINI_API_KEY" in os.environ and "GOOGLE_API_KEY" not in os.environ:
                os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]
            os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "False"

            # Setup ADK Runner with the sequential document pipeline
            adk_app = App(name="agents", root_agent=document_pipeline)
            runner = InMemoryRunner(app=adk_app)

            async def _run_pipeline():
                # Create session, initialize with document_id in state
                session = await runner.session_service.create_session(
                    app_name="agents",
                    user_id="system",
                    session_id=document_id,
                    state={"document_id": document_id}
                )
                
                # Execute pipeline
                async for event in runner.run_async(
                    user_id="system",
                    session_id=document_id,
                    new_message=types.Content(role="user", parts=[types.Part.from_text(text="Start pipeline")])
                ):
                    pass
                    
                # Load final session state
                updated_session = await runner.session_service.get_session(app_name="agents", session_id=document_id)
                return updated_session.state

            # Run sequential pipeline in event loop
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
            if loop.is_running():
                try:
                    import nest_asyncio
                    nest_asyncio.apply()
                except ImportError:
                    pass
                final_state = loop.run_until_complete(_run_pipeline())
            else:
                final_state = asyncio.run(_run_pipeline())

            # Load results from final state
            summary_analysis = final_state.get("summary_analysis") or {}
            sections = final_state.get("sections") or []

            # 2. Save all data and set status = READY
            logger.info(f"ready. document_id: {document_id}")
            now = datetime.now(timezone.utc)
            self.firebase_service.save_document(document_id, {
                "status": "READY",
                "summary": summary_analysis.get("summary", ""),
                "topics": summary_analysis.get("topics", []),
                "suggested_questions": summary_analysis.get("suggested_questions", []),
                "sections": sections,
                "errorMessage": None,
                "updatedAt": now
            })

        except Exception as e:
            logger.error(f"failed. document_id: {document_id}, error: {str(e)}")
            try:
                now = datetime.now(timezone.utc)
                self.firebase_service.save_document(document_id, {
                    "status": "FAILED",
                    "errorMessage": str(e),
                    "updatedAt": now
                })
            except Exception as db_err:
                logger.error(f"Failed to write FAILED status for {document_id}: {db_err}")

