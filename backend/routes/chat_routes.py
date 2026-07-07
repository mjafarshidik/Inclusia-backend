from flask import Blueprint, request, jsonify, g
from services import chat_service, document_service
from utils.response import success_response, error_response
from utils.auth import firebase_auth_required
from utils.logger import get_logger

logger = get_logger(__name__)
chat_bp = Blueprint('chat_bp', __name__)

@chat_bp.route('/v1/chat', methods=['POST'])
@chat_bp.route('/chat', methods=['POST'])
@firebase_auth_required
def chat():
    data = request.get_json()
    
    if not data:
        return error_response("Invalid JSON data")
        
    doc_id = data.get("doc_id")
    message = data.get("message")
    
    if not doc_id or not message:
        return error_response("doc_id and message are required")
        
    try:
        doc = document_service.get_document(doc_id)
        if not doc:
            return jsonify({"error": "Document not found"}), 404
            
        if doc.get("ownerId") != g.user.uid:
            logger.warning(f"Authorization failure: request_id={g.request_id}, user_uid={g.user.uid}, document_id={doc_id}, endpoint={request.path}")
            return error_response("Permission denied", 403)
            
        result = chat_service.handle_chat(doc_id, message)
        return success_response("Chat successful", result)
    except ValueError as e:
        return error_response(str(e), 400)
    except Exception as e:
        return error_response(f"Failed to process chat: {str(e)}", 500)

