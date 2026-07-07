import io
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from app import create_app
from firebase_admin import auth

class TestUserIsolation(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

        # In-memory document and image databases to track records across requests
        self.documents_db = {}
        self.images_db = {}

        # Set up mock verify_id_token
        self.verify_patcher = patch('firebase_admin.auth.verify_id_token')
        self.mock_verify = self.verify_patcher.start()
        self.mock_verify.side_effect = self.mock_verify_token

        # Set up mock upload_file to return dummy GCS paths
        self.upload_patcher = patch('services.firebase_service.FirebaseService.upload_file')
        self.mock_upload = self.upload_patcher.start()
        self.mock_upload.side_effect = lambda f, dest, content_type=None: f"https://storage.googleapis.com/inclusia-test/{dest}"

        # Set up mock get_document, save_document, list_documents_paginated on FirebaseService
        self.get_doc_patcher = patch('services.firebase_service.FirebaseService.get_document')
        self.mock_get_doc = self.get_doc_patcher.start()
        self.mock_get_doc.side_effect = self.documents_db.get

        self.save_doc_patcher = patch('services.firebase_service.FirebaseService.save_document')
        self.mock_save_doc = self.save_doc_patcher.start()
        self.mock_save_doc.side_effect = self.save_document_mock

        self.list_docs_patcher = patch('services.firebase_service.FirebaseService.list_documents_paginated')
        self.mock_list_docs = self.list_docs_patcher.start()
        self.mock_list_docs.side_effect = self.list_documents_paginated_mock

        # Setup mock db for image routes
        self.db_patcher = patch('services.firebase_service.FirebaseService.db')
        self.mock_db = self.db_patcher.start()
        self.mock_db.collection.side_effect = self.mock_collection

        # Mock Thread to execute target function synchronously
        self.thread_patcher = patch('routes.image_routes.threading.Thread')
        self.mock_thread = self.thread_patcher.start()
        
        def run_sync(target, args=(), kwargs=None):
            mock_t = MagicMock()
            mock_t.start.side_effect = lambda: target(*args, **(kwargs or {}))
            return mock_t
            
        self.mock_thread.side_effect = run_sync

        # Authentication headers
        self.google_headers = {'Authorization': 'Bearer google_token'}
        self.anon_headers = {'Authorization': 'Bearer anon_token'}

    def tearDown(self):
        self.verify_patcher.stop()
        self.upload_patcher.stop()
        self.get_doc_patcher.stop()
        self.save_doc_patcher.stop()
        self.list_docs_patcher.stop()
        self.db_patcher.stop()
        self.thread_patcher.stop()

    def mock_verify_token(self, token, check_revoked=True):
        if token == "google_token":
            return {
                "uid": "google_user_123",
                "email": "google@example.com",
                "name": "Google User",
                "picture": "https://google.com/pic.png"
            }
        elif token == "anon_token":
            return {
                "uid": "anon_user_456"
            }
        else:
            raise auth.InvalidIdTokenError("Invalid token")

    def save_document_mock(self, doc_id, data):
        if doc_id in self.documents_db:
            self.documents_db[doc_id].update(data)
        else:
            self.documents_db[doc_id] = data

    def list_documents_paginated_mock(self, owner_id, page, page_size):
        filtered = [d for d in self.documents_db.values() if d.get("ownerId") == owner_id]
        return {
            "data": filtered[(page-1)*page_size : page*page_size],
            "total": len(filtered)
        }

    def mock_collection(self, collection_name):
        mock_coll = MagicMock()
        
        # document() returns a mocked Firestore DocumentReference
        def mock_document(doc_id):
            mock_doc_ref = MagicMock()
            
            def get_mock():
                mock_snapshot = MagicMock()
                if collection_name == "uploaded_images" and doc_id in self.images_db:
                    mock_snapshot.exists = True
                    mock_snapshot.id = doc_id
                    mock_snapshot.to_dict.return_value = self.images_db[doc_id]
                else:
                    mock_snapshot.exists = False
                return mock_snapshot

            def set_mock(data, merge=True):
                if collection_name == "uploaded_images":
                    if doc_id in self.images_db:
                        self.images_db[doc_id].update(data)
                    else:
                        self.images_db[doc_id] = data
            
            mock_doc_ref.get.side_effect = get_mock
            mock_doc_ref.set.side_effect = set_mock
            return mock_doc_ref

        mock_coll.document.side_effect = mock_document

        # where() for queries (like list_images)
        def mock_where(field, op, val):
            mock_query = MagicMock()
            def stream_mock():
                results = []
                if collection_name == "uploaded_images":
                    for doc_id, data in self.images_db.items():
                        if field == "ownerId" and data.get("ownerId") == val:
                            mock_snap = MagicMock()
                            mock_snap.id = doc_id
                            mock_snap.to_dict.return_value = data
                            results.append(mock_snap)
                return results
            mock_query.stream.side_effect = stream_mock
            return mock_query

        mock_coll.where.side_effect = mock_where
        return mock_coll

    @patch('routes.document_routes.document_processing_service.process_document')
    def test_document_isolation_flow(self, mock_process):
        # 1. User A (Google) uploads a document
        pdf_data = b"%PDF-1.4 dummy pdf content"
        response = self.client.post(
            '/api/v1/documents/upload',
            data={'file': (io.BytesIO(pdf_data), 'google_doc.pdf', 'application/pdf')},
            content_type='multipart/form-data',
            headers=self.google_headers
        )
        self.assertEqual(response.status_code, 201)
        google_doc_id = response.get_json()['data']['id']

        # Confirm the document is owned by Google User
        self.assertIn(google_doc_id, self.documents_db)
        self.assertEqual(self.documents_db[google_doc_id]['ownerId'], 'google_user_123')

        # 2. User B (Anon) uploads a document
        response = self.client.post(
            '/api/v1/documents/upload',
            data={'file': (io.BytesIO(pdf_data), 'anon_doc.pdf', 'application/pdf')},
            content_type='multipart/form-data',
            headers=self.anon_headers
        )
        self.assertEqual(response.status_code, 201)
        anon_doc_id = response.get_json()['data']['id']

        # Confirm the document is owned by Anon User
        self.assertIn(anon_doc_id, self.documents_db)
        self.assertEqual(self.documents_db[anon_doc_id]['ownerId'], 'anon_user_456')

        # 3. User B (Anon) tries to retrieve User A's document -> 403 Forbidden
        response = self.client.get(f'/api/v1/documents/{google_doc_id}', headers=self.anon_headers)
        self.assertEqual(response.status_code, 403)

        # 4. User A (Google) retrieves their own document -> 200 OK
        response = self.client.get(f'/api/v1/documents/{google_doc_id}', headers=self.google_headers)
        self.assertEqual(response.status_code, 200)

        # 5. User B (Anon) tries to process User A's document -> 403 Forbidden
        response = self.client.post(f'/api/v1/documents/{google_doc_id}/process', headers=self.anon_headers)
        self.assertEqual(response.status_code, 403)

        # 6. Listing documents for User A -> only returns User A's document
        response = self.client.get('/api/v1/documents', headers=self.google_headers)
        self.assertEqual(response.status_code, 200)
        google_list = response.get_json()['data']
        self.assertEqual(len(google_list), 1)
        self.assertEqual(google_list[0]['id'], google_doc_id)

        # Listing documents for User B -> only returns User B's document
        response = self.client.get('/api/v1/documents', headers=self.anon_headers)
        self.assertEqual(response.status_code, 200)
        anon_list = response.get_json()['data']
        self.assertEqual(len(anon_list), 1)
        self.assertEqual(anon_list[0]['id'], anon_doc_id)

    @patch('services.gemini_service.GeminiService.interpret_image_accessibility')
    def test_image_isolation_flow(self, mock_gemini):
        mock_gemini.return_value = {
            "alt_text_totally_blind": "Mock alt text",
            "visual_explanation_deaf": "Mock explanation"
        }

        # 1. User A (Google) uploads/processes an image
        img_data = b"fake image bytes"
        response = self.client.post(
            '/api/v1/images/process',
            data={'file': (io.BytesIO(img_data), 'google_pic.jpg', 'image/jpeg')},
            content_type='multipart/form-data',
            headers=self.google_headers
        )
        self.assertEqual(response.status_code, 202)
        google_img_id = response.get_json()['data']['id']

        # Confirm ownership
        self.assertIn(google_img_id, self.images_db)
        self.assertEqual(self.images_db[google_img_id]['ownerId'], 'google_user_123')

        # 2. User B (Anon) uploads/processes an image
        response = self.client.post(
            '/api/v1/images/process',
            data={'file': (io.BytesIO(img_data), 'anon_pic.jpg', 'image/jpeg')},
            content_type='multipart/form-data',
            headers=self.anon_headers
        )
        self.assertEqual(response.status_code, 202)
        anon_img_id = response.get_json()['data']['id']

        # Confirm ownership
        self.assertIn(anon_img_id, self.images_db)
        self.assertEqual(self.images_db[anon_img_id]['ownerId'], 'anon_user_456')

        # 3. User B (Anon) tries to retrieve User A's image -> 403 Forbidden
        response = self.client.get(f'/api/v1/images/{google_img_id}', headers=self.anon_headers)
        self.assertEqual(response.status_code, 403)

        # 4. User A (Google) retrieves their own image -> 200 OK
        response = self.client.get(f'/api/v1/images/{google_img_id}', headers=self.google_headers)
        self.assertEqual(response.status_code, 200)

        # 5. User B (Anon) lists images -> only sees User B's image
        response = self.client.get('/api/v1/images', headers=self.anon_headers)
        self.assertEqual(response.status_code, 200)
        anon_imgs = response.get_json()['data']
        self.assertEqual(len(anon_imgs), 1)
        self.assertEqual(anon_imgs[0]['id'], anon_img_id)

    def test_profile_handling(self):
        # 1. Get profile for User B (Anon) -> fields email/name are None/graceful
        response = self.client.get('/api/v1/profile', headers=self.anon_headers)
        self.assertEqual(response.status_code, 200)
        res_json = response.get_json()
        self.assertEqual(res_json["data"]["uid"], "anon_user_456")
        self.assertIsNone(res_json["data"]["email"])
        self.assertIsNone(res_json["data"]["name"])

        # 2. Get profile for User A (Google) -> email/name populated from token
        response = self.client.get('/api/v1/profile', headers=self.google_headers)
        self.assertEqual(response.status_code, 200)
        res_json = response.get_json()
        self.assertEqual(res_json["data"]["uid"], "google_user_123")
        self.assertEqual(res_json["data"]["email"], "google@example.com")
        self.assertEqual(res_json["data"]["name"], "Google User")

if __name__ == '__main__':
    unittest.main()
