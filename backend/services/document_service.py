import uuid
import os
from datetime import datetime, timezone
from io import BytesIO
from typing import Dict, List, Optional, Any
from services.firebase_service import FirebaseService
from services.pdf_service import PdfService
from agents.document_agent import DocumentAgent
from utils.logger import get_logger
from services.section_service import SectionService

logger = get_logger(__name__)

class DocumentService:
    def __init__(self, firebase_service: FirebaseService):
        """Initializes DocumentService with the injected FirebaseService."""
        self.firebase_service = firebase_service
    
    def process_and_store_document(self, file_stream: BytesIO, filename: str, owner_id: str) -> str:
        doc_id = str(uuid.uuid4())
        
        # 1. Create Initial Status
        logger.info(f"Creating initial document status in Firestore for: {doc_id}")
        self.firebase_service.save_document(doc_id, {
            "filename": filename,
            "status": "PROCESSING",
            "ownerId": owner_id,
            "createdAt": datetime.now(timezone.utc),
            "updatedAt": datetime.now(timezone.utc)
        })
        
        try:
            # 2. Extract Text & Assets lewat MinerU v4
            logger.info(f"Extracting text from PDF stream for document {doc_id} via MinerU...")
            text = PdfService.extract_text_from_stream(file_stream, filename, doc_id)
            
            # 3. Potong Markdown menjadi susunan Seksi (Sections)
            logger.info(f"Parsing markdown text into structured sections...")
            sections = SectionService.parse_markdown_to_sections(text, doc_id)
            
            # 4. Loop untuk memproses setiap Seksi (Gambar & Tabel) menggunakan Gemini
            from services.gemini_service import GeminiService # Pastikan ter-import
            
            for i in range(len(sections)):
                section = sections[i]
                if section["type"] == "image":
                    image_path = section["local_image_path"]
                    
                    # Cek apakah file fisik gambar memang ada
                    if os.path.exists(image_path):
                        # Ambil ukuran file dalam satuan Kilobytes (KB)
                        file_size_kb = os.path.getsize(image_path) / 1024
                        
                        # JIKA GAMBAR TERLALU KECIL (Kurang dari 15 KB), ANGGAP GAMBAR DEKORATIF
                        if file_size_kb < 15.0: 
                            logger.info(f"Mengabaikan gambar dekoratif/kecil: {image_path} ({file_size_kb:.2f} KB)")
                            section["type"] = "decorative_ignored"
                            continue
                        
                        # Ambil konteks sekitarnya jika ada
                        context_before = ""
                        if i > 0:
                            context_before = sections[i-1].get("content", "")
                        context_after = ""
                        if i < len(sections) - 1:
                            context_after = sections[i+1].get("content", "")
                            
                        # PROSES GAMBAR UTAMA: Panggil Gemini Multimodal Interpretation dengan konteks
                        logger.info(f"Mengirim gambar ({file_size_kb:.2f} KB) dengan konteks ke Gemini: {image_path}")
                        ai_interpret = GeminiService.interpret_image_accessibility(
                            image_path=image_path,
                            context_before=context_before,
                            context_after=context_after
                        )
                        
                        # Suntikkan hasil interpretasi AI ke dalam objek seksi gambar
                        section["alt_text_totally_blind"] = ai_interpret.get("alt_text_totally_blind", "")
                        section["visual_explanation_deaf"] = ai_interpret.get("visual_explanation_deaf", "")
                        
                        # Upload image to Firebase Storage
                        try:
                            image_filename = os.path.basename(image_path)
                            storage_destination = f"documents/{doc_id}/images/{image_filename}"
                            ext = image_filename.rsplit('.', 1)[-1].lower() if '.' in image_filename else 'png'
                            content_type = f"image/{ext}" if ext in ['png', 'jpg', 'jpeg', 'gif'] else 'image/png'
                            
                            with open(image_path, 'rb') as img_f:
                                image_url = self.firebase_service.upload_file(
                                    img_f,
                                    storage_destination,
                                    content_type=content_type
                                )
                            section["imageUrl"] = image_url
                            section["image_url"] = image_url
                            logger.info(f"Successfully uploaded section image to Storage: {image_url}")
                        except Exception as upload_err:
                            logger.error(f"Failed to upload section image {image_path}: {upload_err}")
                    else:
                        logger.warning(f"File gambar tidak ditemukan di lokal path: {image_path}")
                        section["type"] = "image_not_found"
                
                elif section["type"] == "table":
                    logger.info(f"Mengirim tabel HTML ke Gemini untuk dikonversi menjadi narasi penjelasan multi-versi...")
                    table_content = section.get("content", "")
                    table_prompt = f"""
                    Terjemahkan dan jelaskan data dalam tabel HTML berikut ini menjadi 3 versi penjelasan berbeda sesuai profil kebutuhan aksesibilitas siswa (tabel ini bisa berupa data tabel umum sehari-hari seperti jadwal, tabel harga, data organisasi, diagram, dsb):
                    
                    Tabel HTML:
                    {table_content}
                    
                    Tugas Anda adalah memproses tabel tersebut dan mengembalikan output strictly berupa JSON objek dengan key berikut:
                    1. 'table_interpretation_totally_blind': Pembacaan data tabel secara linier baris-per-baris (mengalir dari kiri ke kanan, atas ke bawah, misal: 'Pada baris pertama kolom satu nilainya A, kolom dua nilainya B. Pada baris kedua...') yang sangat ramah dibaca oleh Screen Reader tunanetra tanpa perlu membayangkan visual kotak tabel.
                    2. 'table_summary_low_vision': Ringkasan padat mengenai kesimpulan utama, tren data, atau poin paling penting dari tabel tersebut agar siswa Low Vision tidak lelah membaca detail kecil saat layar di-zoom besar.
                    3. 'table_explanation_deaf': Penjelasan isi tabel menggunakan struktur kalimat aktif yang pendek, lugas, sederhana, dan berbasis poin-poin informasi langsung agar ramah bagi siswa tunarungu.

                    Format JSON output wajib seperti ini:
                    {{
                        "table_interpretation_totally_blind": "...",
                        "table_summary_low_vision": "...",
                        "table_explanation_deaf": "..."
                    }}
                    """
                    import json
                    response_json = GeminiService.generate_content(
                        prompt=table_prompt,
                        response_mime_type="application/json"
                    )
                    ai_data = json.loads(response_json)
                    section["table_interpretation_totally_blind"] = ai_data.get("table_interpretation_totally_blind", "").strip()
                    section["table_summary_low_vision"] = ai_data.get("table_summary_low_vision", "").strip()
                    section["table_explanation_deaf"] = ai_data.get("table_explanation_deaf", "").strip()
                    
                    # Hapus field lama
                    section.pop("table_explanation_disabled", None)
                    logger.info("Tabel berhasil dijelaskan dalam 3 versi aksesibilitas oleh Gemini.")
                
                elif section["type"] == "text":
                    content = section.get("content", "")
                    math_keywords = ["\\le", "\\in", "\\left", "\\right", "\\leq", "\\geq", "\\frac", "\\sqrt", "^{", "_{"]
                    has_math = "$" in content or any(kw in content for kw in math_keywords)
                    has_url = "http://" in content or "https://" in content
                    has_markdown_link = "[" in content and "](" in content
                    
                    needs_optimization = has_math or has_url or has_markdown_link or "\\" in content
                    
                    if needs_optimization:
                        math_prompt = f"""
                        Teks berikut akan dibacakan oleh Screen Reader untuk siswa tunanetra total. Tolong ubah seluruh konten teks ini menjadi satu paragraf narasi kalimat ejaan bahasa Indonesia yang mengalir, utuh, bersih dari tag/simbol kaku, dan nyaman didengar.
                        
                        ATURAN UTAMA:
                        1. NO CHATTY / NO FILLER: Dilarang keras menyertakan kalimat basa-basi di awal atau di akhir respons (seperti 'Berikut adalah konversi...', 'Berikut adalah narasi...', dll). Output harus langsung dimulai pada kata pertama isi dokumen.
                        2. KEEP VARIABEL LETTERS: Jangan pernah mengubah huruf variabel matematika seperti 'x', 'y', 'z', atau 'f(x)' menjadi ejaan tulisan fonetik seperti 'iks', 'ye', 'zet', atau 'ef iks'. Biarkan tetap tertulis sebagai huruf 'x', 'y', 'z', atau 'f(x)' karena Screen Reader otomatis bisa melafalkannya dengan benar. Simbol operasinya saja (seperti \\leq, \\geq, \\in) yang diubah menjadi kata kalimat (misal: 'kurang dari atau sama dengan', 'anggota dari bilangan').
                        3. Jika ada URL, ubah menjadi kalimat penyebutan tautan yang rapi.
                        4. JANGAN kurangi informasi esensial dari teks asli.

                        Teks Asli:
                        {content}
                        """
                        spoken_text = GeminiService.generate_content(prompt=math_prompt)
                        section["spoken_text_totally_blind"] = spoken_text.strip() if spoken_text else content
                        logger.info("Spoken text untuk teks berhasil dibuat via Gemini.")
                    else:
                        # Teks sudah bersih sejak awal, samakan saja dengan content asli
                        section["spoken_text_totally_blind"] = content

            # 5. Menganalisis teks yang diekstrak menggunakan ADK SummaryAgent
            logger.info(f"Analyzing extracted text for document {doc_id} via ADK SummaryAgent...")
            from agents.summary_agent import run_summary_agent_sync
            analysis = run_summary_agent_sync(text, doc_id)
            
            # 6. Simpan struktur data baru yang SANGAT KAYA AKSESIBILITAS ke Firestore
            now = datetime.now(timezone.utc)
            self.firebase_service.save_document(doc_id, {
                "id": doc_id,
                "ownerId": owner_id,
                "filename": filename,
                "status": "READY",
                "summary": analysis.get("summary"),
                "topics": analysis.get("topics"),
                "suggested_questions": analysis.get("suggested_questions"),
                "sections": sections,  # Array of sections masuk ke sini!
                "extracted_text": text,
                "updatedAt": now
            })
            
            return doc_id
            
        except Exception as e:
            logger.error(f"Failed to process document {doc_id}: {e}")
            try:
                self.firebase_service.save_document(doc_id, {
                    "status": "FAILED",
                    "error": str(e),
                    "updatedAt": datetime.now(timezone.utc)
                })
            except Exception as save_err:
                logger.error(f"Failed to save failure status for document {doc_id}: {save_err}")
            raise e

    def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves document metadata from Firestore by document ID, falling back to uploaded_images."""
        # 1. Try fetching from documents collection
        doc = self.firebase_service.get_document(doc_id)
        if doc:
            return doc
            
        # 2. Try fetching from uploaded_images collection
        try:
            img_ref = self.firebase_service.db.collection("uploaded_images").document(doc_id).get()
            if img_ref.exists:
                img_dict = img_ref.to_dict() or {}
                img_dict['id'] = img_ref.id
                
                # Format datetimes
                for k in ['createdAt', 'updatedAt']:
                    if k in img_dict and img_dict[k]:
                        try:
                            if not isinstance(img_dict[k], str):
                                img_dict[k] = img_dict[k].isoformat()
                        except Exception:
                            pass
                
                # Map fields to match document schema
                filename = img_dict.get("filename", "image.jpg")
                ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'jpeg'
                content_type = f"image/{ext}" if ext != 'jpg' else 'image/jpeg'
                
                # Retrieve accessibility content
                acc_content = img_dict.get("accessibility_content") or {}
                alt_text = acc_content.get("alt_text_totally_blind") or img_dict.get("alt_text_totally_blind") or ""
                deaf_exp = acc_content.get("visual_explanation_deaf") or img_dict.get("visual_explanation_deaf") or ""
                
                # Construct sections
                sections = [
                    {
                        "section_id": 1,
                        "type": "image",
                        "imageUrl": img_dict.get("imageUrl"),
                        "image_url": img_dict.get("imageUrl"),
                        "alt_text_totally_blind": alt_text,
                        "visual_explanation_deaf": deaf_exp,
                        "local_image_path": ""
                    }
                ]
                
                mapped_doc = {
                    "id": img_dict.get("id"),
                    "filename": filename,
                    "contentType": content_type,
                    "status": img_dict.get("status", "READY"),
                    "summary": alt_text,
                    "topics": ["Image Analysis"],
                    "suggested_questions": [],
                    "ownerId": img_dict.get("ownerId", "anonymous"),
                    "sections": sections,
                    "createdAt": img_dict.get("createdAt"),
                    "updatedAt": img_dict.get("updatedAt")
                }
                
                if "errorMessage" in img_dict:
                    mapped_doc["errorMessage"] = img_dict["errorMessage"]
                    
                return mapped_doc
        except Exception as e:
            logger.error(f"Error checking uploaded_images fallback for {doc_id}: {e}")
            
        return None
        
    def list_documents(self, owner_id: str) -> List[Dict[str, Any]]:
        """Lists all documents in Firestore."""
        return self.firebase_service.list_documents(owner_id)

    def upload_document(self, file_stream: BytesIO, filename: str, content_type: str, owner_id: str) -> Dict[str, Any]:
        """
        Orchestrates the document upload flow:
        1. Generate UUID document_id
        2. Upload original PDF to Firebase Storage
        3. Create Firestore document
        """
        document_id = str(uuid.uuid4())
        logger.info(f"upload started. document_id: {document_id}")

        storage_path = f"documents/{document_id}.pdf"
        
        try:
            download_url = self.firebase_service.upload_file(
                file_stream,
                storage_path,
                content_type=content_type
            )
        except Exception as e:
            logger.error(f"upload failed. document_id: {document_id}")
            raise FirebaseUploadError(f"Failed to upload PDF: {str(e)}") from e

        try:
            now = datetime.now(timezone.utc)
            doc_data = {
                "id": document_id,
                "ownerId": owner_id,
                "filename": filename,
                "contentType": content_type,
                "storagePath": storage_path,
                "downloadUrl": download_url,
                "status": "UPLOADED",
                "createdAt": now,
                "updatedAt": now
            }
            self.firebase_service.save_document(document_id, doc_data)
        except Exception as e:
            logger.error(f"upload failed. document_id: {document_id}")
            raise FirestoreFailureError(f"Failed to create Firestore document: {str(e)}") from e

        logger.info(f"upload completed. document_id: {document_id}")
        return {
            "documentId": document_id,
            "status": "UPLOADED"
        }

    def list_documents_paginated(self, owner_id: str, page: int, page_size: int) -> Dict[str, Any]:
        """Lists documents with pagination, converting models/timestamps for response."""
        result = self.firebase_service.list_documents_paginated(owner_id, page, page_size)
        
        formatted_data = []
        for doc in result["data"]:
            formatted_data.append({
                "id": doc.get("id"),
                "filename": doc.get("filename"),
                "contentType": doc.get("contentType") or "application/pdf",
                "status": doc.get("status") or "UPLOADED",
                "summary": doc.get("summary") or None,
                "storagePath": doc.get("storagePath"),
                "downloadUrl": doc.get("downloadUrl") or doc.get("storage_url"),
                "createdAt": self._to_iso_utc(doc.get("createdAt")),
                "updatedAt": self._to_iso_utc(doc.get("updatedAt"))
            })
            
        total = result["total"]
        has_next = (page * page_size) < total
        
        return {
            "data": formatted_data,
            "pagination": {
                "page": page,
                "pageSize": page_size,
                "total": total,
                "hasNext": has_next
            }
        }

    def _to_iso_utc(self, val: Any) -> Optional[str]:
        if isinstance(val, datetime):
            utc_val = val.astimezone(timezone.utc)
            return utc_val.strftime("%Y-%m-%dT%H:%M:%SZ")
        if isinstance(val, str):
            return val
        return None



class FirebaseUploadError(Exception):
    """Exception raised when file upload to Firebase Storage fails."""
    pass


class FirestoreFailureError(Exception):
    """Exception raised when document record creation in Firestore fails."""
    pass
