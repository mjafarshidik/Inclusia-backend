import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
import io
import json

from app import create_app

class TestFeedbackRoutes(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

        # Patch verify_id_token
        self.verify_patcher = patch('firebase_admin.auth.verify_id_token')
        self.mock_verify = self.verify_patcher.start()
        self.mock_verify.return_value = {
            "uid": "feedback_user_123",
            "email": "feedback@example.com",
            "name": "Feedback Reviewer"
        }
        self.auth_headers = {'Authorization': 'Bearer valid_mock_token'}

        # Mock firestore database
        self.db_patcher = patch('services.firebase_service.FirebaseService.db')
        self.mock_db = self.db_patcher.start()
        self.mock_doc = MagicMock()
        self.mock_db.collection.return_value.document.return_value = self.mock_doc

    def tearDown(self):
        self.verify_patcher.stop()
        self.db_patcher.stop()

    def test_post_feedback_success_excellent(self):
        # 1. DOCUMENT feedback with EXCELLENT rating and tags
        payload = {
            "targetId": "doc-uuid-abc",
            "targetType": "DOCUMENT",
            "rating": "EXCELLENT",
            "tags": ["Easy Understand", "Well Summarized"],
            "comment": "Highly recommended and readable!"
        }

        response = self.client.post(
            '/api/v1/feedback',
            json=payload,
            headers=self.auth_headers
        )

        self.assertEqual(response.status_code, 200)
        res_json = response.get_json()
        self.assertTrue(res_json["success"])
        self.assertEqual(res_json["message"], "Feedback submitted successfully. Thank you for helping us improve Inclusia!")
        self.assertIn("id", res_json["data"])

        # Check Firestore set call
        self.mock_db.collection.assert_called_with("feedbacks")
        self.mock_doc.set.assert_called_once()
        saved_data = self.mock_doc.set.call_args[0][0]
        self.assertEqual(saved_data["targetId"], "doc-uuid-abc")
        self.assertEqual(saved_data["rating"], "EXCELLENT")
        self.assertEqual(saved_data["tags"], ["Easy Understand", "Well Summarized"])
        self.assertEqual(saved_data["comment"], "Highly recommended and readable!")
        self.assertIn("createdAt", saved_data)
        self.assertIn("updatedAt", saved_data)

    def test_post_feedback_success_bad_triggers_loop(self):
        # 2. IMAGE feedback with BAD rating, triggers prompt optimization loop
        payload = {
            "targetId": "img-uuid-xyz",
            "targetType": "IMAGE",
            "rating": "BAD",
            "tags": ["Too Complicated"],
            "comment": "The text was way too complex for screen reader users."
        }

        # Mock collection for prompt_evaluations
        mock_eval_doc = MagicMock()
        
        def get_collection(name):
            col = MagicMock()
            if name == "feedbacks":
                col.document.return_value = self.mock_doc
            elif name == "prompt_evaluations":
                col.document.return_value = mock_eval_doc
            return col
            
        self.mock_db.collection.side_effect = get_collection

        response = self.client.post(
            '/api/v1/feedback',
            json=payload,
            headers=self.auth_headers
        )

        self.assertEqual(response.status_code, 200)
        res_json = response.get_json()
        self.assertTrue(res_json["success"])
        
        # Verify both collections (feedbacks & prompt_evaluations) are called
        self.assertTrue(self.mock_db.collection.called)
        mock_eval_doc.set.assert_called_once()
        eval_data = mock_eval_doc.set.call_args[0][0]
        self.assertEqual(eval_data["targetId"], "img-uuid-xyz")
        self.assertEqual(eval_data["rating"], "BAD")
        self.assertEqual(eval_data["tags"], ["Too Complicated"])
        self.assertEqual(eval_data["status"], "PENDING_OPTIMIZATION")

    def test_post_feedback_invalid_target_type(self):
        # 3. Invalid targetType value
        payload = {
            "targetId": "doc-uuid-abc",
            "targetType": "VIDEO",  # Invalid
            "rating": "GOOD",
            "tags": []
        }
        response = self.client.post(
            '/api/v1/feedback',
            json=payload,
            headers=self.auth_headers
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["status"], "error")
        self.assertIn("Invalid targetType", response.get_json()["message"])

    def test_post_feedback_comment_too_long(self):
        # 4. Comment exceeds 300 characters
        payload = {
            "targetId": "doc-uuid-abc",
            "targetType": "DOCUMENT",
            "rating": "OKAY",
            "tags": ["Missing Information"],
            "comment": "A" * 301
        }
        response = self.client.post(
            '/api/v1/feedback',
            json=payload,
            headers=self.auth_headers
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["status"], "error")
        self.assertIn("Comment must not exceed 300 characters", response.get_json()["message"])

    def test_post_feedback_missing_required_fields(self):
        # 5. Missing targetId
        payload = {
            "targetType": "DOCUMENT",
            "rating": "GOOD",
            "tags": []
        }
        response = self.client.post(
            '/api/v1/feedback',
            json=payload,
            headers=self.auth_headers
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["status"], "error")
        self.assertIn("Missing required fields", response.get_json()["message"])

    @patch('agents.feedback_agent.run_feedback_agent_sync')
    def test_process_pending_optimizations_success(self, mock_generate_content):
        # Setup mock for GeminiService generate_content
        mock_generate_content.return_value = "Optimized prompt instructions context_before_str context_after_str"

        # Mock evaluation document
        mock_eval = MagicMock()
        mock_eval.id = "eval-uuid-123"
        mock_eval.to_dict.return_value = {
            "id": "eval-uuid-123",
            "feedbackId": "feedback-uuid-123",
            "targetId": "img-123",
            "targetType": "IMAGE",
            "rating": "BAD",
            "tags": ["Too Complicated"],
            "comment": "Rumus matematikanya terlalu bertele-tele, susah dipahami anak low vision"
        }

        # Mock collection query results
        mock_query = MagicMock()
        mock_query.stream.return_value = [mock_eval]

        # Setup db mapping
        mock_system_prompt_doc = MagicMock()
        mock_eval_doc = MagicMock()

        def get_collection(name):
            col = MagicMock()
            if name == "prompt_evaluations":
                # For query
                col.where.return_value = mock_query
                # For update
                col.document.return_value = mock_eval_doc
            elif name == "system_prompts":
                col.document.return_value = mock_system_prompt_doc
            return col

        self.mock_db.collection.side_effect = get_collection

        # Send POST request to /api/v1/feedback/optimize
        response = self.client.post(
            '/api/v1/feedback/optimize',
            headers=self.auth_headers
        )

        self.assertEqual(response.status_code, 200)
        res_json = response.get_json()
        self.assertTrue(res_json["success"])
        self.assertEqual(res_json["data"]["processedCount"], 1)

        # Assert set was called on system prompts doc and update on evaluation doc
        mock_system_prompt_doc.set.assert_called_once()
        saved_prompt = mock_system_prompt_doc.set.call_args[0][0]
        self.assertEqual(saved_prompt["prompt"], "Optimized prompt instructions context_before_str context_after_str")

        mock_eval_doc.update.assert_called_once()
        updated_data = mock_eval_doc.update.call_args[0][0]
        self.assertEqual(updated_data["status"], "OPTIMIZED")

    def test_post_feedback_snake_case_and_int_rating_success(self):
        payload = {
            "target_id": "doc-uuid-111",
            "target_type": "document",
            "rating": 5,
            "tags": ["Easy Understand"],
            "comment": "Nice job!"
        }

        response = self.client.post(
            '/api/v1/feedback',
            json=payload,
            headers=self.auth_headers
        )

        self.assertEqual(response.status_code, 200)
        res_json = response.get_json()
        self.assertTrue(res_json["success"])
        
        # Verify mapped fields inside set call
        self.mock_doc.set.assert_called_once()
        saved_data = self.mock_doc.set.call_args[0][0]
        self.assertEqual(saved_data["targetId"], "doc-uuid-111")
        self.assertEqual(saved_data["targetType"], "DOCUMENT")
        self.assertEqual(saved_data["rating"], "EXCELLENT")

if __name__ == '__main__':
    unittest.main()
