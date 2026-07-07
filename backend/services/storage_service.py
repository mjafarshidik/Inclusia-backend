import os
from io import BytesIO
from typing import Any, Optional
from google.cloud.storage import Bucket as StorageBucket
from utils.logger import get_logger

logger = get_logger(__name__)

def get_base_url() -> str:
    from flask import has_request_context, request
    if has_request_context():
        return request.host_url.rstrip('/')
    port = os.environ.get("PORT", "8080")
    return f"http://localhost:{port}"

class StorageService:
    def __init__(self, bucket: Optional[StorageBucket] = None):
        self._bucket = bucket

    @property
    def bucket(self) -> Optional[StorageBucket]:
        if self._bucket is not None:
            return self._bucket
        try:
            from firebase.firebase import firebase_client
            # Safely check if firebase_client has bucket initialized
            if firebase_client._bucket is not None:
                return firebase_client.bucket
        except Exception as e:
            logger.warning(f"Could not get Firebase storage bucket: {e}")
        return None

    def upload_file(self, file: Any, destination: str, content_type: str = "application/pdf") -> str:
        """Uploads a file to Google Cloud Storage (or falls back to local storage)."""
        bucket = self.bucket
        if bucket is None:
            logger.warning("Google Cloud Storage bucket not configured. Falling back to local storage.")
            return self._save_locally(file, destination)

        try:
            logger.info(f"Uploading file to Storage path: {destination}")
            blob = bucket.blob(destination)
            
            # Reset seek position if file-like object has seek method
            if hasattr(file, 'seek'):
                try:
                    file.seek(0)
                except Exception as seek_err:
                    logger.debug(f"Could not seek file to 0: {seek_err}")

            if hasattr(file, 'read'):
                blob.upload_from_file(file, content_type=content_type)
            else:
                blob.upload_from_string(file, content_type=content_type)
        except Exception as e:
            logger.error(f"Error uploading file to GCS: {e}")
            logger.info("GCS upload failed, falling back to local storage.")
            return self._save_locally(file, destination)

        # Make public - failures here are critical if UBLA is disabled
        try:
            try:
                # Check if Uniform Bucket-Level Access (UBLA) is enabled
                bucket.reload()
                ubla_enabled = getattr(bucket.iam_configuration.uniform_bucket_level_access, 'enabled', False)
            except Exception as reload_err:
                logger.warning(f"Could not reload bucket metadata to check UBLA: {reload_err}")
                ubla_enabled = False

            try:
                blob.make_public()
                logger.info(f"Blob '{blob.name}' made public via ACL.")
            except Exception as make_public_err:
                err_msg = str(make_public_err).lower()
                if ubla_enabled or "uniform bucket-level access" in err_msg:
                    logger.info(
                        f"Uniform Bucket-Level Access is enabled on bucket '{bucket.name}'. "
                        f"ACL update skipped, object '{blob.name}' is public via bucket IAM policy."
                    )
                else:
                    logger.error(f"Failed to make blob '{blob.name}' public via ACL: {make_public_err}", exc_info=True)
                    # Clean up newly uploaded private blob to avoid inconsistent metadata
                    try:
                        blob.delete()
                        logger.info(f"Deleted private blob '{blob.name}' to prevent inconsistent metadata.")
                    except Exception as del_err:
                        logger.error(f"Failed to delete private blob '{blob.name}': {del_err}")
                    raise make_public_err

            return self.get_public_url(destination)
        except Exception as e:
            logger.error(f"Critical error making GCS blob public: {e}")
            raise e

    def upload_image(self, file_path: str, destination: str, content_type: str = "image/jpeg") -> str:
        """Uploads an image from local file path to GCS (or falls back to local storage)."""
        try:
            with open(file_path, 'rb') as f:
                return self.upload_file(f, destination, content_type)
        except Exception as e:
            logger.error(f"Error uploading image file '{file_path}': {e}")
            raise e

    def download_file(self, destination: str) -> BytesIO:
        """Downloads a file from Storage (or falls back to local storage)."""
        bucket = self.bucket
        if bucket is None:
            logger.warning("Google Cloud Storage bucket not configured. Loading from local storage.")
            return self._load_locally(destination)

        try:
            logger.info(f"Downloading file from Storage path: {destination}")
            blob = bucket.blob(destination)
            file_stream = BytesIO()
            blob.download_to_file(file_stream)
            file_stream.seek(0)
            return file_stream
        except Exception as e:
            logger.warning(f"Failed to download from GCS: {e}. Checking local storage fallback.")
            try:
                return self._load_locally(destination)
            except Exception:
                raise e

    def get_public_url(self, destination: str) -> str:
        """Returns the GCS public URL or local URL for a destination path."""
        bucket = self.bucket
        if bucket is not None:
            return f"https://storage.googleapis.com/{bucket.name}/{destination}"
        return f"{get_base_url().rstrip('/')}/static/uploads/{destination}"

    def _save_locally(self, file: Any, destination: str) -> str:
        """Helper to save a file stream/string to the local static directory."""
        local_dir = os.path.join("static", "uploads", os.path.dirname(destination))
        os.makedirs(local_dir, exist_ok=True)
        local_path = os.path.join("static", "uploads", destination)
        
        # Reset seek position if possible
        if hasattr(file, 'seek'):
            try:
                file.seek(0)
            except Exception:
                pass
                
        content = file.read() if hasattr(file, 'read') else file
        if isinstance(content, str):
            content = content.encode('utf-8')
            
        with open(local_path, 'wb') as f:
            f.write(content)
            
        logger.info(f"File successfully saved locally to {local_path}")
        return f"{get_base_url().rstrip('/')}/{local_path}"

    def _load_locally(self, destination: str) -> BytesIO:
        """Helper to load a file from the local static directory."""
        local_path = os.path.join("static", "uploads", destination)
        if not os.path.exists(local_path):
            raise FileNotFoundError(f"Local file not found: {local_path}")
        with open(local_path, 'rb') as f:
            return BytesIO(f.read())
