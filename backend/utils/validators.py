from typing import Any, Optional

def is_valid_pdf(filename: str) -> bool:
    """Validates if the filename has a .pdf extension."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() == 'pdf'

def normalize_accessibility_mode(raw_mode: Any) -> Optional[str]:
    """
    Normalizes accessibility mode strings.
    Accepts aliases like 'DEAF', lowercase/mixedcase, and spaces.
    Returns canonical mode in {'TOTALLY_BLIND', 'LOW_VISION', 'DEAF_HEARING'} or None if invalid.
    """
    if not raw_mode:
        return None
    mode = str(raw_mode).strip().upper().replace(" ", "_")
    if mode == "DEAF":
        mode = "DEAF_HEARING"
    allowed_modes = {"TOTALLY_BLIND", "LOW_VISION", "DEAF_HEARING"}
    return mode if mode in allowed_modes else None

