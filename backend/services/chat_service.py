from typing import Dict, Any
from services.firebase_service import FirebaseService
from utils.logger import get_logger

logger = get_logger(__name__)

class ChatService:
    def __init__(self, firebase_service: FirebaseService):
        """Initializes ChatService with the injected FirebaseService."""
        self.firebase_service = firebase_service

    def handle_chat(self, doc_id: str, message: str) -> Dict[str, Any]:
        """
        Orchestrates chatting with a document using chat history and Document context.
        """
        # 1. Get document context
        logger.info(f"Retrieving document context for chat on doc: {doc_id}")
        doc = self.firebase_service.get_document(doc_id)
        if not doc:
            raise ValueError("Document not found")
            
        if doc.get("status") != "READY":
            raise ValueError("Document is not ready for chatting")
            
        context = doc.get("extracted_text", "")
        
        # 2. Get chat history
        logger.info(f"Retrieving chat history for doc: {doc_id}")
        history = self.firebase_service.get_chat_history(doc_id)
        
        # 3. Generate response using ADK ChatAgent
        logger.info("Calling ADK ChatAgent to generate response...")
        from agents.chat_agent import run_chat_agent_sync
        response_text = run_chat_agent_sync(
            user_message=message,
            document_context=context,
            chat_history=history
        )
        
        # 4. Save messages
        logger.info("Saving user and assistant messages to history...")
        user_msg = {"role": "user", "content": message}
        assistant_msg = {"role": "assistant", "content": response_text}
        
        self.firebase_service.save_chat_message(doc_id, user_msg)
        self.firebase_service.save_chat_message(doc_id, assistant_msg)
        
        return {
            "reply": response_text
        }
