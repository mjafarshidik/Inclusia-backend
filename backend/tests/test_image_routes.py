import os
import io
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from app import create_app

class TestImageRoutes(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

        # Mock Firebase authentication decorator's token verification
        self.verify_patcher = patch('firebase_admin.auth.verify_id_token')
        self.mock_verify = self.verify_patcher.start()
        self.mock_verify.return_value = {
            "uid": "test_user_789",
            "email": "tester@example.com",
            "name": "Image Tester",
            "picture": "http://example.com/tester.png"
        }
        self.auth_headers = {'Authorization': 'Bearer mock_token_456'}

        # Mock Firestore Client to prevent database writes
        self.db_patcher = patch('services.firebase_service.FirebaseService.db')
        self.mock_db = self.db_patcher.start()
        self.mock_doc = MagicMock()
        self.mock_db.collection.return_value.document.return_value = self.mock_doc

        # Mock Thread to execute target function synchronously
        self.thread_patcher = patch('routes.image_routes.threading.Thread')
        self.mock_thread = self.thread_patcher.start()
        
        def run_sync(target, args=(), kwargs=None):
            mock_t = MagicMock()
            mock_t.start.side_effect = lambda: target(*args, **(kwargs or {}))
            return mock_t
            
        self.mock_thread.side_effect = run_sync

    def tearDown(self):
        self.verify_patcher.stop()
        self.db_patcher.stop()
        self.thread_patcher.stop()
        
        # Cleanup uploaded test files from static/uploaded_images/ if any exist
        upload_dir = os.path.join('static', 'uploaded_images')
        if os.path.exists(upload_dir):
            for file in os.listdir(upload_dir):
                file_path = os.path.join(upload_dir, file)
                try:
                    if os.path.isfile(file_path):
                        os.unlink(file_path)
                except Exception:
                    pass

    @patch('services.gemini_service.GeminiService.interpret_image_accessibility')
    def test_process_image_success(self, mock_interpret):
        # Configure Gemini mock
        mock_interpret.return_value = {
            "alt_text_totally_blind": "Mock alt text for totally blind",
            "visual_explanation_deaf": "Mock visual explanation for deaf"
        }

        # Prepare dummy image content
        image_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRDummyPNGData"
        data = {
            'file': (io.BytesIO(image_data), 'test_camera.png', 'image/png')
        }

        response = self.client.post(
            '/api/v1/images/process',
            data=data,
            content_type='multipart/form-data',
            headers=self.auth_headers
        )

        self.assertEqual(response.status_code, 202)
        res_json = response.get_json()
        
        self.assertTrue(res_json["success"])
        self.assertEqual(res_json["message"], "Image processing started")
        self.assertIn("id", res_json["data"])
        self.assertEqual(res_json["data"]["status"], "PROCESSING")
        self.assertEqual(res_json["data"]["progress"], 0)
        
        mock_interpret.assert_called_once()
        self.mock_db.collection.assert_called_with("uploaded_images")
        
        # Verify Firestore set calls (initial write and final progress write)
        self.assertTrue(self.mock_doc.set.called)

    def test_process_image_invalid_extension(self):
        # Prepare dummy invalid extension content
        invalid_data = b"dummy text file content"
        data = {
            'file': (io.BytesIO(invalid_data), 'test_document.txt', 'text/plain')
        }

        response = self.client.post(
            '/api/v1/images/process',
            data=data,
            content_type='multipart/form-data',
            headers=self.auth_headers
        )

        self.assertEqual(response.status_code, 400)
        res_json = response.get_json()
        self.assertFalse(res_json["success"])
        self.assertIn("Invalid file format", res_json["error"]["message"])

    def test_process_image_oversized(self):
        # Prepare dummy oversized image content (17MB)
        oversized_data = b"0" * (17 * 1024 * 1024)
        data = {
            'file': (io.BytesIO(oversized_data), 'huge_image.jpg', 'image/jpeg')
        }

        response = self.client.post(
            '/api/v1/images/process',
            data=data,
            content_type='multipart/form-data',
            headers=self.auth_headers
        )

        self.assertEqual(response.status_code, 413)
        res_json = response.get_json()
        self.assertFalse(res_json["success"])
        self.assertIn("Oversized file", res_json["error"]["message"])

    def test_list_images_success(self):
        # Configure mock stream return
        mock_doc = MagicMock()
        mock_doc.id = "mock-img-id"
        mock_doc.to_dict.return_value = {
            "id": "mock-img-id",
            "ownerId": "test_user_789",
            "filename": "camera.png",
            "status": "READY",
            "imageUrl": "http://localhost:8080/static/uploaded_images/mock-img-id.png",
            "accessibility_content": {
                "alt_text_totally_blind": "Mock alt text",
                "visual_explanation_deaf": "Mock deaf"
            },
            "createdAt": datetime(2026, 7, 4, tzinfo=timezone.utc),
            "updatedAt": datetime(2026, 7, 4, tzinfo=timezone.utc)
        }
        
        self.mock_db.collection.return_value.where.return_value.stream.return_value = [mock_doc]
        
        response = self.client.get(
            '/api/v1/images',
            headers=self.auth_headers
        )
        
        self.assertEqual(response.status_code, 200)
        res_json = response.get_json()
        self.assertTrue(res_json["success"])
        self.assertEqual(len(res_json["data"]), 1)
        self.assertEqual(res_json["data"][0]["id"], "mock-img-id")

    def test_global_404_handler(self):
        # Request a non-existent endpoint path
        response = self.client.get('/api/v1/non/existent/endpoint')
        self.assertEqual(response.status_code, 404)
        res_json = response.get_json()
        self.assertFalse(res_json["success"])
        self.assertEqual(res_json["error"]["code"], 404)

    @patch('services.gemini_service.GeminiService.interpret_image_accessibility')
    def test_process_image_gemini_failure(self, mock_interpret):
        # Configure Gemini mock to raise exception
        mock_interpret.side_effect = RuntimeError("Gemini quota exceeded")

        # Prepare dummy image content
        image_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRDummyPNGData"
        data = {
            'file': (io.BytesIO(image_data), 'test_camera.png', 'image/png')
        }

        response = self.client.post(
            '/api/v1/images/process',
            data=data,
            content_type='multipart/form-data',
            headers=self.auth_headers
        )

        # Post immediately returns 202
        self.assertEqual(response.status_code, 202)
        
        # Verify Firestore document was written with status: FAILED
        # Since it runs synchronously in the test, we can check the set() calls
        self.assertTrue(self.mock_doc.set.called)
        
        # Find the call with status="FAILED"
        failed_calls = [
            args[0] for args, kwargs in self.mock_doc.set.call_args_list
            if args[0].get("status") == "FAILED"
        ]
        self.assertTrue(len(failed_calls) > 0)
        self.assertIn("Gemini quota exceeded", failed_calls[0]["errorMessage"])

    def test_pillow_dependency_loaded(self):
        # Verify PIL / Pillow can be imported and works by creating a small dummy image in memory
        from PIL import Image
        import io
        img = Image.new('RGB', (100, 100), color='red')
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='PNG')
        self.assertTrue(len(img_bytes.getvalue()) > 0)

    def test_get_image_success(self):
        # Configure mock get return for existing document
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.id = "test-image-123"
        mock_doc.to_dict.return_value = {
            "ownerId": "test_user_789",
            "filename": "camera.png",
            "status": "READY",
            "imageUrl": "http://localhost:8080/static/uploaded_images/test-image-123.png",
            "createdAt": datetime(2026, 7, 4, tzinfo=timezone.utc),
            "updatedAt": datetime(2026, 7, 4, tzinfo=timezone.utc)
        }
        
        self.mock_db.collection.return_value.document.return_value.get.return_value = mock_doc
        
        response = self.client.get(
            '/api/v1/images/test-image-123',
            headers=self.auth_headers
        )
        
        self.assertEqual(response.status_code, 200)
        res_json = response.get_json()
        self.assertTrue(res_json["success"])
        self.assertEqual(res_json["data"]["id"], "test-image-123")
        self.assertEqual(res_json["data"]["status"], "READY")

    def test_get_image_not_found(self):
        # Configure mock get return for non-existent document
        mock_doc = MagicMock()
        mock_doc.exists = False
        
        self.mock_db.collection.return_value.document.return_value.get.return_value = mock_doc
        
        response = self.client.get(
            '/api/v1/images/non-existent-id',
            headers=self.auth_headers
        )
        
        self.assertEqual(response.status_code, 404)
        res_json = response.get_json()
        self.assertFalse(res_json["success"])
        self.assertIn("Image not found", res_json["error"]["message"])

if __name__ == '__main__':
    unittest.main()
