import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List
from utils.logger import get_logger
from services import firebase_service

logger = get_logger(__name__)

class FeedbackService:
    @staticmethod
    def submit_feedback(
        owner_id: str,
        target_id: str,
        target_type: Any,
        rating: Any,
        tags: List[str],
        comment: str = None
    ) -> str:
        """
        Saves user feedback to Firestore and triggers prompt optimization loop if rating is bad or tags are negative.
        """
        # Robust parameter formatting
        if isinstance(target_type, str):
            target_type = target_type.upper()
            
        if isinstance(rating, int):
            rating_map = {1: "BAD", 2: "BAD", 3: "OKAY", 4: "GOOD", 5: "EXCELLENT"}
            rating = rating_map.get(rating, "OKAY")
        elif isinstance(rating, str):
            rating = rating.upper()
            
        # Validate inputs
        if target_type not in ("DOCUMENT", "IMAGE"):
            raise ValueError("Invalid targetType. Must be 'DOCUMENT' or 'IMAGE'.")
        if rating not in ("EXCELLENT", "GOOD", "OKAY", "BAD"):
            raise ValueError("Invalid rating. Must be 'EXCELLENT', 'GOOD', 'OKAY', or 'BAD'.")
        if comment and len(comment) > 300:
            raise ValueError("Comment must not exceed 300 characters.")
            
        feedback_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        
        feedback_data = {
            "id": feedback_id,
            "ownerId": owner_id,
            "targetId": target_id,
            "targetType": target_type,
            "rating": rating,
            "tags": tags,
            "comment": comment or "",
            "createdAt": now,
            "updatedAt": now
        }
        
        # Save to Firestore feedbacks collection
        firebase_service.db.collection("feedbacks").document(feedback_id).set(feedback_data)
        logger.info(f"Feedback {feedback_id} saved to Firestore by user {owner_id}")
        
        # Check for bad rating or negative tags to trigger the feedback loop
        negative_tags = {"Missing Information", "Too Complicated", "Inaccurate", "Hard to Understand"}
        has_negative_tag = any(t in negative_tags for t in tags)
        
        if rating == "BAD" or has_negative_tag:
            FeedbackService.optimize_prompt_loop(feedback_data)
            
        return feedback_id

    @staticmethod
    def optimize_prompt_loop(feedback_data: Dict[str, Any]) -> None:
        """
        Logs and analyzes negative feedbacks to optimize future prompts.
        """
        logger.warning(
            f"Negative feedback detected! target_id={feedback_data['targetId']}, "
            f"target_type={feedback_data['targetType']}, rating={feedback_data['rating']}, "
            f"tags={feedback_data['tags']}, comment={feedback_data['comment']}. "
            f"Prompt optimization evaluation logged."
        )
        try:
            eval_id = str(uuid.uuid4())
            firebase_service.db.collection("prompt_evaluations").document(eval_id).set({
                "id": eval_id,
                "feedbackId": feedback_data["id"],
                "targetId": feedback_data["targetId"],
                "targetType": feedback_data["targetType"],
                "rating": feedback_data["rating"],
                "tags": feedback_data["tags"],
                "comment": feedback_data["comment"],
                "evaluatedAt": datetime.now(timezone.utc),
                "status": "PENDING_OPTIMIZATION"
            })
            logger.info(f"Prompt optimization evaluation record created: {eval_id}")
        except Exception as e:
            logger.error(f"Failed to log prompt optimization evaluation: {e}")

    @staticmethod
    def process_pending_optimizations() -> int:
        """
        Processes all evaluations with status 'PENDING_OPTIMIZATION'.
        Uses Gemini to rewrite/optimize the corresponding system prompt based on user comments and tags,
        saves the optimized prompt to Firestore, and updates the evaluation status to 'OPTIMIZED'.
        """
        try:
            docs = firebase_service.db.collection("prompt_evaluations").where("status", "==", "PENDING_OPTIMIZATION").stream()
            processed_count = 0
            
            from services.gemini_service import GeminiService
            from prompts.agent_prompts import EDUCATIONAL_SUMMARY_PROMPT
            
            default_image_prompt = """Anda adalah agen aksesibilitas. Analisislah gambar materi pelajaran ini. Gambar ini terletak di antara teks sebelum: "{context_before_str}" dan teks sesudah: "{context_after_str}". Gunakan konteks teks tersebut agar deskripsi gambar Anda akurat dan menyatu dengan materi pelajaran.
            
            Berikan dua jenis interpretasi teks:
            1. 'alt_text_totally_blind': Deskripsikan seluruh isi gambar secara linier, mendalam, dan mengalir untuk dibacakan oleh Screen Reader ke telinga tunanetra (tanpa simbol dekoratif atau kalimat pengantar visual). Gunakan pemahaman dari konteks sekitarnya untuk mendeskripsikan secara tepat.
            2. 'visual_explanation_deaf': Berikan penjelasan visual terstruktur menggunakan kalimat aktif yang pendek, sederhana, dan langsung ke inti materi untuk siswa tunarungu. Gunakan poin-poin jika menjelaskan bagian-bagian gambar.

            Format output wajib berupa JSON objek seperti ini:
            {{
                "alt_text_totally_blind": "...",
                "visual_explanation_deaf": "..."
            }}"""
            
            for doc in docs:
                eval_data = doc.to_dict() or {}
                eval_id = doc.id
                target_type = eval_data.get("targetType")
                comment = eval_data.get("comment")
                tags = eval_data.get("tags")
                
                # Determine which prompt to optimize
                if target_type == "DOCUMENT":
                    prompt_id = "educational_summary_prompt"
                    current_prompt = GeminiService.get_active_prompt(prompt_id, EDUCATIONAL_SUMMARY_PROMPT)
                elif target_type == "IMAGE":
                    prompt_id = "image_accessibility_prompt"
                    current_prompt = GeminiService.get_active_prompt(prompt_id, default_image_prompt)
                else:
                    logger.warning(f"Unknown targetType '{target_type}' in evaluation '{eval_id}', skipping.")
                    continue
                
                logger.info(f"Optimizing prompt '{prompt_id}' based on feedback evaluation '{eval_id}'")
                
                try:
                    from agents.feedback_agent import run_feedback_agent_sync
                    optimized_prompt = run_feedback_agent_sync(comment, tags, current_prompt)
                    if optimized_prompt and optimized_prompt.strip():
                        # Save optimized prompt to Firestore
                        firebase_service.db.collection("system_prompts").document(prompt_id).set({
                            "prompt": optimized_prompt.strip(),
                            "updatedAt": datetime.now(timezone.utc)
                        })
                        logger.info(f"Optimized prompt '{prompt_id}' saved successfully.")
                    
                    # Update status in Firestore
                    firebase_service.db.collection("prompt_evaluations").document(eval_id).update({
                        "status": "OPTIMIZED",
                        "updatedAt": datetime.now(timezone.utc)
                    })
                    processed_count += 1
                    logger.info(f"Feedback evaluation '{eval_id}' updated to OPTIMIZED.")
                    
                except Exception as opt_err:
                    logger.error(f"Failed to optimize prompt for evaluation '{eval_id}': {opt_err}")
            
            return processed_count
        except Exception as e:
            logger.error(f"Error processing pending optimizations: {e}")
            raise e
