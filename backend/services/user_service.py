from datetime import datetime, timezone
from typing import Any, Dict, Optional
from services.firebase_service import FirebaseService

class UserService:
    def __init__(self, firebase_service: FirebaseService):
        self.firebase_service = firebase_service

    def get_profile(self, uid: str) -> Optional[Dict[str, Any]]:
        """Retrieves user profile from Firestore."""
        return self.firebase_service.get_user_profile(uid)

    def update_profile(
        self,
        uid: str,
        email: Optional[str],
        display_name: Optional[str],
        photo_url: Optional[str],
        update_data: Dict[str, Any]
    ) -> str:
        """Saves or updates user profile metadata and preferences in Firestore."""
        profile = self.firebase_service.get_user_profile(uid)
        now = datetime.now(timezone.utc)
        
        if profile is None:
            # Document does not exist, create complete profile
            new_profile = {
                "uid": uid,
                "email": email,
                "displayName": display_name,
                "photoUrl": photo_url,
                "createdAt": now,
                "updatedAt": now
            }
            # Merge with incoming preference fields
            new_profile.update(update_data)
            self.firebase_service.save_user_profile(uid, new_profile)
            return "created"
        else:
            # Document exists, update preference fields and updatedAt only
            to_update = update_data.copy()
            to_update["updatedAt"] = now
            self.firebase_service.save_user_profile(uid, to_update)
            return "updated"
