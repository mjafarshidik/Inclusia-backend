import os
import sys

# Critical startup dependency check to fail-fast if modules are missing
try:
    import PIL
    from PIL import Image
    import google.genai
    import firebase_admin
    import tenacity
    import requests
except ImportError as e:
    print(f"CRITICAL STARTUP ERROR: Critical dependency is missing: {e}", file=sys.stderr)
    sys.exit(1)

from flask import Flask, jsonify, g
from flask_cors import CORS
from config import Config

# Critical startup configuration check to fail-fast if GEMINI_API_KEY is missing
if not Config.GEMINI_API_KEY or Config.GEMINI_API_KEY.strip() == "" or Config.GEMINI_API_KEY == "your_gemini_api_key_here":
    print("CRITICAL STARTUP ERROR: GEMINI_API_KEY environment variable is not configured or is invalid.", file=sys.stderr)
    sys.exit(1)

from routes.document_routes import document_bp
from routes.chat_routes import chat_bp
from routes.profile_routes import profile_bp
from routes.image_routes import image_bp
from routes.feedback_routes import feedback_bp
from utils.logger import get_logger

logger = get_logger(__name__)

def create_app():
    app = Flask(__name__)
    CORS(app)
    
    app.config.from_object(Config)
    app.url_map.strict_slashes = False
    
    # Critical startup configuration check: verify Firestore and Storage configuration
    import sys
    if "unittest" not in sys.modules and not os.environ.get("TESTING"):
        try:
            from firebase.firebase import firebase_client
            
            # 1. Check if Firestore client initialized successfully
            db_project = firebase_client.db.project
            if not db_project:
                raise ValueError("Firestore client could not resolve project ID.")
                
            # 2. Check if Storage bucket client initialized successfully
            bucket_project = firebase_client.bucket.client.project
            if not bucket_project:
                raise ValueError("Storage client could not resolve project ID.")
                
            # 3. Verify Firestore and Storage project IDs match
            if db_project != bucket_project:
                raise ValueError(f"Project ID mismatch: Firestore is using '{db_project}' but Storage is using '{bucket_project}'.")
                
            # 4. Verify Firestore project matches Config.FIREBASE_PROJECT_ID if specified
            if Config.FIREBASE_PROJECT_ID and db_project != Config.FIREBASE_PROJECT_ID:
                raise ValueError(f"Project ID configuration drift: Config.FIREBASE_PROJECT_ID is '{Config.FIREBASE_PROJECT_ID}' but Firestore resolved to '{db_project}'.")
                
            # 5. Verify bucket name matches Config.FIREBASE_STORAGE_BUCKET if specified
            if Config.FIREBASE_STORAGE_BUCKET and firebase_client.bucket.name != Config.FIREBASE_STORAGE_BUCKET:
                raise ValueError(f"Storage Bucket configuration drift: Config.FIREBASE_STORAGE_BUCKET is '{Config.FIREBASE_STORAGE_BUCKET}' but client bucket name is '{firebase_client.bucket.name}'.")
                
            logger.info(f"Startup configuration verified: Firestore & Storage successfully connected to project '{db_project}' using bucket '{firebase_client.bucket.name}'.")
        except Exception as e:
            print(f"CRITICAL STARTUP CONFIGURATION ERROR: {e}", file=sys.stderr)
            sys.exit(1)
    
    @app.before_request
    def before_request():
        import uuid
        from flask import request
        g.request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        class AnonymousUser:
            uid = "anonymous"
            email = None
            name = None
            picture = None
        g.user = AnonymousUser()

    
    # Register routes
    app.register_blueprint(document_bp, url_prefix='/api')
    app.register_blueprint(chat_bp, url_prefix='/api')
    app.register_blueprint(profile_bp, url_prefix='/api')
    app.register_blueprint(image_bp, url_prefix='/api')
    app.register_blueprint(feedback_bp, url_prefix='/api')
    
    # Global Error Handlers
    from werkzeug.exceptions import HTTPException
    from utils.response import error_response

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        return error_response(e.description or str(e), e.code)

    @app.errorhandler(Exception)
    def handle_generic_exception(e):
        logger.error(f"Unhandled Server Error: {e}", exc_info=True)
        return error_response("Internal server error", 500)
        
    @app.route('/health', methods=['GET'])
    def health_check():
        return jsonify({"success": True, "message": "Service is healthy"}), 200
        
    return app

app = create_app()

if __name__ == '__main__':
    logger.info(f"Starting Inclusia Backend on port {Config.PORT}...")
    app.run(host='0.0.0.0', port=Config.PORT, debug=(Config.FLASK_ENV == 'development'))
