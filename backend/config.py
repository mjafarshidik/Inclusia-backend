import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    PORT = int(os.environ.get("PORT", 8080))
    FLASK_ENV = os.environ.get("FLASK_ENV", "development")
    
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
    
    FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID")
    FIREBASE_STORAGE_BUCKET = os.environ.get("FIREBASE_STORAGE_BUCKET")
    FIREBASE_CREDENTIALS = os.environ.get("FIREBASE_CREDENTIALS")
    
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024  # 20MB max file upload size
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")
    
    # Debug flag for authentication errors
    DEBUG_AUTH_ERRORS = os.getenv("DEBUG_AUTH_ERRORS", "False").lower() == "true"
    
    # Allow bypassing authentication in specific environments
    BYPASS_AUTH = os.getenv("BYPASS_AUTH", "False").lower() == "true"
