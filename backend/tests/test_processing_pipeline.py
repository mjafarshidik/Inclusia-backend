import os
import io
import json
import time
import unittest
from unittest.mock import MagicMock, patch

from app import create_app
from services import firebase_service, document_processing_service
from services.document_processing_service import DocumentProcessingService

class TestDocumentProcessingPipeline(unittest.TestCase):
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

    @patch('services.firebase_service.FirebaseService.save_document')
    @patch('google.adk.runners.InMemoryRunner')
    def test_pipeline_execution_success(self, mock_runner_cls, mock_save_document):
        mock_runner = MagicMock()
        mock_runner_cls.return_value = mock_runner
        
        mock_session = MagicMock()
        mock_session.state = {
            "summary_analysis": {
                "summary": "Mocked Gemini Summary",
                "topics": ["topic1"],
                "suggested_questions": ["q1"]
            },
            "sections": [
                {"type": "text", "content": "Simple text", "spoken_text_totally_blind": "Simple text"}
            ]
        }
        
        async def mock_get_session(app_name, session_id):
            return mock_session
            
        async def mock_create_session(*args, **kwargs):
            return mock_session
            
        async def mock_run_async(*args, **kwargs):
            yield MagicMock()
            
        mock_runner.session_service.get_session = mock_get_session
        mock_runner.session_service.create_session = mock_create_session
        mock_runner.run_async = mock_run_async
        
        document_processing_service.process_document("doc-123")
        
        self.assertEqual(mock_save_document.call_count, 2)
        calls = [args[0][1] for args in mock_save_document.call_args_list]
        self.assertEqual(calls[0]["status"], "QUEUED")
        self.assertEqual(calls[1]["status"], "READY")
        self.assertEqual(calls[1]["summary"], "Mocked Gemini Summary")
        self.assertEqual(len(calls[1]["sections"]), 1)

    @patch('services.firebase_service.FirebaseService.save_document')
    @patch('google.adk.runners.InMemoryRunner')
    def test_pipeline_missing_document(self, mock_runner_cls, mock_save_document):
        mock_runner = MagicMock()
        mock_runner_cls.return_value = mock_runner
        
        async def mock_create_session(*args, **kwargs):
            raise ValueError("Document not found in Firestore")
            
        mock_runner.session_service.create_session = mock_create_session
        
        document_processing_service.process_document("non-existent-doc")
        
        self.assertEqual(mock_save_document.call_count, 2)
        self.assertEqual(mock_save_document.call_args_list[0][0][1]["status"], "QUEUED")
        self.assertEqual(mock_save_document.call_args_list[1][0][1]["status"], "FAILED")
        self.assertIn("Document not found in Firestore", mock_save_document.call_args_list[1][0][1]["errorMessage"])

    @patch('services.firebase_service.FirebaseService.save_document')
    @patch('google.adk.runners.InMemoryRunner')
    def test_pipeline_download_failure(self, mock_runner_cls, mock_save_document):
        mock_runner = MagicMock()
        mock_runner_cls.return_value = mock_runner
        
        mock_session = MagicMock()
        async def mock_create_session(*args, **kwargs):
            return mock_session
            
        async def mock_run_async(*args, **kwargs):
            raise RuntimeError("Storage download failure: Firebase Storage not available")
            yield MagicMock()
            
        mock_runner.session_service.create_session = mock_create_session
        mock_runner.run_async = mock_run_async
        
        document_processing_service.process_document("doc-123")
        
        self.assertEqual(mock_save_document.call_count, 2)
        self.assertEqual(mock_save_document.call_args_list[0][0][1]["status"], "QUEUED")
        self.assertEqual(mock_save_document.call_args_list[1][0][1]["status"], "FAILED")
        self.assertIn("Storage download failure", mock_save_document.call_args_list[1][0][1]["errorMessage"])

    @patch('services.firebase_service.FirebaseService.save_document')
    @patch('google.adk.runners.InMemoryRunner')
    def test_pipeline_extraction_failure(self, mock_runner_cls, mock_save_document):
        mock_runner = MagicMock()
        mock_runner_cls.return_value = mock_runner
        
        mock_session = MagicMock()
        async def mock_create_session(*args, **kwargs):
            return mock_session
            
        async def mock_run_async(*args, **kwargs):
            raise RuntimeError("Extraction failure: PyMuPDF: Invalid PDF file")
            yield MagicMock()
            
        mock_runner.session_service.create_session = mock_create_session
        mock_runner.run_async = mock_run_async
        
        document_processing_service.process_document("doc-123")
        
        self.assertEqual(mock_save_document.call_count, 2)
        self.assertEqual(mock_save_document.call_args_list[0][0][1]["status"], "QUEUED")
        self.assertEqual(mock_save_document.call_args_list[1][0][1]["status"], "FAILED")
        self.assertIn("Extraction failure", mock_save_document.call_args_list[1][0][1]["errorMessage"])

    @patch('services.firebase_service.FirebaseService.get_document')
    @patch('routes.document_routes.document_processing_service.process_document')
    def test_route_process_started(self, mock_process_document, mock_get_document):
        # Setup mocks
        mock_get_document.return_value = {
            "id": "doc-123",
            "status": "UPLOADED",
            "ownerId": "test_user_456"
        }

        # Call POST route
        response = self.client.post('/api/v1/documents/doc-123/process', headers=self.auth_headers)
        self.assertEqual(response.status_code, 200)
        res_json = response.get_json()
        self.assertTrue(res_json["success"])
        self.assertEqual(res_json["message"], "Processing started")
        self.assertEqual(res_json["data"]["documentId"], "doc-123")
        self.assertEqual(res_json["data"]["status"], "PROCESSING_AI")
        
        # Verify that background processing was triggered
        mock_process_document.assert_called_once_with("doc-123")

    def test_route_process_non_existent_document(self):
        from services.firebase_service import FirebaseService
        with patch.object(FirebaseService, 'get_document', return_value=None):
            response = self.client.post('/api/v1/documents/non-existent-doc/process', headers=self.auth_headers)
            self.assertEqual(response.status_code, 404)
            res_json = response.get_json()
            self.assertEqual(res_json["error"]["message"], "Document not found")

    @patch('services.firebase_service.FirebaseService.get_document')
    def test_route_get_metadata(self, mock_get_document):
        mock_get_document.return_value = {
            "id": "doc-123",
            "status": "READY",
            "extractedText": "Sample text",
            "summary": "Sample summary",
            "ownerId": "test_user_456"
        }

        response = self.client.get('/api/v1/documents/doc-123', headers=self.auth_headers)
        self.assertEqual(response.status_code, 200)
        res_json = response.get_json()
        self.assertTrue(res_json["success"])
        self.assertEqual(res_json["data"]["status"], "READY")
        self.assertEqual(res_json["data"]["extractedText"], "Sample text")
        self.assertEqual(res_json["data"]["summary"], "Sample summary")

    @patch('config.Config.GEMINI_API_KEY', None)
    def test_gemini_service_missing_api_key(self):
        from services.gemini_service import GeminiService
        with self.assertRaises(RuntimeError) as context:
            GeminiService.process("Some valid text")
        self.assertEqual(str(context.exception), "Missing API key")

    def test_gemini_service_invalid_input(self):
        from services.gemini_service import GeminiService
        with self.assertRaises(ValueError) as context:
            GeminiService.process("")
        self.assertEqual(str(context.exception), "Invalid input text")

        with self.assertRaises(ValueError) as context:
            GeminiService.process("a" * 500001)
        self.assertEqual(str(context.exception), "Input text exceeds maximum safe size")

    @patch('config.Config.GEMINI_API_KEY', 'valid_api_key')
    @patch('services.gemini_service.get_gemini_client')
    def test_gemini_service_error_mappings(self, mock_get_gemini_client):
        from services.gemini_service import GeminiService
        
        mock_client = MagicMock()
        mock_generate_content = mock_client.models.generate_content
        mock_get_gemini_client.return_value = mock_client
        
        # Test Auth Failure
        mock_generate_content.side_effect = Exception("API_KEY_INVALID: The provided API key is invalid.")
        with self.assertRaises(RuntimeError) as context:
            GeminiService.process("Test text")
        self.assertEqual(str(context.exception), "Authentication failure")

        # Test Permission/Access Denied
        mock_generate_content.side_effect = Exception("PERMISSION_DENIED: Your project has been denied access.")
        with self.assertRaises(RuntimeError) as context:
            GeminiService.process("Test text")
        self.assertEqual(str(context.exception), "Gemini API access denied. Please verify your API key and project status.")

        # Test Rate Limit
        mock_generate_content.side_effect = Exception("429 Resource exhausted: quota exceeded.")
        with self.assertRaises(RuntimeError) as context:
            GeminiService.process("Test text")
        self.assertEqual(str(context.exception), "Rate limit")

        # Test Timeout
        mock_generate_content.side_effect = Exception("Request timed out after 30 seconds.")
        with self.assertRaises(RuntimeError) as context:
            GeminiService.process("Test text")
        self.assertEqual(str(context.exception), "Timeout")

        # Test Network Failure
        mock_generate_content.side_effect = Exception("Connection reset by peer or endpoint unavailable.")
        with self.assertRaises(RuntimeError) as context:
            GeminiService.process("Test text")
        self.assertEqual(str(context.exception), "Network failure")

        # Test Invalid Request
        mock_generate_content.side_effect = Exception("400 Bad Request: invalid model name.")
        with self.assertRaises(RuntimeError) as context:
            GeminiService.process("Test text")
        self.assertEqual(str(context.exception), "Invalid request")

        # Reset model caching after test
        GeminiService._model = None

if __name__ == '__main__':
    unittest.main()

