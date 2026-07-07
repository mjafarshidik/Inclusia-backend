import io
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from app import create_app
from firebase_admin import auth

class TestProfileAccessibility(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

        # Patch verify_id_token
        self.verify_patcher = patch('firebase_admin.auth.verify_id_token')
        self.mock_verify = self.verify_patcher.start()
        self.mock_verify.return_value = {
            "uid": "alice",
            "email": "alice@example.com",
            "name": "Alice Smith",
            "picture": "https://alice.pic"
        }
        self.auth_headers = {'Authorization': 'Bearer alice_token'}

    def tearDown(self):
        self.verify_patcher.stop()

    @patch('services.firebase_service.FirebaseService.get_user_profile')
    def test_fetch_profile_without_accessibility_mode(self, mock_get_user_profile):
        # 1. User profile does not exist in collection
        mock_get_user_profile.return_value = None

        response = self.client.get('/api/v1/profile', headers=self.auth_headers)
        self.assertEqual(response.status_code, 200)
        
        res_json = response.get_json()
        self.assertTrue(res_json["success"])
        self.assertEqual(res_json["data"]["uid"], "alice")
        self.assertEqual(res_json["data"]["email"], "alice@example.com")
        self.assertEqual(res_json["data"]["displayName"], "Alice Smith")
        self.assertEqual(res_json["data"]["photoUrl"], "https://alice.pic")
        self.assertIsNone(res_json["data"]["accessibilityMode"])

        mock_get_user_profile.assert_called_once_with("alice")

    @patch('services.firebase_service.FirebaseService.get_user_profile')
    def test_fetch_profile_with_accessibility_mode(self, mock_get_user_profile):
        # 2. User profile exists in collection
        mock_get_user_profile.return_value = {
            "uid": "alice",
            "email": "alice@example.com",
            "displayName": "Alice Smith",
            "photoUrl": "https://alice.pic",
            "accessibilityMode": "LOW_VISION"
        }

        response = self.client.get('/api/v1/profile', headers=self.auth_headers)
        self.assertEqual(response.status_code, 200)
        
        res_json = response.get_json()
        self.assertTrue(res_json["success"])
        self.assertEqual(res_json["data"]["accessibilityMode"], "LOW_VISION")

    @patch('services.firebase_service.FirebaseService.save_user_profile')
    @patch('services.firebase_service.FirebaseService.get_user_profile')
    def test_create_new_accessibility_profile(self, mock_get_user_profile, mock_save_user_profile):
        # 3. User does not exist, should call set with merge=True for creation
        mock_get_user_profile.return_value = None

        response = self.client.post(
            '/api/v1/profile/accessibility',
            json={"mode": "TOTALLY_BLIND"},
            headers=self.auth_headers
        )
        self.assertEqual(response.status_code, 200)
        
        res_json = response.get_json()
        self.assertTrue(res_json["success"])
        self.assertIn("created", res_json["message"])

        # Check firebase save_user_profile call
        mock_save_user_profile.assert_called_once()
        saved_data = mock_save_user_profile.call_args[0][1]
        self.assertEqual(saved_data["uid"], "alice")
        self.assertEqual(saved_data["accessibilityMode"], "TOTALLY_BLIND")
        self.assertIn("createdAt", saved_data)
        self.assertIn("updatedAt", saved_data)

    @patch('services.firebase_service.FirebaseService.save_user_profile')
    @patch('services.firebase_service.FirebaseService.get_user_profile')
    def test_update_existing_accessibility_profile(self, mock_get_user_profile, mock_save_user_profile):
        # 4. User exists, should call update
        mock_get_user_profile.return_value = {
            "uid": "alice",
            "email": None,
            "displayName": None,
            "photoUrl": None,
            "accessibilityMode": "DEAF_HEARING",
            "createdAt": datetime.now(timezone.utc)
        }

        response = self.client.post(
            '/api/v1/profile/accessibility',
            json={"mode": "LOW_VISION"},
            headers=self.auth_headers
        )
        self.assertEqual(response.status_code, 200)
        
        res_json = response.get_json()
        self.assertTrue(res_json["success"])
        self.assertIn("updated", res_json["message"])

        mock_save_user_profile.assert_called_once()
        updated_data = mock_save_user_profile.call_args[0][1]
        self.assertEqual(updated_data["accessibilityMode"], "LOW_VISION")
        self.assertNotIn("createdAt", updated_data) # Do not overwrite createdAt
        self.assertIn("updatedAt", updated_data)

    def test_invalid_accessibility_mode(self):
        # 5. Invalid mode string
        response = self.client.post(
            '/api/v1/profile/accessibility',
            json={"mode": "INVALID_MODE"},
            headers=self.auth_headers
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid accessibility mode", response.get_json()["error"]["message"])

    def test_missing_mode_parameter(self):
        # 6. Missing mode parameter
        response = self.client.post(
            '/api/v1/profile/accessibility',
            json={},
            headers=self.auth_headers
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["message"], "Missing mode")

    def test_missing_body(self):
        # 7. No JSON body
        response = self.client.post(
            '/api/v1/profile/accessibility',
            headers=self.auth_headers
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["message"], "Missing body")

    @patch('services.firebase_service.FirebaseService.get_user_profile')
    def test_firestore_exception_handling(self, mock_get_user_profile):
        # 9. Firestore raises exception
        mock_get_user_profile.side_effect = Exception("Firestore read error")

        # GET profile
        response = self.client.get('/api/v1/profile', headers=self.auth_headers)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json()["error"]["message"], "Internal server error")

        # POST profile
        response_post = self.client.post(
            '/api/v1/profile/accessibility',
            json={"mode": "TOTALLY_BLIND"},
            headers=self.auth_headers
        )
        self.assertEqual(response_post.status_code, 500)
        self.assertEqual(response_post.get_json()["error"]["message"], "Internal server error")

    @patch('services.user_service.UserService.update_profile')
    def test_put_user_profile_success(self, mock_update_profile):
        mock_update_profile.return_value = "updated"
        
        response = self.client.put(
            '/api/v1/user/profile',
            json={"mode": "TOTALLY_BLIND"},
            headers=self.auth_headers
        )
        
        self.assertEqual(response.status_code, 200)
        res_json = response.get_json()
        self.assertTrue(res_json["success"])
        self.assertEqual(res_json["data"]["accessibilityMode"], "TOTALLY_BLIND")
        mock_update_profile.assert_called_once_with(
            uid="alice",
            email="alice@example.com",
            display_name="Alice Smith",
            photo_url="https://alice.pic",
            update_data={"accessibilityMode": "TOTALLY_BLIND"}
        )

    def test_put_user_profile_invalid_mode(self):
        response = self.client.put(
            '/api/v1/user/profile',
            json={"mode": "INVALID_MODE_NAME"},
            headers=self.auth_headers
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid accessibility mode", response.get_json()["error"]["message"])

    def test_put_user_profile_missing_mode(self):
        response = self.client.put(
            '/api/v1/user/profile',
            json={},
            headers=self.auth_headers
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Missing accessibility mode", response.get_json()["error"]["message"])

    @patch('services.firebase_service.FirebaseService.upload_file')
    @patch('services.firebase_service.FirebaseService.save_user_profile')
    @patch('services.firebase_service.FirebaseService.get_user_profile')
    def test_upload_avatar_success(self, mock_get_user_profile, mock_save_user_profile, mock_upload_file):
        # Configure mocks
        mock_get_user_profile.return_value = {
            "uid": "alice",
            "accessibilityMode": "LOW_VISION"
        }
        mock_upload_file.return_value = "https://storage.googleapis.com/inclusia-test/avatars/alice_123.png"
        
        avatar_data = b"fake image bytes"
        data = {
            'file': (io.BytesIO(avatar_data), 'avatar.png', 'image/png')
        }
        
        response = self.client.post(
            '/api/v1/profile/avatar',
            data=data,
            content_type='multipart/form-data',
            headers=self.auth_headers
        )
        
        self.assertEqual(response.status_code, 200)
        res_json = response.get_json()
        self.assertTrue(res_json["success"])
        self.assertEqual(res_json["data"]["photoUrl"], "https://storage.googleapis.com/inclusia-test/avatars/alice_123.png")
        
        mock_upload_file.assert_called_once()
        mock_save_user_profile.assert_called_once()

    def test_upload_avatar_invalid_extension(self):
        invalid_data = b"fake text content"
        data = {
            'file': (io.BytesIO(invalid_data), 'text.txt', 'text/plain')
        }
        
        response = self.client.post(
            '/api/v1/profile/avatar',
            data=data,
            content_type='multipart/form-data',
            headers=self.auth_headers
        )
        
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid file type", response.get_json()["error"]["message"])

if __name__ == '__main__':
    unittest.main()
