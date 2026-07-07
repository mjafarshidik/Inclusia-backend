import os
import asyncio
from typing import AsyncGenerator
from pydantic import BaseModel, Field
from google.adk.agents import BaseAgent, LlmAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.adk.apps import App
from google.adk.runners import InMemoryRunner
from google.genai import types

# ==========================================
# 1. Output Schemas
# ==========================================

class TextAccessibilityOutput(BaseModel):
    spoken_text_totally_blind: str = Field(description="Narasi kalimat ejaan bahasa Indonesia yang mengalir, utuh, bersih dari tag/simbol kaku.")

class ImageAccessibilityOutput(BaseModel):
    alt_text_totally_blind: str = Field(description="Deskripsi gambar linier mendalam untuk tunanetra.")
    visual_explanation_deaf: str = Field(description="Penjelasan visual terstruktur dengan kalimat pendek untuk tunarungu.")

class TableAccessibilityOutput(BaseModel):
    table_interpretation_totally_blind: str = Field(description="Pembacaan tabel linier baris-per-baris untuk screen reader.")
    table_summary_low_vision: str = Field(description="Ringkasan padat kesimpulan utama untuk low vision.")
    table_explanation_deaf: str = Field(description="Penjelasan isi tabel dengan kalimat aktif pendek untuk tunarungu.")

# ==========================================
# 2. Prompts
# ==========================================

TEXT_ACCESSIBILITY_PROMPT = """
Teks berikut akan dibacakan oleh Screen Reader untuk siswa tunanetra total. Tolong ubah seluruh konten teks ini menjadi satu paragraf narasi kalimat ejaan bahasa Indonesia yang mengalir, utuh, bersih dari tag/simbol kaku, dan nyaman didengar.

ATURAN UTAMA:
1. NO CHATTY / NO FILLER: Dilarang keras menyertakan kalimat basa-basi di awal atau di akhir respons. Output harus langsung dimulai pada kata pertama isi dokumen.
2. KEEP VARIABEL LETTERS: Jangan pernah mengubah huruf variabel matematika seperti 'x', 'y', 'z', atau 'f(x)'. Biarkan tetap tertulis sebagai huruf 'x', 'y', 'z', atau 'f(x)'. Simbol operasinya saja (seperti \\leq, \\geq, \\in) yang diubah menjadi kata kalimat (misal: 'kurang dari atau sama dengan', 'anggota dari bilangan').
3. Jika ada URL, ubah menjadi kalimat penyebutan tautan yang rapi.
4. JANGAN kurangi informasi esensial dari teks asli.

Teks Asli:
{content}
"""

IMAGE_ACCESSIBILITY_PROMPT = """
Anda adalah agen aksesibilitas. Analisislah gambar materi pelajaran ini. Gambar ini terletak di antara teks sebelum: "{context_before}" dan teks sesudah: "{context_after}". Gunakan konteks teks tersebut agar deskripsi gambar Anda akurat dan menyatu dengan materi pelajaran.

Berikan dua jenis interpretasi teks:
1. 'alt_text_totally_blind': Deskripsikan seluruh isi gambar secara linier, mendalam, dan mengalir untuk dibacakan oleh Screen Reader ke telinga tunanetra (tanpa simbol dekoratif atau kalimat pengantar visual). Gunakan pemahaman dari konteks sekitarnya untuk mendeskripsikan secara tepat.
2. 'visual_explanation_deaf': Berikan penjelasan visual terstruktur menggunakan kalimat aktif yang pendek, sederhana, dan langsung ke inti materi untuk siswa tunarungu. Gunakan poin-poin jika menjelaskan bagian-bagian gambar.
"""

TABLE_ACCESSIBILITY_PROMPT = """
Terjemahkan dan jelaskan data dalam tabel HTML berikut ini menjadi 3 versi penjelasan berbeda sesuai profil kebutuhan aksesibilitas siswa:

Tabel HTML:
{table_content}

Tugas Anda adalah memproses tabel tersebut dan mengembalikan output sesuai dengan schema yang didefinisikan:
1. 'table_interpretation_totally_blind': Pembacaan data tabel secara linier baris-per-baris.
2. 'table_summary_low_vision': Ringkasan padat mengenai kesimpulan utama, tren data, atau poin paling penting.
3. 'table_explanation_deaf': Penjelasan isi tabel menggunakan kalimat aktif pendek, lugas, sederhana, dan berbasis poin-poin.
"""

# ==========================================
# 3. Agent Definitions
# ==========================================

text_section_agent = LlmAgent(
    name="text_section_agent",
    model="gemini-3.5-flash",
    instruction="Generate spoken text description for math/link contents.",
    output_schema=TextAccessibilityOutput,
    output_key="result"
)

image_section_agent = LlmAgent(
    name="image_section_agent",
    model="gemini-3.5-flash",
    instruction="Interpret the image for accessibility contexts.",
    output_schema=ImageAccessibilityOutput,
    output_key="result"
)

table_section_agent = LlmAgent(
    name="table_section_agent",
    model="gemini-3.5-flash",
    instruction="Translate HTML table to multiple accessible descriptions.",
    output_schema=TableAccessibilityOutput,
    output_key="result"
)

# ==========================================
# 4. Helper runner
# ==========================================

async def run_sub_agent(agent: LlmAgent, message_content: types.Content, session_id: str) -> dict:
    """Helper function to run an LlmAgent session asynchronously and return the structured result."""
    app = App(name="agents", root_agent=agent)
    runner = InMemoryRunner(app=app)
    await runner.session_service.create_session(
        app_name="agents",
        user_id="system",
        session_id=session_id
    )
    async for event in runner.run_async(
        user_id="system",
        session_id=session_id,
        new_message=message_content
    ):
        pass
    session = await runner.session_service.get_session(app_name="agents", session_id=session_id)
    return session.state.get("result") or {}

# ==========================================
# 5. Section Analysis Orchestrator Agent
# ==========================================

class SectionAnalysisOrchestrator(BaseAgent):
    """BaseAgent subclass that orchestrates section analysis for text, image, and table types with bounded concurrency."""
    
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        document_id = ctx.session.state.get("document_id")
        extracted_text = ctx.session.state.get("extracted_text")

        from services import firebase_service
        from datetime import datetime, timezone
        firebase_service.save_document(document_id, {
            "status": "PROCESSING_SECTIONS",
            "updatedAt": datetime.now(timezone.utc)
        })

        from services.section_service import SectionService
        sections = SectionService.parse_markdown_to_sections(extracted_text, document_id)

        # Set rate-limit resilience via bounded concurrency (max 3 concurrent Gemini requests)
        sem = asyncio.Semaphore(3)

        async def process_section(idx, sec):
            session_prefix = f"{document_id}_sec_{idx}"
            
            if sec["type"] == "text":
                content = sec.get("content", "")
                math_keywords = ["\\le", "\\in", "\\left", "\\right", "\\leq", "\\geq", "\\frac", "\\sqrt", "^{", "_{"]
                has_math = "$" in content or any(kw in content for kw in math_keywords)
                has_url = "http://" in content or "https://" in content
                has_markdown_link = "[" in content and "](" in content
                needs_optimization = has_math or has_url or has_markdown_link or "\\" in content

                if needs_optimization:
                    async with sem:
                        prompt = TEXT_ACCESSIBILITY_PROMPT.format(content=content)
                        message_content = types.Content(parts=[types.Part.from_text(text=prompt)])
                        res = await run_sub_agent(text_section_agent, message_content, session_prefix)
                        sec["spoken_text_totally_blind"] = res.get("spoken_text_totally_blind", content)
                else:
                    sec["spoken_text_totally_blind"] = content

            elif sec["type"] == "image":
                image_path = sec.get("local_image_path", "")
                if os.path.exists(image_path):
                    file_size_kb = os.path.getsize(image_path) / 1024
                    if file_size_kb < 15.0:
                        sec["type"] = "decorative_ignored"
                    else:
                        context_before = ""
                        if idx > 0:
                            context_before = sections[idx-1].get("content", "")
                        context_after = ""
                        if idx < len(sections) - 1:
                            context_after = sections[idx+1].get("content", "")

                        async with sem:
                            from PIL import Image
                            img = Image.open(image_path)
                            prompt = IMAGE_ACCESSIBILITY_PROMPT.format(
                                context_before=context_before,
                                context_after=context_after
                            )
                            message_content = types.Content(parts=[
                                img,
                                types.Part.from_text(text=prompt)
                            ])
                            res = await run_sub_agent(image_section_agent, message_content, session_prefix)
                            sec["alt_text_totally_blind"] = res.get("alt_text_totally_blind", "")
                            sec["visual_explanation_deaf"] = res.get("visual_explanation_deaf", "")

                        # Upload to Firebase Storage
                        try:
                            from services import firebase_service
                            image_filename = os.path.basename(image_path)
                            storage_destination = f"documents/{document_id}/images/{image_filename}"
                            ext = image_filename.rsplit('.', 1)[-1].lower() if '.' in image_filename else 'png'
                            content_type = f"image/{ext}" if ext in ['png', 'jpg', 'jpeg', 'gif'] else 'image/png'

                            with open(image_path, 'rb') as img_f:
                                image_url = firebase_service.upload_file(
                                    img_f,
                                    storage_destination,
                                    content_type=content_type
                                )
                            sec["imageUrl"] = image_url
                            sec["image_url"] = image_url
                        except Exception as upload_err:
                            from services.storage_service import get_base_url
                            local_url = f"{get_base_url().rstrip('/')}/{image_path.lstrip('/')}"
                            sec["imageUrl"] = local_url
                            sec["image_url"] = local_url
                else:
                    sec["type"] = "image_not_found"

            elif sec["type"] == "table":
                table_content = sec.get("content", "")
                async with sem:
                    prompt = TABLE_ACCESSIBILITY_PROMPT.format(table_content=table_content)
                    message_content = types.Content(parts=[types.Part.from_text(text=prompt)])
                    res = await run_sub_agent(table_section_agent, message_content, session_prefix)
                    sec["table_interpretation_totally_blind"] = res.get("table_interpretation_totally_blind", "")
                    sec["table_summary_low_vision"] = res.get("table_summary_low_vision", "")
                    sec["table_explanation_deaf"] = res.get("table_explanation_deaf", "")

            return sec

        tasks = [process_section(idx, sec) for idx, sec in enumerate(sections)]
        processed_sections = await asyncio.gather(*tasks)
        ctx.session.state["sections"] = processed_sections
        yield Event(author=self.name)
