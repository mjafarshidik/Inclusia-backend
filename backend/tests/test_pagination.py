import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from app import create_app
from firebase_admin import auth

class TestDocumentPagination(unittest.TestCase):
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
            "name": "Alice Smith"
        }
        self.auth_headers = {'Authorization': 'Bearer alice_token'}

    def tearDown(self):
        self.verify_patcher.stop()

    @patch('services.firebase_service.FirebaseService.list_documents_paginated')
    def test_list_authenticated_user_with_documents(self, mock_list_paginated):
        # 1. Mock database return for user with documents
        dt1 = datetime(2026, 6, 30, 10, 0, 0, tzinfo=timezone.utc)
        mock_list_paginated.return_value = {
            "data": [
                {
                    "id": "doc_1",
                    "filename": "file1.pdf",
                    "contentType": "application/pdf",
                    "status": "READY",
                    "summary": "This is a summary",
                    "storagePath": "documents/doc_1.pdf",
                    "downloadUrl": "https://storage.url/doc_1.pdf",
                    "createdAt": dt1,
                    "updatedAt": dt1,
                    "ownerId": "anonymous"
                }
            ],
            "total": 1
        }

        response = self.client.get('/api/v1/documents', headers=self.auth_headers)
        self.assertEqual(response.status_code, 200)
        
        res_json = response.get_json()
        self.assertIn("data", res_json)
        self.assertEqual(len(res_json["data"]), 1)
        
        doc = res_json["data"][0]
        self.assertEqual(doc["id"], "doc_1")
        self.assertEqual(doc["filename"], "file1.pdf")
        self.assertEqual(doc["contentType"], "application/pdf")
        self.assertEqual(doc["status"], "READY")
        self.assertEqual(doc["summary"], "This is a summary")
        self.assertEqual(doc["storagePath"], "documents/doc_1.pdf")
        self.assertEqual(doc["downloadUrl"], "https://storage.url/doc_1.pdf")
        self.assertEqual(doc["createdAt"], "2026-06-30T10:00:00Z")
        self.assertEqual(doc["updatedAt"], "2026-06-30T10:00:00Z")
        
        # Verify pagination meta
        pagination = res_json["pagination"]
        self.assertEqual(pagination["page"], 1)
        self.assertEqual(pagination["pageSize"], 20)
        self.assertEqual(pagination["total"], 1)
        self.assertFalse(pagination["hasNext"])

    @patch('services.firebase_service.FirebaseService.list_documents_paginated')
    def test_list_authenticated_user_without_documents(self, mock_list_paginated):
        # Mock empty return
        mock_list_paginated.return_value = {
            "data": [],
            "total": 0
        }

        response = self.client.get('/api/v1/documents', headers=self.auth_headers)
        self.assertEqual(response.status_code, 200)
        
        res_json = response.get_json()
        self.assertEqual(res_json["data"], [])
        self.assertEqual(res_json["pagination"]["total"], 0)
        self.assertFalse(res_json["pagination"]["hasNext"])

    @patch('services.firebase_service.FirebaseService.list_documents_paginated')
    def test_pagination_parameters_and_boundaries(self, mock_list_paginated):
        mock_list_paginated.return_value = {
            "data": [],
            "total": 150
        }

        # Page 2, Page size 15
        response = self.client.get('/api/v1/documents?page=2&pageSize=15', headers=self.auth_headers)
        self.assertEqual(response.status_code, 200)
        mock_list_paginated.assert_called_with("alice", 2, 15)
        res_json = response.get_json()
        self.assertTrue(res_json["pagination"]["hasNext"])

        # Page size above limit (120 -> 100)
        response = self.client.get('/api/v1/documents?page=1&pageSize=120', headers=self.auth_headers)
        self.assertEqual(response.status_code, 200)
        mock_list_paginated.assert_called_with("alice", 1, 100)

        # Invalid/negative parameters
        response = self.client.get('/api/v1/documents?page=-5&pageSize=-10', headers=self.auth_headers)
        self.assertEqual(response.status_code, 200)
        mock_list_paginated.assert_called_with("alice", 1, 20)

    @patch('services.firebase_service.FirebaseService.list_documents_paginated')
    def test_firestore_failure_returns_500(self, mock_list_paginated):
        mock_list_paginated.side_effect = Exception("Firestore connection timeout")

        response = self.client.get('/api/v1/documents', headers=self.auth_headers)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json()["error"]["message"], "Internal server error")

    def test_firestore_query_ordering_and_projection(self):
        from services.firebase_service import FirebaseService
        
        # Setup mock db chain
        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_where = MagicMock()
        mock_count = MagicMock()
        mock_order_by = MagicMock()
        mock_select = MagicMock()
        mock_offset = MagicMock()
        mock_limit = MagicMock()
        
        mock_db.collection.return_value = mock_collection
        mock_collection.where.return_value = mock_where
        
        # Mock count chain
        mock_where.count.return_value = mock_count
        mock_agg = MagicMock()
        mock_agg.value = 10
        mock_count.get.return_value = [[mock_agg]]
        
        # Mock documents fetch chain
        mock_where.order_by.return_value = mock_order_by
        mock_order_by.select.return_value = mock_select
        mock_select.offset.return_value = mock_offset
        mock_offset.limit.return_value = mock_limit
        mock_limit.stream.return_value = []
        
        firebase_service = FirebaseService(db=mock_db)
        firebase_service.list_documents_paginated("anonymous", page=2, page_size=15)
        
        # Assertions to verify the query parameters:
        mock_collection.where.assert_called_with("ownerId", "==", "anonymous")
        mock_where.order_by.assert_called_with("createdAt", direction="DESCENDING")
        mock_order_by.select.assert_called_with(["filename", "contentType", "status", "summary", "storagePath", "downloadUrl", "createdAt", "updatedAt", "ownerId"])
        mock_select.offset.assert_called_with(15)
        mock_offset.limit.assert_called_with(15)

if __name__ == '__main__':
    unittest.main()
