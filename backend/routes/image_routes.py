import os
import uuid
import threading
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, g

from utils.logger import get_logger
from services.gemini_service import GeminiService
from services import firebase_service
from utils.response import error_response
from utils.auth import firebase_auth_required

logger = get_logger(__name__)
image_bp = Blueprint('image_bp', __name__)

ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def background_process_image(image_id, image_path, filename, content_type, owner_id, host_url, unique_filename):
    db = firebase_service.db
    doc_ref = db.collection("uploaded_images").document(image_id)
    
    def update_progress(progress, current_step, status="PROCESSING", extra_data=None):
        now = datetime.now(timezone.utc)
        payload = {
            "status": status,
            "progress": progress,
            "currentStep": current_step,
            "updatedAt": now
        }
        if extra_data:
            payload.update(extra_data)
        try:
            doc_ref.set(payload, merge=True)
            logger.info(f"Image {image_id} progress updated to {progress}% ({current_step})")
        except Exception as e:
            logger.error(f"Failed to update progress in Firestore for image {image_id}: {e}")

    try:
        # Step 1: Uploading image (10%)
        update_progress(10, "Uploading image")
        
        # Upload to Firebase Storage
        try:
            with open(image_path, 'rb') as f:
                destination_path = f"uploaded_images/{unique_filename}"
                gcs_url = firebase_service.upload_file(f, destination_path, content_type=content_type)
        except Exception as e:
            logger.warning(f"GCS upload failed for image {image_id}, falling back to local URL: {e}")
            gcs_url = f"{host_url.rstrip('/')}/static/uploaded_images/{unique_filename}"
            
        # Step 2: Preparing AI (30%)
        update_progress(30, "Preparing AI", extra_data={"imageUrl": gcs_url})
        
        # Step 3: Analyzing image (60%)
        update_progress(60, "Analyzing image")
        
        accessibility_result = GeminiService.interpret_image_accessibility(
            image_path=image_path,
            context_before=None,
            context_after=None
        )
        
        # Step 4: Saving accessibility result (85%)
        update_progress(85, "Saving accessibility result")
        
        # Step 5: Completed (100%)
        update_progress(100, "Completed", status="READY", extra_data={
            "accessibility_content": {
                "alt_text_totally_blind": accessibility_result.get("alt_text_totally_blind", ""),
                "visual_explanation_deaf": accessibility_result.get("visual_explanation_deaf", "")
            }
        })
        logger.info(f"Image {image_id} processing completed successfully.")
        
    except Exception as e:
        logger.error(f"Error in background image processing for image {image_id}: {e}")
        update_progress(100, "Failed", status="FAILED", extra_data={
            "errorMessage": str(e)
        })

@image_bp.route('/v1/images/process', methods=['POST'])
@firebase_auth_required
def process_image():
    try:
        if 'file' not in request.files:
            return error_response("No file part", 400)
            
        file = request.files['file']
        if file.filename == '':
            return error_response("No selected file", 400)
            
        if not allowed_file(file.filename):
            return error_response("Invalid file format. Only .jpg, .jpeg, and .png are allowed.", 400)
            
        # Read file data to check length
        file_data = file.read()
        file_size = len(file_data)
        
        if file_size == 0:
            return error_response("Empty file", 400)
            
        if file_size > 16 * 1024 * 1024:
            return error_response("Oversized file. Maximum limit is 16MB.", 413)
            
        # Unique filename generation using UUID
        image_id = str(uuid.uuid4())
        ext = file.filename.rsplit('.', 1)[1].lower()
        unique_filename = f"{image_id}.{ext}"
        
        # Ensure upload folder exists
        upload_dir = os.path.join('static', 'uploaded_images')
        os.makedirs(upload_dir, exist_ok=True)
        
        image_path = os.path.join(upload_dir, unique_filename)
        
        # Save file to path locally first
        with open(image_path, 'wb') as f:
            f.write(file_data)
            
        logger.info(f"Saved uploaded image locally to {image_path}")
        
        # Prepare initial Firestore metadata
        now = datetime.now(timezone.utc)
        base_url = request.host_url.rstrip('/')
        image_url = f"{base_url}/static/uploaded_images/{unique_filename}"
        
        initial_data = {
            "id": image_id,
            "ownerId": g.user.uid,
            "filename": file.filename,
            "status": "PROCESSING",
            "progress": 0,
            "currentStep": "Queued",
            "imageUrl": image_url,
            "createdAt": now,
            "updatedAt": now
        }
        
        # Save to Firestore
        firebase_service.db.collection("uploaded_images").document(image_id).set(initial_data)
        logger.info(f"Created initial Firestore metadata for image {image_id}")
        
        # Start background worker thread
        thread = threading.Thread(
            target=background_process_image,
            args=(image_id, image_path, file.filename, file.content_type, g.user.uid, request.host_url, unique_filename)
        )
        thread.start()
        
        return jsonify({
            "success": True,
            "message": "Image processing started",
            "data": {
                "id": image_id,
                "status": "PROCESSING",
                "progress": 0
            }
        }), 202
        
    except Exception as e:
        logger.error(f"Error starting image processing: {e}")
        return error_response(f"Internal server error: {str(e)}", 500)

@image_bp.route('/v1/images', methods=['GET'])
@firebase_auth_required
def list_images():
    try:
        user_uid = g.user.uid
        # Query Firestore collection "uploaded_images" where ownerId == user_uid
        docs_stream = (
            firebase_service.db.collection("uploaded_images")
            .where("ownerId", "==", user_uid)
            .stream()
        )
        
        results = []
        for doc in docs_stream:
            doc_dict = doc.to_dict() or {}
            doc_dict['id'] = doc.id
            
            # Convert datetimes to ISO strings
            for k in ['createdAt', 'updatedAt']:
                if k in doc_dict and doc_dict[k]:
                    try:
                        if hasattr(doc_dict[k], 'isoformat'):
                            doc_dict[k] = doc_dict[k].isoformat()
                    except Exception:
                        pass
                        
            results.append(doc_dict)
            
        logger.info(f"Listed {len(results)} images for user {user_uid}")
        return jsonify({
            "success": True,
            "data": results
        }), 200
    except Exception as e:
        logger.error(f"Error listing uploaded images: {e}")
        return error_response(f"Internal server error: {str(e)}", 500)

@image_bp.route('/v1/images/<image_id>', methods=['GET'])
@firebase_auth_required
def get_image(image_id):
    try:
        doc_ref = firebase_service.db.collection("uploaded_images").document(image_id).get()
        if not doc_ref.exists:
            return error_response("Image not found", 404)
            
        doc_dict = doc_ref.to_dict() or {}
        if doc_dict.get("ownerId") != g.user.uid:
            logger.warning(f"Authorization failure: request_id={g.request_id}, user_uid={g.user.uid}, image_id={image_id}, endpoint={request.path}")
            return error_response("Permission denied", 403)
        doc_dict['id'] = doc_ref.id
        
        # Convert datetimes to ISO strings
        for k in ['createdAt', 'updatedAt']:
            if k in doc_dict and doc_dict[k]:
                try:
                    if hasattr(doc_dict[k], 'isoformat'):
                        doc_dict[k] = doc_dict[k].isoformat()
                except Exception:
                    pass
                    
        return jsonify({
            "success": True,
            "data": doc_dict
        }), 200
    except Exception as e:
        logger.error(f"Error retrieving image {image_id}: {e}")
        return error_response(f"Internal server error: {str(e)}", 500)
