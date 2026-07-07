from google import genai
from google.genai import types
from typing import Optional, Dict
from config import Config
from prompts.agent_prompts import EDUCATIONAL_SUMMARY_PROMPT
from utils.logger import get_logger
from tenacity import retry, stop_after_attempt, wait_exponential

logger = get_logger(__name__)

_client = None

def get_gemini_client():
    global _client
    if _client is None:
        api_key = Config.GEMINI_API_KEY
        if not api_key or api_key.strip() == "" or api_key == "your_gemini_api_key_here":
            raise RuntimeError("GEMINI_API_KEY environment variable is not configured or is invalid.")
        _client = genai.Client(api_key=api_key)
    return _client

class GeminiService:
    @staticmethod
    def _handle_gemini_exception(e: Exception, action_name: str) -> Exception:
        error_message = str(e)
        logger.error(f"{action_name} failed: {error_message}")
        
        # Default message
        sanitized_message = "Gemini processing failure"
        
        # Map specific internal exception phrases
        if "API_KEY_INVALID" in error_message or "API key not valid" in error_message:
            sanitized_message = "Authentication failure"
        elif "PERMISSION_DENIED" in error_message or "denied access" in error_message.lower():
            sanitized_message = "Gemini API access denied. Please verify your API key and project status."
        elif "429" in error_message or "quota" in error_message.lower():
            sanitized_message = "Rate limit"
        elif "timeout" in error_message.lower() or "timed out" in error_message.lower():
            sanitized_message = "Timeout"
        elif "network" in error_message.lower() or "connection" in error_message.lower() or "endpoint" in error_message.lower():
            sanitized_message = "Network failure"
        elif "400" in error_message or "invalid" in error_message.lower():
            sanitized_message = "Invalid request"
            
        return RuntimeError(sanitized_message)

    @staticmethod
    def _get_thinking_budget(level: str) -> int:
        """Translate a conceptual thinking level to a token budget."""
        mapping = {
            'LOW': 1024,
            'MEDIUM': 2048,
            'HIGH': 2048
        }
        return mapping.get(level.upper(), 2048)

    @staticmethod
    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def generate_content(prompt: str, model_name: str = "gemini-3.5-flash", temperature: float = 0.2, response_mime_type: str = "text/plain") -> str:
        """Call Gemini to generate content based on a prompt."""
        try:
            thinking_level = "HIGH"
            config = types.GenerateContentConfig(
                temperature=temperature,
                response_mime_type=response_mime_type,
                thinking_config=types.ThinkingConfig(
                    thinking_budget=GeminiService._get_thinking_budget(thinking_level)
                )
            )
            response = get_gemini_client().models.generate_content(
                model=model_name,
                contents=prompt,
                config=config
            )
            return response.text
        except Exception as e:
            raise GeminiService._handle_gemini_exception(e, "Generate content")

    @classmethod
    def process(cls, text: str, document_id: Optional[str] = None, **kwargs) -> str:
        """
        Processes extracted document text to generate an accessible educational summary.
        """
        # Validate inputs
        if not text or not isinstance(text, str) or text.strip() == "":
            raise ValueError("Invalid input text")
            
        MAX_SAFE_CHARACTERS = 500000
        if len(text) > MAX_SAFE_CHARACTERS:
            raise ValueError("Input text exceeds maximum safe size")
            
        # Check API key configuration
        if not Config.GEMINI_API_KEY:
            raise RuntimeError("Missing API key")

        doc_id_val = document_id if document_id else ""
        logger.info(f"processing started. document_id: {doc_id_val}")

        try:
            model_name = getattr(Config, "GEMINI_MODEL", "gemini-3.5-flash")
            prompt_template = cls.get_active_prompt("educational_summary_prompt", EDUCATIONAL_SUMMARY_PROMPT)
            prompt = prompt_template.format(text=text)
            
            # Gunakan thinking_level="HIGH" untuk pemrosesan teks agar lebih matang
            thinking_level = "HIGH"
            config = types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(
                    thinking_budget=cls._get_thinking_budget(thinking_level)
                )
            )
            
            response = get_gemini_client().models.generate_content(
                model=model_name,
                contents=prompt,
                config=config
            )
            summary = response.text
            
            if not summary:
                raise ValueError("Generated summary is empty")

            logger.info(f"processing completed. document_id: {doc_id_val}")
            return summary.strip()

        except Exception as e:
            raise cls._handle_gemini_exception(e, f"Processing document {doc_id_val}")
    
    @classmethod
    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def interpret_image_accessibility(cls, image_path: str, context_before: str = "", context_after: str = "") -> Dict[str, str]:
        """
        Membaca gambar lokal dan meminta Gemini 3.5 Flash membuat 
        deskripsi untuk Totally Blind dan Deaf sekaligus dengan informasi konteks sekitar.
        """
        # Sanitize None values
        context_before_str = context_before if context_before is not None else ""
        context_after_str = context_after if context_after is not None else ""

        # Load gambar lokal menggunakan PIL Image
        from PIL import Image
        from pathlib import Path
        img_file = Path(image_path)
        if not img_file.exists():
            raise FileNotFoundError(f"Local image file not found: {image_path}")
            
        img = Image.open(image_path)

        # Buat Prompt instruksi khusus dua disabilitas dengan konteks sekitarnya
        default_image_prompt = """Anda adalah agen aksesibilitas. Analisislah gambar materi pelajaran ini. Gambar ini terletak di antara teks sebelum: "{context_before_str}" dan teks sesudah: "{context_after_str}". Gunakan konteks teks tersebut agar deskripsi gambar Anda akurat dan menyatu dengan materi pelajaran.
        
        Berikan dua jenis interpretasi teks:
        1. 'alt_text_totally_blind': Deskripsikan seluruh isi gambar secara linier, mendalam, dan mengalir untuk dibacakan oleh Screen Reader ke telinga tunanetra (tanpa simbol dekoratif atau kalimat pengantar visual). Gunakan pemahaman dari konteks sekitarnya untuk mendeskripsikan secara tepat.
        2. 'visual_explanation_deaf': Berikan penjelasan visual terstruktur menggunakan kalimat aktif yang pendek, sederhana, dan langsung ke inti materi untuk siswa tunarungu. Gunakan poin-poin jika menjelaskan bagian-bagian gambar.

        Format output wajib berupa JSON objek seperti ini:
        {{
            "alt_text_totally_blind": "...",
            "visual_explanation_deaf": "..."
        }}"""
        prompt_template = cls.get_active_prompt("image_accessibility_prompt", default_image_prompt)
        prompt = prompt_template.format(context_before_str=context_before_str, context_after_str=context_after_str)
        
        # Gunakan media_resolution: "HIGH" untuk pemrosesan multimodal gambar
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            media_resolution="MEDIA_RESOLUTION_HIGH"
        )
        
        try:
            # Panggil Gemini dengan mode JSON response menggunakan PIL Image
            response = get_gemini_client().models.generate_content(
                model="gemini-3.5-flash",
                contents=[img, prompt],
                config=config
            )
            
            import json
            result = json.loads(response.text)
            return result
        except Exception as e:
            raise cls._handle_gemini_exception(e, f"Interpret image accessibility {image_path}")

    @classmethod
    def get_active_prompt(cls, prompt_id: str, default_prompt: str) -> str:
        """
        Retrieves the active prompt from Firestore if configured, otherwise falls back to default.
        """
        try:
            from services import firebase_service
            doc_ref = firebase_service.db.collection("system_prompts").document(prompt_id).get()
            if doc_ref.exists:
                doc_data = doc_ref.to_dict() or {}
                active_prompt = doc_data.get("prompt")
                if active_prompt:
                    logger.info(f"Loaded active prompt '{prompt_id}' from Firestore.")
                    return active_prompt
        except Exception as e:
            logger.warning(f"Failed to load prompt '{prompt_id}' from Firestore, using default: {e}")
        return default_prompt