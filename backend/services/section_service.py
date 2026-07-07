import re
import os
from typing import List, Dict, Any

class SectionService:
    @staticmethod
    def parse_markdown_to_sections(markdown_text: str, doc_id: str) -> List[Dict[str, Any]]:
        """
        Memotong teks Markdown menjadi kumpulan seksi (Sections) terstruktur
        berdasarkan Heading (##, ###), tag Gambar ![](images/...), dan Tabel HTML <table>
        """
        if not markdown_text:
            return []

        # Pisahkan teks berdasarkan baris
        lines = markdown_text.split("\n")
        sections = []
        current_text_block = []
        section_index = 1
        
        in_table = False
        current_table_block = []

        def save_current_text_block():
            nonlocal section_index
            if current_text_block:
                full_text = "\n".join(current_text_block).strip()
                if full_text:
                    sections.append({
                        "section_id": section_index,
                        "type": "text",
                        "content": full_text
                    })
                    section_index += 1
                current_text_block.clear()

        for line in lines:
            # Jika sedang berada di dalam tabel
            if in_table:
                current_table_block.append(line)
                if "</table>" in line:
                    full_table_text = "\n".join(current_table_block).strip()
                    if full_table_text:
                        sections.append({
                            "section_id": section_index,
                            "type": "table",
                            "content": full_table_text,
                            "table_explanation_disabled": ""
                        })
                        section_index += 1
                    current_table_block.clear()
                    in_table = False
                continue

            # Jika mendeteksi baris baru pembuka tabel
            if "<table" in line:
                save_current_text_block()  # Simpan teks sebelumnya
                in_table = True
                current_table_block.append(line)
                
                # Cek jika baris yang sama langsung memuat penutup tabel
                if "</table>" in line:
                    full_table_text = "\n".join(current_table_block).strip()
                    if full_table_text:
                        sections.append({
                            "section_id": section_index,
                            "type": "table",
                            "content": full_table_text,
                            "table_explanation_disabled": ""
                        })
                        section_index += 1
                    current_table_block.clear()
                    in_table = False
                continue

            # 1. Deteksi apakah baris ini adalah judul seksi (Heading)
            if line.startswith("#"):
                save_current_text_block() # Simpan teks sebelumnya jika ada
                sections.append({
                    "section_id": section_index,
                    "type": "text",
                    "content": line.strip()
                })
                section_index += 1

            # 2. Deteksi apakah baris ini memuat gambar dari MinerU, misal: ![](images/img1.png)
            elif "![" in line and "images/" in line:
                save_current_text_block() # Simpan teks sebelum gambar
                
                # Ekstrak nama file gambar lokal menggunakan Regex
                match = re.search(r'images/([\w\.-]+)', line)
                image_filename = match.group(1) if match else "unknown.png"
                
                # Lokasi penyimpanan gambar lokal di MacBook kamu (cek subfolder images atau direct parent)
                path_with_images_dir = f"static/extracted_assets/doc_{doc_id}/images/{image_filename}"
                path_without_images_dir = f"static/extracted_assets/doc_{doc_id}/{image_filename}"
                
                if os.path.exists(path_with_images_dir):
                    local_path = path_with_images_dir
                elif os.path.exists(path_without_images_dir):
                    local_path = path_without_images_dir
                else:
                    # Fallback default
                    local_path = path_with_images_dir
                
                sections.append({
                    "section_id": section_index,
                    "type": "image",
                    "local_image_path": local_path,
                    "alt_text_totally_blind": "Memproses deskripsi gambar...", # Nanti diisi AI
                    "visual_explanation_deaf": "Memproses penjelasan visual..." # Nanti diisi AI
                })
                section_index += 1
            
            else:
                current_text_block.append(line)

        # Simpan sisa tabel jika tag penutup tidak ditemukan
        if in_table and current_table_block:
            full_table_text = "\n".join(current_table_block).strip()
            sections.append({
                "section_id": section_index,
                "type": "table",
                "content": full_table_text,
                "table_explanation_disabled": ""
            })
            section_index += 1

        # Simpan sisa blok teks terakhir
        save_current_text_block()
        return sections