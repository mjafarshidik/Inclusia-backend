from flask import Blueprint, request, jsonify, g
import threading
from werkzeug.utils import secure_filename
from services import document_service, document_processing_service
from services.document_service import FirebaseUploadError, FirestoreFailureError
from utils.response import success_response, error_response
from utils.validators import is_valid_pdf
from utils.auth import firebase_auth_required

from utils.logger import get_logger
from config import Config
from io import BytesIO

logger = get_logger(__name__)
document_bp = Blueprint('document_bp', __name__)

@document_bp.route('/v1/documents/upload', methods=['POST'])
@firebase_auth_required
def upload_document_v1():
    if 'file' not in request.files:
        return error_response("Missing file", 400)
        
    file = request.files['file']
    if file.filename == '':
        return error_response("Empty file", 400)
        
    if file.content_type != 'application/pdf' or not is_valid_pdf(file.filename):
        return error_response("Invalid MIME type", 400)
        
    file_stream = BytesIO(file.read())
    file_size = file_stream.getbuffer().nbytes
    
    if file_size == 0:
        return error_response("Empty file", 400)
        
    if file_size > 20 * 1024 * 1024:
        return error_response("Oversized file", 413)
        
    filename = secure_filename(file.filename)
    owner_id = g.user.uid
    
    try:
        result = document_service.upload_document(
            file_stream=file_stream,
            filename=filename,
            content_type=file.content_type,
            owner_id=owner_id
        )
        return success_response("Document uploaded successfully", {"id": result["documentId"]}, 201)
    except FirebaseUploadError as e:
        return error_response("Firebase upload failure", 500, details={"error": str(e)})
    except FirestoreFailureError as e:
        return error_response("Firestore failure", 500, details={"error": str(e)})
    except Exception as e:
        return error_response(f"Internal server error: {str(e)}", 500)

@document_bp.route('/v1/documents/<doc_id>/process', methods=['POST'])
@firebase_auth_required
def process_document_v1(doc_id):
    try:
        doc = document_service.get_document(doc_id)
        if not doc:
            return error_response("Document not found", 404)
            
        if doc.get("ownerId") != g.user.uid:
            logger.warning(f"Authorization failure: request_id={g.request_id}, user_uid={g.user.uid}, document_id={doc_id}, endpoint={request.path}")
            return error_response("Permission denied", 403)
            
        # Trigger pipeline asynchronously in a background thread
        thread = threading.Thread(
            target=document_processing_service.process_document,
            args=(doc_id,)
        )
        thread.start()
        
        return success_response(
            message="Processing started",
            data={
                "documentId": doc_id,
                "status": "PROCESSING_AI"
            },
            status_code=200
        )
    except Exception as e:
        return error_response(f"Internal server error: {str(e)}", 500)

@document_bp.route('/v1/documents/<doc_id>', methods=['GET'])
@firebase_auth_required
def get_document_v1(doc_id):
    try:
        doc = document_service.get_document(doc_id)
        if not doc:
            return error_response("Document not found", 404)
            
        if doc.get("ownerId") != g.user.uid:
            logger.warning(f"Authorization failure: request_id={g.request_id}, user_uid={g.user.uid}, document_id={doc_id}, endpoint={request.path}")
            return error_response("Permission denied", 403)
            
        return success_response("Document retrieved successfully", doc)
    except Exception as e:
        return error_response(f"Internal server error: {str(e)}", 500)

@document_bp.route('/v1/documents', methods=['POST'])
@document_bp.route('/documents', methods=['POST'])
@firebase_auth_required
def upload_document():
    if 'file' not in request.files:
        return error_response("No file part in the request")
        
    file = request.files['file']
    if file.filename == '':
        return error_response("No selected file")
        
    if not is_valid_pdf(file.filename):
        return error_response("Invalid file type. Only PDF is allowed")
        
    # Check size
    file_stream = BytesIO(file.read())
    file_size = file_stream.getbuffer().nbytes
    if file_size > Config.MAX_CONTENT_LENGTH:
        return error_response("File too large. Maximum size is 16MB")
        
    filename = secure_filename(file.filename)
    owner_id = g.user.uid
    
    try:
        # Pendelegasian pemrosesan ke document_service
        logger.info(f"Delegating processing for document: {filename}")
        doc_id = document_service.process_and_store_document(
            file_stream=file_stream,
            filename=filename,
            owner_id=owner_id
        )
        return success_response("Document uploaded and processed successfully", {"id": doc_id}, 201)
    except Exception as e:
        logger.error(f"Failed to process document: {str(e)}", exc_info=True)
        return error_response(f"Failed to process document: {str(e)}", 500)


@document_bp.route('/v1/documents', methods=['GET'])
@document_bp.route('/documents', methods=['GET'])
@firebase_auth_required
def get_documents():
    try:
        # Extract pagination parameters with defaults
        page_arg = request.args.get('page', '1')
        page_size_arg = request.args.get('pageSize', '20')
        
        try:
            page = int(page_arg)
        except ValueError:
            page = 1
            
        try:
            page_size = int(page_size_arg)
        except ValueError:
            page_size = 20
            
        if page < 1:
            page = 1
        if page_size < 1:
            page_size = 20
        if page_size > 100:
            page_size = 100
            
        result = document_service.list_documents_paginated(
            owner_id=g.user.uid,
            page=page,
            page_size=page_size
        )
        
        returned_count = len(result["data"])
        logger.info(
            f"documents listed: request_id={g.request_id}, user_uid={g.user.uid}, "
            f"page={page}, page_size={page_size}, returned_count={returned_count}"
        )
        
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Failed to list documents: {str(e)}", exc_info=True)
        return error_response("Internal server error", 500)


@document_bp.route('/documents/<doc_id>', methods=['GET'])
@firebase_auth_required
def get_document(doc_id):
    try:
        doc = document_service.get_document(doc_id)
        if not doc:
            return error_response("Document not found", 404)
            
        if doc.get("ownerId") != g.user.uid:
            logger.warning(f"Authorization failure: request_id={g.request_id}, user_uid={g.user.uid}, document_id={doc_id}, endpoint={request.path}")
            return error_response("Permission denied", 403)
        
        # Don't return the full text to the frontend unless explicitly needed
        doc.pop('extracted_text', None)
        
        return success_response("Document retrieved successfully", {"document": doc})
    except Exception as e:
        return error_response(f"Failed to get document: {str(e)}", 500)

