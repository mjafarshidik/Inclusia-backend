import os
import io
import json
import unittest
from unittest.mock import MagicMock, patch

from app import create_app
from services import firebase_service
from services.document_service import FirebaseUploadError, FirestoreFailureError

class TestDocumentUploadRoute(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

        # Mock Firebase Token Verification for all tests in this suite
        self.verify_patcher = patch('firebase_admin.auth.verify_id_token')
        self.mock_verify = self.verify_patcher.start()
        self.mock_verify.return_value = {
            "uid": "test_user_456",
            "email": "test@example.com",
            "name": "Test User",
            "picture": "http://example.com/pic.png"
        }
        self.auth_headers = {'Authorization': 'Bearer mock_token_123'}

    def tearDown(self):
        self.verify_patcher.stop()

    @patch('services.firebase_service.FirebaseService.upload_file')
    @patch('services.firebase_service.FirebaseService.save_document')
    def test_upload_success(self, mock_save_document, mock_upload_file):
        # Configure mocks
        mock_upload_file.return_value = "https://storage.googleapis.com/inclusia-test/documents/test-uuid.pdf"
        mock_save_document.return_value = None

        # Prepare dummy PDF content
        pdf_data = b"%PDF-1.4 dummy pdf content"
        data = {
            'file': (io.BytesIO(pdf_data), 'test_document.pdf', 'application/pdf')
        }

        response = self.client.post(
            '/api/v1/documents/upload',
            data=data,
            content_type='multipart/form-data',
            headers=self.auth_headers
        )

        self.assertEqual(response.status_code, 201)
        res_json = response.get_json()
        self.assertTrue(res_json['success'])
        self.assertEqual(res_json['message'], "Document uploaded successfully")
        self.assertIn('id', res_json['data'])
        
        # Verify that firebase_service.upload_file and save_document were called
        mock_upload_file.assert_called_once()
        mock_save_document.assert_called_once()

    @patch('services.document_service.DocumentService.process_and_store_document')
    def test_upload_and_process_success(self, mock_process):
        mock_process.return_value = "test-doc-123"

        pdf_data = b"%PDF-1.4 dummy pdf content"
        data = {
            'file': (io.BytesIO(pdf_data), 'test_document.pdf', 'application/pdf')
        }

        response = self.client.post(
            '/api/v1/documents',
            data=data,
            content_type='multipart/form-data',
            headers=self.auth_headers
        )

        self.assertEqual(response.status_code, 201)
        res_json = response.get_json()
        self.assertTrue(res_json['success'])
        self.assertEqual(res_json['message'], "Document uploaded and processed successfully")
        self.assertEqual(res_json['data']['id'], "test-doc-123")

    def test_upload_missing_file_field(self):
        # Missing 'file' key in form-data
        data = {
            'wrong_field': (io.BytesIO(b"data"), 'test.pdf', 'application/pdf')
        }
        response = self.client.post(
            '/api/v1/documents/upload',
            data=data,
            content_type='multipart/form-data',
            headers=self.auth_headers
        )
        self.assertEqual(response.status_code, 400)
        res_json = response.get_json()
        self.assertFalse(res_json['success'])
        self.assertEqual(res_json['message'], "Missing file")

    def test_upload_empty_filename(self):
        # File field exists but has no selected filename
        data = {
            'file': (io.BytesIO(b""), '', 'application/pdf')
        }
        response = self.client.post(
            '/api/v1/documents/upload',
            data=data,
            content_type='multipart/form-data',
            headers=self.auth_headers
        )
        self.assertEqual(response.status_code, 400)
        res_json = response.get_json()
        self.assertFalse(res_json['success'])
        self.assertEqual(res_json['message'], "Empty file")

    def test_upload_empty_file_content(self):
        # File field exists, filename valid, but content is 0 bytes
        data = {
            'file': (io.BytesIO(b""), 'test.pdf', 'application/pdf')
        }
        response = self.client.post(
            '/api/v1/documents/upload',
            data=data,
            content_type='multipart/form-data',
            headers=self.auth_headers
        )
        self.assertEqual(response.status_code, 400)
        res_json = response.get_json()
        self.assertFalse(res_json['success'])
        self.assertEqual(res_json['message'], "Empty file")

    def test_upload_invalid_mime_type(self):
        # Uploading txt file instead of PDF
        data = {
            'file': (io.BytesIO(b"some text content"), 'test.txt', 'text/plain')
        }
        response = self.client.post(
            '/api/v1/documents/upload',
            data=data,
            content_type='multipart/form-data',
            headers=self.auth_headers
        )
        self.assertEqual(response.status_code, 400)
        res_json = response.get_json()
        self.assertFalse(res_json['success'])
        self.assertEqual(res_json['message'], "Invalid MIME type")

    def test_upload_oversized_file(self):
        # Uploading file larger than 20MB
        oversized_data = b"0" * (20 * 1024 * 1024 + 1)
        data = {
            'file': (io.BytesIO(oversized_data), 'large.pdf', 'application/pdf')
        }
        response = self.client.post(
            '/api/v1/documents/upload',
            data=data,
            content_type='multipart/form-data',
            headers=self.auth_headers
        )
        self.assertEqual(response.status_code, 413)
        res_json = response.get_json()
        self.assertEqual(res_json['status'], "error")
        self.assertEqual(res_json['code'], 413)

    @patch('services.firebase_service.FirebaseService.upload_file')
    def test_upload_firebase_storage_failure(self, mock_upload_file):
        # Mock Storage upload raising an exception
        mock_upload_file.side_effect = Exception("Storage is down")

        data = {
            'file': (io.BytesIO(b"%PDF-1.4 dummy"), 'test.pdf', 'application/pdf')
        }
        response = self.client.post(
            '/api/v1/documents/upload',
            data=data,
            content_type='multipart/form-data',
            headers=self.auth_headers
        )
        self.assertEqual(response.status_code, 500)
        res_json = response.get_json()
        self.assertFalse(res_json['success'])
        self.assertEqual(res_json['message'], "Firebase upload failure")

    @patch('services.firebase_service.FirebaseService.upload_file')
    @patch('services.firebase_service.FirebaseService.save_document')
    def test_upload_firestore_failure(self, mock_save_document, mock_upload_file):
        # Mock Storage upload success, but Firestore saving fails
        mock_upload_file.return_value = "https://storage.googleapis.com/bucket/doc.pdf"
        mock_save_document.side_effect = Exception("Firestore write quota exceeded")

        data = {
            'file': (io.BytesIO(b"%PDF-1.4 dummy"), 'test.pdf', 'application/pdf')
        }
        response = self.client.post(
            '/api/v1/documents/upload',
            data=data,
            content_type='multipart/form-data',
            headers=self.auth_headers
        )
        self.assertEqual(response.status_code, 500)
        res_json = response.get_json()
        self.assertFalse(res_json['success'])
        self.assertEqual(res_json['message'], "Firestore failure")

    @patch('services.firebase_service.FirebaseService.get_document')
    @patch('services.firebase_service.FirebaseService.db')
    def test_get_document_fallback_to_images(self, mock_db, mock_get_document):
        # 1. Document not found in documents collection
        mock_get_document.return_value = None
        
        # 2. Mock firestore document retrieval for uploaded_images
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.id = "mock-image-id-999"
        mock_doc.to_dict.return_value = {
            "ownerId": "test_user_456",
            "filename": "camera_snap.png",
            "status": "READY",
            "imageUrl": "https://storage.googleapis.com/inclusia/avatars/anonymous_1.png",
            "accessibility_content": {
                "alt_text_totally_blind": "Alt text for blind",
                "visual_explanation_deaf": "Explanation for deaf"
            }
        }
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc
        
        response = self.client.get(
            '/api/v1/documents/mock-image-id-999',
            headers=self.auth_headers
        )
        
        self.assertEqual(response.status_code, 200)
        res_json = response.get_json()
        self.assertTrue(res_json["success"])
        self.assertEqual(res_json["data"]["id"], "mock-image-id-999")
        self.assertEqual(res_json["data"]["contentType"], "image/png")
        self.assertEqual(res_json["data"]["status"], "READY")
        self.assertEqual(len(res_json["data"]["sections"]), 1)
        self.assertEqual(res_json["data"]["sections"][0]["type"], "image")

if __name__ == '__main__':
    unittest.main()

