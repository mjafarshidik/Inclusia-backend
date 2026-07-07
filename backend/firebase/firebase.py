import base64
import json
from typing import Any, Optional
import firebase_admin
from firebase_admin import credentials, firestore, storage
from google.cloud.firestore import Client as FirestoreClient
from google.cloud.storage import Bucket as StorageBucket

from config import Config
from utils.logger import get_logger

logger = get_logger(__name__)

class FirebaseClient:
    _instance: Optional['FirebaseClient'] = None
    _db: Optional[FirestoreClient] = None
    _bucket: Optional[StorageBucket] = None

    def __new__(cls) -> 'FirebaseClient':
        if cls._instance is None:
            cls._instance = super(FirebaseClient, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self) -> None:
        """Initializes Firebase Admin SDK application and client wrappers."""
        if firebase_admin._apps:
            logger.info("Firebase app already initialized.")
            try:
                self._db = firestore.client()
                if Config.FIREBASE_STORAGE_BUCKET:
                    self._bucket = storage.bucket(Config.FIREBASE_STORAGE_BUCKET)
            except Exception as e:
                logger.error(f"Failed to obtain Firebase clients for already initialized app: {e}")
            return

        cred = None
        if Config.FIREBASE_CREDENTIALS:
            cred_str = Config.FIREBASE_CREDENTIALS.strip()
            try:
                # 1. Try loading as JSON string
                if cred_str.startswith('{'):
                    cred_dict = json.loads(cred_str)
                    cred = credentials.Certificate(cred_dict)
                    logger.info("Firebase credentials initialized from JSON string.")
                else:
                    # 2. Try loading as Base64 encoded JSON
                    try:
                        decoded = base64.b64decode(cred_str).decode('utf-8')
                        if decoded.strip().startswith('{'):
                            cred_dict = json.loads(decoded)
                            cred = credentials.Certificate(cred_dict)
                            logger.info("Firebase credentials initialized from Base64 string.")
                        else:
                            raise ValueError("Decoded Base64 is not valid JSON.")
                    except Exception:
                        # 3. Fallback: treat as file path
                        logger.info(f"Firebase credentials treating as file path: {cred_str}")
                        import os
                        resolved_path = cred_str
                        if not os.path.isabs(cred_str):
                            # Resolve relative to the backend/ root directory
                            backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                            potential_path = os.path.join(backend_root, cred_str)
                            if os.path.exists(potential_path):
                                resolved_path = potential_path
                                logger.info(f"Resolved relative credentials path to: {resolved_path}")
                        cred = credentials.Certificate(resolved_path)
            except Exception as e:
                logger.error(f"Failed to parse Firebase credentials configuration: {e}")
                return
        else:
            logger.warning("No FIREBASE_CREDENTIALS provided. Defaulting to Application Default Credentials.")
            try:
                cred = credentials.ApplicationDefault()
            except Exception as e:
                logger.error(f"Failed to load Application Default Credentials: {e}")
                return

        try:
            options: dict[str, Any] = {}
            if Config.FIREBASE_STORAGE_BUCKET:
                options['storageBucket'] = Config.FIREBASE_STORAGE_BUCKET
            if Config.FIREBASE_PROJECT_ID:
                options['projectId'] = Config.FIREBASE_PROJECT_ID

            firebase_admin.initialize_app(cred, options)
            self._db = firestore.client()
            
            if Config.FIREBASE_STORAGE_BUCKET:
                self._bucket = storage.bucket(Config.FIREBASE_STORAGE_BUCKET)
            else:
                logger.warning("FIREBASE_STORAGE_BUCKET is not configured. Storage bucket client is not available.")
                
            logger.info("Firebase Admin SDK initialized successfully.")
        except Exception as e:
            logger.error(f"Error during Firebase Admin SDK initialization: {e}")

    @property
    def db(self) -> FirestoreClient:
        if self._db is None:
            raise RuntimeError(
                "Firestore database client is not initialized. "
                "Please verify that FIREBASE_CREDENTIALS and configuration are correct."
            )
        return self._db

    @property
    def bucket(self) -> StorageBucket:
        if self._bucket is None:
            raise RuntimeError(
                "Firebase Storage bucket client is not initialized. "
                "Please verify that FIREBASE_STORAGE_BUCKET and credentials are correct."
            )
        return self._bucket

firebase_client = FirebaseClient()
