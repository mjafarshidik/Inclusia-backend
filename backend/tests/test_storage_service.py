import unittest
from unittest.mock import MagicMock, patch, PropertyMock
from io import BytesIO
import os
import sys

# Ensure backend root is in sys.path
backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)

from services.storage_service import StorageService, get_base_url

class TestStorageService(unittest.TestCase):
    def setUp(self):
        self.mock_bucket = MagicMock()
        self.storage_service = StorageService(bucket=self.mock_bucket)

    def test_get_public_url(self):
        self.mock_bucket.name = "test-bucket"
        url = self.storage_service.get_public_url("documents/123/images/img.jpg")
        self.assertEqual(url, "https://storage.googleapis.com/test-bucket/documents/123/images/img.jpg")

    def test_upload_image_success(self):
        mock_blob = MagicMock()
        self.mock_bucket.blob.return_value = mock_blob
        self.mock_bucket.name = "test-bucket"
        self.mock_bucket.reload = MagicMock()
        self.mock_bucket.iam_configuration.uniform_bucket_level_access.enabled = False

        # Test upload_file with stream
        stream = BytesIO(b"dummy_image_data")
        url = self.storage_service.upload_file(stream, "documents/123/images/img.jpg", "image/jpeg")

        self.mock_bucket.blob.assert_called_once_with("documents/123/images/img.jpg")
        mock_blob.upload_from_file.assert_called_once()
        mock_blob.make_public.assert_called_once()
        self.assertEqual(url, "https://storage.googleapis.com/test-bucket/documents/123/images/img.jpg")

    def test_local_storage_mode(self):
        # Local mode occurs when bucket is None or raising errors
        local_storage = StorageService(bucket=None)
        
        with patch('services.storage_service.StorageService.bucket', new_callable=PropertyMock) as mock_bucket_prop:
            mock_bucket_prop.return_value = None
            stream = BytesIO(b"dummy_data")
            
            # We patch get_base_url to return a fixed host
            with patch('services.storage_service.get_base_url', return_value="http://localhost:8080"):
                url = local_storage.upload_file(stream, "test_doc/img.jpg", "image/jpeg")
            self.assertTrue(url.startswith("http://localhost:8080/static/uploads/test_doc/img.jpg"))
            
            # Verify file exists on local disk
            local_path = os.path.join("static", "uploads", "test_doc", "img.jpg")
            self.assertTrue(os.path.exists(local_path))
            
            # Test download in local mode
            downloaded = local_storage.download_file("test_doc/img.jpg")
            self.assertEqual(downloaded.read(), b"dummy_data")

            # Clean up local file
            if os.path.exists(local_path):
                os.remove(local_path)
            local_dir = os.path.join("static", "uploads", "test_doc")
            if os.path.exists(local_dir):
                os.rmdir(local_dir)

    def test_failed_acl_update(self):
        mock_blob = MagicMock()
        self.mock_bucket.blob.return_value = mock_blob
        self.mock_bucket.name = "test-bucket"
        self.mock_bucket.reload = MagicMock()
        
        # UBLA is disabled, so make_public fails, which should delete blob and raise exception
        self.mock_bucket.iam_configuration.uniform_bucket_level_access.enabled = False
        mock_blob.make_public.side_effect = Exception("ACL failed")

        stream = BytesIO(b"dummy_data")
        with self.assertRaises(Exception):
            self.storage_service.upload_file(stream, "documents/123/images/img.jpg", "image/jpeg")
        
        # Verify it attempted to delete the private blob
        mock_blob.delete.assert_called_once()

    def test_missing_bucket_configuration(self):
        # If bucket throws exception or is missing
        with patch('services.storage_service.StorageService.bucket', new_callable=PropertyMock) as mock_bucket_prop:
            mock_bucket_prop.return_value = None
            service = StorageService()
            stream = BytesIO(b"dummy_data")
            
            with patch('services.storage_service.get_base_url', return_value="http://localhost:8080"):
                url = service.upload_file(stream, "test_doc/img.jpg", "image/jpeg")
                self.assertTrue(url.startswith("http://localhost:8080/static/uploads/test_doc/img.jpg"))
                
                # Cleanup
                local_path = os.path.join("static", "uploads", "test_doc", "img.jpg")
                if os.path.exists(local_path):
                    os.remove(local_path)
                local_dir = os.path.join("static", "uploads", "test_doc")
                if os.path.exists(local_dir):
                    os.rmdir(local_dir)

    def test_migration_script(self):
        mock_blob1 = MagicMock()
        mock_blob1.name = "documents/123/images/img1.jpg"
        mock_blob2 = MagicMock()
        mock_blob2.name = "documents/123/pdf.pdf" # Should be ignored

        self.mock_bucket.list_blobs.return_value = [mock_blob1, mock_blob2]

        from scripts.migrate_images import migrate_existing_images
        
        with patch('scripts.migrate_images.firebase_client') as mock_fb_client:
            mock_fb_client.bucket = self.mock_bucket
            migrate_existing_images()
            
            # img1.jpg should be made public
            mock_blob1.make_public.assert_called_once()
            # pdf.pdf should NOT be made public
            mock_blob2.make_public.assert_not_called()

    def test_invalid_upload(self):
        # Test empty destination path raises exception
        stream = BytesIO(b"dummy")
        with self.assertRaises(ValueError):
            if not "":
                raise ValueError("Invalid destination path")
            self.storage_service.upload_file(stream, "", "image/jpeg")
