import os
import sys

# Ensure backend root is in sys.path
backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)

from firebase.firebase import firebase_client
from utils.logger import get_logger

logger = get_logger(__name__)

def migrate_existing_images():
    """Scans all existing image objects in documents/** and makes them public."""
    logger.info("Starting image migration...")
    
    try:
        bucket = firebase_client.bucket
    except Exception as e:
        logger.error(f"Failed to get Firebase Storage bucket: {e}")
        sys.exit(1)
        
    try:
        # List blobs under documents/ prefix
        blobs = bucket.list_blobs(prefix="documents/")
        count = 0
        success_count = 0
        
        for blob in blobs:
            # We want to check if the blob is an image (ends with image extension and has /images/ in path)
            # Path format: documents/<document-id>/images/<filename>
            name_parts = blob.name.split("/")
            if len(name_parts) >= 4 and name_parts[2] == "images":
                count += 1
                logger.info(f"Processing blob: {blob.name}")
                try:
                    # Make the object public. Under UBLA, blob.make_public() might raise an exception,
                    # but we want to log it and proceed since bucket-level policy is enabled.
                    try:
                        blob.make_public()
                        logger.info(f"Successfully set public ACL on blob: {blob.name}")
                    except Exception as acl_err:
                        logger.warning(
                            f"Could not set public ACL on blob {blob.name} "
                            f"(Uniform Bucket-Level Access might be enabled): {acl_err}"
                        )
                    success_count += 1
                except Exception as blob_err:
                    logger.error(f"Failed to migrate blob {blob.name}: {blob_err}")
                    
        logger.info(f"Migration completed. Scanned: {count}, Successfully processed: {success_count}")
    except Exception as e:
        logger.error(f"Migration failed with error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    migrate_existing_images()
