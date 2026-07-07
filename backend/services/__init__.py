from services.firebase_service import FirebaseService
from services.document_service import DocumentService
from services.chat_service import ChatService
from services.document_processing_service import DocumentProcessingService
from services.user_service import UserService

# Centralized Dependency Injection
# By default, FirebaseService lazily loads its dependencies from firebase_client.
# This prevents import-time errors when Firebase credentials are not yet configured.
# You can explicitly inject mock clients for testing: FirebaseService(db=mock_db, bucket=mock_bucket)
firebase_service = FirebaseService()

document_service = DocumentService(firebase_service=firebase_service)
chat_service = ChatService(firebase_service=firebase_service)
document_processing_service = DocumentProcessingService(firebase_service=firebase_service)
user_service = UserService(firebase_service=firebase_service)

# Bind class objects on instance variables to support string-based unit test patching
# without clashing with the package namespace.
firebase_service.FirebaseService = FirebaseService
document_service.DocumentService = DocumentService
chat_service.ChatService = ChatService
document_processing_service.DocumentProcessingService = DocumentProcessingService
user_service.UserService = UserService

__all__ = ["firebase_service", "document_service", "chat_service", "document_processing_service", "user_service"]
