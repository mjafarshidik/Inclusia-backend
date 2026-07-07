from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Dict, List, Optional
from google.cloud.firestore import Client as FirestoreClient
from google.cloud.storage import Bucket as StorageBucket
from utils.logger import get_logger

logger = get_logger(__name__)

class FirebaseService:
    def __init__(self, db: Optional[FirestoreClient] = None, bucket: Optional[StorageBucket] = None):
        """Initializes the FirebaseService. Supports Dependency Injection of clients, falls back to firebase_client."""
        self._db = db
        self._bucket = bucket
        self.collection_name = "documents"
        from services.storage_service import StorageService
        self.storage_service = StorageService(bucket=bucket)

    @property
    def db(self) -> FirestoreClient:
        if self._db is None:
            from firebase.firebase import firebase_client
            return firebase_client.db
        return self._db

    @property
    def bucket(self) -> StorageBucket:
        if self._bucket is None:
            from firebase.firebase import firebase_client
            return firebase_client.bucket
        return self._bucket

    def upload_file(self, file: Any, destination: str, content_type: str = "application/pdf") -> str:
        """Uploads a file (or file-like object) to Firebase Storage and returns its public URL."""
        return self.storage_service.upload_file(file, destination, content_type)

    def save_document(self, id: str, data: Dict[str, Any]) -> None:
        """Saves or updates a document in Firestore (merge=True)."""
        try:
            logger.info(f"Saving/updating document: {id}")
            doc_ref = self.db.collection(self.collection_name).document(id)
            
            # Set update and creation timestamps safely
            updated_data = data.copy()
            updated_data['updated_at'] = datetime.now(timezone.utc)
            
            doc_ref.set(updated_data, merge=True)
            logger.info(f"Document {id} saved successfully.")
        except Exception as e:
            logger.error(f"Error saving Firestore document '{id}': {e}")
            raise e

    def get_document(self, id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a document from Firestore by ID."""
        try:
            logger.info(f"Retrieving document: {id}")
            doc_ref = self.db.collection(self.collection_name).document(id).get()
            if doc_ref.exists:
                doc_dict = doc_ref.to_dict() or {}
                doc_dict['id'] = doc_ref.id
                return doc_dict
            logger.info(f"Document {id} not found in Firestore.")
            return None
        except Exception as e:
            logger.error(f"Error retrieving Firestore document '{id}': {e}")
            raise e

    def list_documents(self, owner_id: str) -> List[Dict[str, Any]]:
        """Lists all documents in the 'documents' collection filtered by ownerId."""
        try:
            logger.info(f"Listing documents from Firestore for owner: {owner_id}")
            docs_stream = (
                self.db.collection(self.collection_name)
                .where("ownerId", "==", owner_id)
                .stream()
            )
            results = []
            for doc in docs_stream:
                doc_dict = doc.to_dict() or {}
                doc_dict['id'] = doc.id
                results.append(doc_dict)
            return results
        except Exception as e:
            logger.error(f"Error listing Firestore documents: {e}")
            raise e

    def delete_document(self, id: str) -> None:
        """Deletes a document from Firestore."""
        try:
            logger.info(f"Deleting document: {id}")
            self.db.collection(self.collection_name).document(id).delete()
            logger.info(f"Document {id} successfully deleted from Firestore.")
        except Exception as e:
            logger.error(f"Error deleting Firestore document '{id}': {e}")
            raise e

    def save_chat_message(self, doc_id: str, message: Dict[str, Any]) -> None:
        """Saves a chat message in the messages subcollection of a document."""
        try:
            logger.info(f"Saving chat message for document: {doc_id}")
            msg_data = message.copy()
            msg_data['created_at'] = datetime.now(timezone.utc)
            
            # Save message under documents/{doc_id}/messages subcollection
            self.db.collection(self.collection_name).document(doc_id).collection("messages").add(msg_data)
            logger.info(f"Chat message saved successfully for document {doc_id}.")
        except Exception as e:
            logger.error(f"Error saving chat message for document '{doc_id}': {e}")
            raise e

    def get_chat_history(self, doc_id: str) -> List[Dict[str, Any]]:
        """Retrieves chat history for a document, ordered by created_at ascending."""
        try:
            logger.info(f"Retrieving chat history for document: {doc_id}")
            msgs_stream = (
                self.db.collection(self.collection_name)
                .document(doc_id)
                .collection("messages")
                .order_by("created_at", direction="ASCENDING")
                .stream()
            )
            history = []
            for msg in msgs_stream:
                msg_dict = msg.to_dict() or {}
                history.append({
                    "role": msg_dict.get("role"),
                    "content": msg_dict.get("content")
                })
            logger.info(f"Retrieved {len(history)} chat history messages.")
            return history
        except Exception as e:
            logger.error(f"Error retrieving chat history for document '{doc_id}': {e}")
            raise e

    def download_file(self, destination: str) -> BytesIO:
        """Downloads a file from Firebase Storage and returns its content as a BytesIO stream."""
        return self.storage_service.download_file(destination)

    def list_documents_paginated(self, owner_id: str, page: int, page_size: int) -> Dict[str, Any]:
        """Lists documents in Firestore with pagination, ordering, and projection."""
        try:
            logger.info(f"Listing documents paginated for owner {owner_id}, page {page}, pageSize {page_size}")
            base_query = (
                self.db.collection(self.collection_name)
                .where("ownerId", "==", owner_id)
            )
            
            # Fetch total count
            count_results = base_query.count().get()
            total = 0
            if count_results:
                first_res = count_results[0]
                if isinstance(first_res, list) and len(first_res) > 0:
                    total = first_res[0].value
                elif hasattr(first_res, 'value'):
                    total = first_res.value
                else:
                    total = int(first_res)
            
            # Optimization: If total is 0, return empty data immediately without querying
            if total == 0:
                return {
                    "data": [],
                    "total": 0,
                    "page": page,
                    "pageSize": page_size,
                    "totalPages": 0
                }
            
            # Get paginated data
            offset = (page - 1) * page_size
            document_list = []
            try:
                docs = (
                    base_query.order_by("createdAt", direction="DESCENDING")
                    .select(["filename", "contentType", "status", "summary", "storagePath", "downloadUrl", "createdAt", "updatedAt", "ownerId"])
                    .offset(offset)
                    .limit(page_size)
                    .stream()
                )
                for doc in docs:
                    data = doc.to_dict()
                    data["id"] = doc.id
                    document_list.append(data)
            except Exception as e:
                # Self-healing fallback: If composite index is missing, sort and paginate in memory
                if "index" in str(e).lower() or "failed_precondition" in str(type(e)).lower():
                    logger.warning(f"Firestore index missing, falling back to in-memory sorting: {e}")
                    all_docs = (
                        base_query.select(["filename", "contentType", "status", "summary", "storagePath", "downloadUrl", "createdAt", "updatedAt", "ownerId"])
                        .stream()
                    )
                    all_list = []
                    for doc in all_docs:
                        data = doc.to_dict()
                        data["id"] = doc.id
                        all_list.append(data)
                    
                    # Safe sorting key to prevent TypeError between datetime and string
                    all_list.sort(
                        key=lambda x: (
                            x.get("createdAt").isoformat()
                            if hasattr(x.get("createdAt"), "isoformat")
                            else str(x.get("createdAt") or "")
                        ),
                        reverse=True
                    )
                    document_list = all_list[offset : offset + page_size]
                else:
                    raise e
                
            return {
                "data": document_list,
                "total": total
            }
        except Exception as e:
            logger.error(f"Error listing documents paginated for owner '{owner_id}': {e}")
            raise e

    def save_user_profile(self, uid: str, profile_data: Dict[str, Any]) -> None:
        """Saves or updates a user profile document in the 'users' collection."""
        try:
            logger.info(f"Saving/updating user profile: {uid}")
            doc_ref = self.db.collection("users").document(uid)
            doc_ref.set(profile_data, merge=True)
            logger.info(f"User profile {uid} saved successfully.")
        except Exception as e:
            logger.error(f"Error saving Firestore user profile '{uid}': {e}")
            raise e

    def get_user_profile(self, uid: str) -> Optional[Dict[str, Any]]:
        """Retrieves a user profile document from the 'users' collection by UID."""
        try:
            logger.info(f"Retrieving user profile: {uid}")
            doc_ref = self.db.collection("users").document(uid).get()
            if doc_ref.exists:
                return doc_ref.to_dict()
            logger.info(f"User profile {uid} not found in Firestore.")
            return None
        except Exception as e:
            logger.error(f"Error retrieving Firestore user profile '{uid}': {e}")
            raise e

