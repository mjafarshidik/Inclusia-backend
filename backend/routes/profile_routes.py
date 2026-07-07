from flask import Blueprint, jsonify, g, request
from utils.auth import firebase_auth_required
from services import user_service
from utils.logger import get_logger
from utils.validators import normalize_accessibility_mode
from utils.response import error_response

logger = get_logger(__name__)
profile_bp = Blueprint('profile_bp', __name__)

@profile_bp.route('/v1/profile', methods=['GET'])
@firebase_auth_required
def get_profile():
    request_id = g.request_id
    user_uid = g.user.uid
    try:
        profile = user_service.get_profile(user_uid)
        
        # Default accessibilityMode to None if user does not exist in collection
        accessibility_mode = None
        email = g.user.email
        display_name = g.user.name
        photo_url = g.user.picture
        if profile:
            accessibility_mode = profile.get("accessibilityMode")
            if not email:
                email = profile.get("email")
            if not display_name:
                display_name = profile.get("displayName")
            if not photo_url:
                photo_url = profile.get("photoUrl")
            
        logger.info(f"profile fetched: request_id={request_id}, user_uid={user_uid}, accessibility_mode={accessibility_mode}")
        
        return jsonify({
            "success": True,
            "data": {
                "uid": user_uid,
                "email": email,
                "name": display_name,
                "displayName": display_name,
                "picture": photo_url,
                "photoUrl": photo_url,
                "accessibilityMode": accessibility_mode
            }
        }), 200
    except Exception as e:
        logger.error(f"profile fetch failed: request_id={request_id}, user_uid={user_uid}, error={str(e)}")
        return error_response("Internal server error", 500)

@profile_bp.route('/v1/profile/accessibility', methods=['POST'])
@firebase_auth_required
def set_accessibility_profile():
    request_id = g.request_id
    user_uid = g.user.uid
    
    # 1. Validation for Missing body
    data = request.get_json(silent=True)
    if data is None:
        logger.warning(f"profile update failed: request_id={request_id}, user_uid={user_uid}, accessibility_mode=None, reason=Missing body")
        return error_response("Missing body", 400)
        
    # 2. Validation for Missing mode
    raw_mode = data.get("mode")
    if raw_mode is None:
        logger.warning(f"profile update failed: request_id={request_id}, user_uid={user_uid}, accessibility_mode=None, reason=Missing mode")
        return error_response("Missing mode", 400)
        
    # 3. Validation for Invalid mode
    mode = normalize_accessibility_mode(raw_mode)
    if mode is None:
        logger.warning(f"profile update failed: request_id={request_id}, user_uid={user_uid}, accessibility_mode={raw_mode}, reason=Invalid mode")
        return error_response(f"Invalid accessibility mode: {raw_mode}", 400)
        
    try:
        action = user_service.update_profile(
            uid=user_uid,
            email=g.user.email,
            display_name=g.user.name,
            photo_url=g.user.picture,
            update_data={"accessibilityMode": mode}
        )
        
        # Emit structured log
        if action == "created":
            logger.info(f"profile created: request_id={request_id}, user_uid={user_uid}, accessibility_mode={mode}")
        else:
            logger.info(f"profile updated: request_id={request_id}, user_uid={user_uid}, accessibility_mode={mode}")
            
        return jsonify({"success": True, "message": f"Profile {action} successfully"}), 200
        
    except Exception as e:
        logger.error(f"profile update failed: request_id={request_id}, user_uid={user_uid}, accessibility_mode={mode}, error={str(e)}")
        return error_response("Internal server error", 500)

@profile_bp.route('/v1/user/profile', methods=['PUT'])
@firebase_auth_required
def update_user_profile():
    request_id = g.request_id
    user_uid = g.user.uid
    
    data = request.get_json(silent=True)
    if data is None:
        return error_response("Missing body", 400)
        
    raw_mode = data.get("accessibilityMode") or data.get("mode") or data.get("accessibility_mode")
    if not raw_mode:
        return error_response("Missing accessibility mode", 400)
        
    # Standardize input
    mode = normalize_accessibility_mode(raw_mode)
    if mode is None:
        logger.warning(f"profile update failed: request_id={request_id}, user_uid={user_uid}, accessibility_mode={raw_mode}, reason=Invalid mode")
        return error_response(f"Invalid accessibility mode: {raw_mode}", 400)
        
    try:
        action = user_service.update_profile(
            uid=user_uid,
            email=g.user.email,
            display_name=g.user.name,
            photo_url=g.user.picture,
            update_data={"accessibilityMode": mode}
        )
        
        logger.info(f"profile PUT updated: request_id={request_id}, user_uid={user_uid}, accessibility_mode={mode}")
        return jsonify({
            "success": True, 
            "message": "Profile updated successfully",
            "data": {
                "uid": user_uid,
                "accessibilityMode": mode
            }
        }), 200
        
    except Exception as e:
        logger.error(f"profile PUT update failed: request_id={request_id}, user_uid={user_uid}, error={str(e)}")
        return error_response("Internal server error", 500)

@profile_bp.route('/v1/profile/avatar', methods=['POST'])
@firebase_auth_required
def upload_avatar():
    request_id = g.request_id
    user_uid = g.user.uid
    
    if 'file' not in request.files:
        return error_response("No file part", 400)
        
    file = request.files['file']
    if file.filename == '':
        return error_response("No selected file", 400)
        
    allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in allowed_extensions:
        return error_response("Invalid file type. Only PNG, JPG, JPEG, GIF, and WEBP are allowed.", 400)
        
    from io import BytesIO
    file_stream = BytesIO(file.read())
    file_size = file_stream.getbuffer().nbytes
    if file_size > 5 * 1024 * 1024:
        return error_response("File too large. Maximum size is 5MB.", 413)
        
    try:
        import uuid
        from services import firebase_service
        
        unique_id = str(uuid.uuid4())
        destination = f"avatars/{user_uid}_{unique_id}.{ext}"
        
        file_stream.seek(0)
        
        content_type = f"image/{ext}" if ext != 'jpg' else 'image/jpeg'
        photo_url = firebase_service.upload_file(
            file_stream,
            destination,
            content_type=content_type
        )
        
        user_service.update_profile(
            uid=user_uid,
            email=None,
            display_name=None,
            photo_url=photo_url,
            update_data={"photoUrl": photo_url}
        )
        
        logger.info(f"Avatar uploaded successfully: request_id={request_id}, photo_url={photo_url}")
        
        return jsonify({
            "success": True,
            "message": "Avatar uploaded successfully",
            "data": {
                "photoUrl": photo_url
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Avatar upload failed: request_id={request_id}, error={str(e)}")
        return error_response(f"Avatar upload failed: {str(e)}", 500)
