import os
import time
import zipfile
import io
import requests
from utils.logger import get_logger

logger = get_logger(__name__)

class PdfService:
    @staticmethod
    def extract_text_from_stream(file_stream: io.BytesIO, filename: str = "document.pdf", doc_id: str = None) -> str:
        """
        Mengirim file stream PDF ke MinerU Precision Extract API v4,
        Mengekstrak file ZIP, dan mengembalikan teks Markdown utama.
        """
        token = os.getenv("MINERU_API_KEY")
        if not token:
            logger.error("MINERU_API_KEY is not set in environment variables.")
            raise ValueError("MINERU_API_KEY is missing from environment variables.")
        
        url_init_batch = "https://mineru.net/api/v4/file-urls/batch"
        url_status_batch = "https://mineru.net/api/v4/extract-results/batch"
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }

        try:
            # Pastikan posisi pointer stream berada di awal berkas
            file_stream.seek(0)
            file_bytes = file_stream.read()

            # STEP 1: Meminta Signed Upload URL ke MinerU
            logger.info("Meminta signed upload URL dari MinerU v4...")
            data_init = {
                "files": [
                    {"name": filename, "data_id": f"upload_{int(time.time())}"}
                ],
                "model_version": "vlm"
            }
            
            response = requests.post(url_init_batch, headers=headers, json=data_init)
            res_json = response.json()
            
            if response.status_code != 200 or res_json.get("code") != 0:
                raise Exception(f"Gagal inisiasi batch MinerU: {res_json.get('msg')}")
                
            batch_id = res_json["data"]["batch_id"]
            upload_url = res_json["data"]["file_urls"][0]

            # STEP 2: Upload File PDF via PUT dari memori
            logger.info("Mengunggah data bytes PDF ke Storage MinerU...")
            put_response = requests.put(upload_url, data=file_bytes)
            if put_response.status_code not in (200, 201):
                raise Exception(f"PUT upload ke MinerU gagal, HTTP: {put_response.status_code}")

            # STEP 3: Polling Status Pekerjaan AI
            logger.info("Menunggu proses AI MinerU selesai (Polling)...")
            url_check = f"{URL_STATUS_BATCH}/{batch_id}" if 'URL_STATUS_BATCH' in locals() else f"https://mineru.net/api/v4/extract-results/batch/{batch_id}"
            
            full_zip_url = None
            for i in range(30):
                time.sleep(5)
                status_res = requests.get(url_check, headers=headers).json()
                
                if status_res.get("code") == 0 and "extract_result" in status_res["data"]:
                    file_result = status_res["data"]["extract_result"][0]
                    state = file_result.get("state")
                    logger.info(f"Pengecekan MinerU ke-{i+1}: Status -> {state}")
                    
                    if state == "done":
                        full_zip_url = file_result["full_zip_url"]
                        break
                    elif state == "failed":
                        raise Exception(f"Ekstraksi AI MinerU gagal: {file_result.get('err_msg')}")
            
            if not full_zip_url:
                raise Exception("Timeout: MinerU memproses dokumen terlalu lama.")

            # STEP 4: Unduh ZIP dan Ekstrak Berkas ke Folder Proyek
            logger.info("Mengunduh paket ZIP hasil ekstraksi...")
            zip_response = requests.get(full_zip_url)
            
            if zip_response.status_code == 200:
                # Siapkan folder khusus untuk menyimpan asset gambar dokumen ini agar bisa diakses Frontend
                # Kamu bisa mengarahkannya ke folder 'static/extracted_assets/...' milik Flask
                folder_suffix = f"doc_{doc_id}" if doc_id else f"doc_{batch_id[:8]}"
                output_folder = os.path.join("static", "extracted_assets", folder_suffix)
                os.makedirs(output_folder, exist_ok=True)
                
                with zipfile.ZipFile(io.BytesIO(zip_response.content)) as zip_ref:
                    zip_ref.extractall(output_folder)
                
                logger.info(f"Seluruh aset sukses diekstrak ke: {output_folder}")
                
                # Membaca file tulisan utamanya 'full.md' untuk dikembalikan ke pipeline sistem
                path_markdown = os.path.join(output_folder, "full.md")
                if os.path.exists(path_markdown):
                    with open(path_markdown, "r", encoding="utf-8") as md_file:
                        return md_file.read()
                
                return "Ekstraksi selesai, namun berkas full.md tidak ditemukan."
            else:
                raise Exception(f"Gagal mengunduh ZIP dari CDN. HTTP: {zip_response.status_code}")

        except Exception as e:
            logger.error(f"Error pada PdfService MinerU Integration: {str(e)}")
            raise e