from flask import Blueprint, request, jsonify, g
from utils.auth import firebase_auth_required
from utils.logger import get_logger
from services.feedback_service import FeedbackService
from utils.response import error_response

logger = get_logger(__name__)
feedback_bp = Blueprint('feedback_bp', __name__)

@feedback_bp.route('/v1/feedback', methods=['POST'])
@firebase_auth_required
def post_feedback():
    try:
        data = request.get_json(silent=True)
        if not data:
            return error_response("Missing JSON request body", 400)
            
        target_id = data.get("targetId") or data.get("target_id")
        target_type = data.get("targetType") or data.get("target_type")
        rating = data.get("rating")
        tags = data.get("tags")
        comment = data.get("comment")
        
        if target_id is None or target_type is None or rating is None or tags is None:
            return error_response("Missing required fields (targetId, targetType, rating, tags)", 400)
            
        if not isinstance(tags, list):
            return error_response("tags must be a list of strings", 400)
            
        try:
            feedback_id = FeedbackService.submit_feedback(
                owner_id=g.user.uid,
                target_id=target_id,
                target_type=target_type,
                rating=rating,
                tags=tags,
                comment=comment
            )
            
            return jsonify({
                "data": {
                    "id": feedback_id
                },
                "message": "Feedback submitted successfully. Thank you for helping us improve Inclusia!",
                "success": True
            }), 200
            
        except ValueError as ve:
            return error_response(str(ve), 400)
            
    except Exception as e:
        logger.error(f"Error submitting feedback: {e}")
        return error_response("Internal server error", 500)

@feedback_bp.route('/v1/feedback/optimize', methods=['POST'])
@firebase_auth_required
def optimize_feedbacks():
    try:
        processed = FeedbackService.process_pending_optimizations()
        return jsonify({
            "success": True,
            "message": f"Processed {processed} pending optimizations.",
            "data": {
                "processedCount": processed
            }
        }), 200
    except Exception as e:
        logger.error(f"Error processing optimizations: {e}")
        return error_response("Internal server error", 500)
