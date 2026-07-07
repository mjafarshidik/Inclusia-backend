import os
from typing import AsyncGenerator
from datetime import datetime, timezone
from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event

class ExtractionAgent(BaseAgent):
    """Custom ADK Agent that handles PDF downloading and text/asset extraction using MinerU."""
    
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        document_id = ctx.session.state.get("document_id")
        if not document_id:
            raise ValueError("Missing document_id in session state.")
            
        from services import firebase_service
        
        # 1. Fetch the document to get the storage path
        doc = firebase_service.get_document(document_id)
        if not doc:
            raise ValueError("Document not found in Firestore")

        storage_path = doc.get("storagePath")
        if not storage_path:
            raise ValueError("Document has no storagePath configured")

        # 2. Update status = EXTRACTING
        now = datetime.now(timezone.utc)
        firebase_service.save_document(document_id, {
            "status": "EXTRACTING",
            "updatedAt": now
        })

        # 3. Download PDF from Firebase Storage
        try:
            file_stream = firebase_service.download_file(storage_path)
        except Exception as e:
            raise RuntimeError(f"Storage download failure: {str(e)}") from e

        # 4. Extract text via PdfService
        try:
            from services.pdf_service import PdfService
            filename = doc.get("filename", "document.pdf")
            extracted_text = PdfService.extract_text_from_stream(file_stream, filename, document_id)
            if not extracted_text:
                extracted_text = ""
        except Exception as e:
            raise RuntimeError(f"Extraction failure: {str(e)}") from e

        # 5. Save extractedText and update status = EXTRACTED
        now = datetime.now(timezone.utc)
        firebase_service.save_document(document_id, {
            "status": "EXTRACTED",
            "extractedText": extracted_text,
            "extracted_text": extracted_text,  # Compatibility
            "updatedAt": now
        })

        # 6. Save text to session state for summary_agent
        ctx.session.state["extracted_text"] = extracted_text
        yield Event(author=self.name)
