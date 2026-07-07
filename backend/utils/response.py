from flask import jsonify

def success_response(message: str, data: dict = None, status_code: int = 200):
    """Standardized success response format."""
    response = {
        "success": True,
        "message": message,
        "data": data if data is not None else {}
    }
    return jsonify(response), status_code

def error_response(message: str, status_code: int = 400, details: dict = None):
    """Standardized canonical error response format with backward compatibility shims."""
    response = {
        "success": False,
        "error": {
            "code": status_code,
            "message": message
        },
        # Backward compatibility shims
        "message": message,
        "error_string": message,
        "status": "error",
        "code": status_code
    }
    if details:
        response["error"]["details"] = details
        response["details"] = details
    return jsonify(response), status_code
