from functools import wraps
import uuid
from flask import g, request
from firebase_admin import auth
from firebase.firebase import firebase_client
from utils.logger import get_logger
from utils.response import error_response

logger = get_logger(__name__)

# Access the singleton firebase client to ensure Firebase Admin SDK is initialized
_ = firebase_client

class AuthenticatedUser:
    """Represents the authenticated user's Firebase profile claims."""
    def __init__(self, decoded_token: dict):
        self.uid = decoded_token.get("uid") or decoded_token.get("sub")
        self.email = decoded_token.get("email")
        self.name = decoded_token.get("name")
        self.picture = decoded_token.get("picture")

def firebase_auth_required(f):
    """Decorator to require/verify Firebase ID Token authentication on an endpoint.
    
    Permissive behavior (Option A):
    - If Authorization header is missing, request is allowed but g.user remains AnonymousUser.
    - If Authorization header is present, it is verified. If invalid, 401 is returned.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Generate or extract request correlation ID
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        g.request_id = request_id
        
        endpoint = request.path
        method = request.method

        auth_header = request.headers.get("Authorization")
        if not auth_header:
            # Permissive mode: allow request but guarantee g.user exists and has a uid.
            if not hasattr(g, 'user') or g.user is None or getattr(g.user, 'uid', None) is None:
                class AnonymousUser:
                    uid = "anonymous"
                    email = None
                    name = None
                    picture = None
                g.user = AnonymousUser()
            return f(*args, **kwargs)

        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            reason = "Invalid Bearer format"
            logger.warning(f"Authentication failure: request_id={request_id}, endpoint={endpoint}, reason={reason}")
            return error_response("Invalid Firebase token", 401)

        token = parts[1]
        try:
            # Verify the ID token checking for revocation
            decoded_token = auth.verify_id_token(token, check_revoked=True)
            
            # Store verified identity claims in g.user
            g.user = AuthenticatedUser(decoded_token)
            
            # Structured log for successful authentication
            logger.info(f"Authentication success: request_id={request_id}, user_uid={g.user.uid}, endpoint={endpoint}, method={method}")
            
        except auth.ExpiredIdTokenError:
            reason = "Token has expired"
            logger.warning(f"Authentication failure: request_id={request_id}, endpoint={endpoint}, reason={reason}")
            return error_response("Invalid Firebase token", 401)
            
        except auth.RevokedIdTokenError:
            reason = "Token has been revoked"
            logger.warning(f"Authentication failure: request_id={request_id}, endpoint={endpoint}, reason={reason}")
            return error_response("Invalid Firebase token", 401)
            
        except auth.InvalidIdTokenError:
            reason = "Token is invalid"
            logger.warning(f"Authentication failure: request_id={request_id}, endpoint={endpoint}, reason={reason}")
            return error_response("Invalid Firebase token", 401)
            
        except Exception as e:
            # Never expose internal SDK/network error details to client
            reason = f"Verification failed: {str(e)}"
            logger.warning(f"Authentication failure: request_id={request_id}, endpoint={endpoint}, reason={reason}")
            return error_response("Invalid Firebase token", 401)

        return f(*args, **kwargs)

    return decorated_function

