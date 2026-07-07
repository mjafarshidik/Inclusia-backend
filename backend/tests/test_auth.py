import unittest
from unittest.mock import patch
from io import BytesIO

from app import create_app

class TestNoAuthentication(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    @patch('services.firebase_service.FirebaseService.get_user_profile')
    def test_profile_accessible_without_auth(self, mock_get_user_profile):
        mock_get_user_profile.return_value = None
        response = self.client.get('/api/v1/profile')
        self.assertEqual(response.status_code, 200)
        res_json = response.get_json()
        self.assertTrue(res_json["success"])
        self.assertEqual(res_json["data"]["uid"], "anonymous")

    @patch('services.firebase_service.FirebaseService.list_documents_paginated')
    def test_documents_list_accessible_without_auth(self, mock_list_paginated):
        mock_list_paginated.return_value = {
            "data": [],
            "total": 0
        }
        response = self.client.get('/api/v1/documents')
        self.assertEqual(response.status_code, 200)
        res_json = response.get_json()
        self.assertIn("data", res_json)

    @patch('services.firebase_service.FirebaseService.upload_file')
    @patch('services.firebase_service.FirebaseService.save_document')
    def test_upload_document_accessible_without_auth(self, mock_save_document, mock_upload_file):
        mock_upload_file.return_value = "https://storage.url/doc.pdf"
        data = {
            'file': (BytesIO(b"%PDF-1.4 dummy"), 'document.pdf', 'application/pdf')
        }
        response = self.client.post(
            '/api/v1/documents/upload',
            data=data,
            content_type='multipart/form-data'
        )
        # Should succeed or return validation errors, but not 401 Unauthorized
        self.assertIn(response.status_code, [200, 201])

if __name__ == '__main__':
    unittest.main()
