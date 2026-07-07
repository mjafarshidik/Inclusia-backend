# API Documentation - Inclusia Backend

Dokumentasi ini menjelaskan seluruh endpoint REST API yang telah diselaraskan dengan kontrak API dan diimplementasikan pada backend Inclusia.

---

## Alur Autentikasi & Autentikasi Global

Seluruh endpoint (kecuali ditentukan lain seperti `/health`) dilindungi oleh Firebase Authentication. Setiap request harus menyertakan token Firebase ID Token (baik dari Google Account maupun Firebase Anonymous/Guest Login) dalam header:

```http
Authorization: Bearer <Firebase_ID_Token>
```

### Kebijakan & Isolasi Data
* **Autentikasi Permisif**: Jika header `Authorization` tidak disertakan, request tetap diproses menggunakan identitas tamu default (`uid: "anonymous"`). Namun, seluruh client **sangat disarankan untuk selalu mengirimkan Firebase ID Token** agar dokumen, gambar, chat, dan profil terisolasi secara pribadi per-`uid` masing-masing dan tidak bercampur dengan tamu global lainnya.
* **Validasi Token**: Jika token disertakan tetapi tidak valid/kedaluwarsa/dicabut, API akan mengembalikan status **401 Unauthorized**.
* **Isolasi Kepemilikan (Strict Ownership)**: Dokumen dan gambar yang diunggah dikaitkan langsung dengan `uid` pengguna. Endpoint pengambilan detail (`GET`), pemrosesan (`POST`), dan chat (`POST`) memvalidasi kepemilikan (`ownerId == user_uid`). Jika pengguna mencoba mengakses aset milik `uid` lain, API akan mengembalikan status **403 Forbidden**.

---

## Format Respons Error (Global)

Backend Inclusia menggunakan **Format Respons Error Kanonikal** yang seragam di seluruh endpoint. Format ini menyertakan *nested error object* untuk integrasi modern, sekaligus menyertakan *shim/alias kompatibilitas mundur* agar parser klien lama tidak pecah.

Format respons di atas berlaku untuk semua status error (**400 Bad Request**, **401 Unauthorized**, **403 Forbidden**, **404 Not Found**, **413 Payload Too Large**, dan **500 Internal Server Error**).

---

## 1. Endpoint Profil Pengguna

### Dapatkan Profil Pengguna
Mengembalikan data profil pengguna yang terautentikasi beserta preferensi Accessibility Profile miliknya yang tersimpan di Firestore.

*   **URL**: `/api/v1/profile`
*   **Method**: `GET`
*   **Auth Required**: Ya (Permissive)
*   **Response (200 OK)**:
    ```json
    {
      "success": true,
      "data": {
        "uid": "wJ27Xm...",
        "email": "user@example.com",
        "name": "User Full Name",
        "displayName": "User Full Name",
        "picture": "https://lh3.googleusercontent.com/...",
        "photoUrl": "https://lh3.googleusercontent.com/...",
        "accessibilityMode": "LOW_VISION"
      }
    }
    ```
    *Catatan: Jika pengguna belum pernah memilih profil aksesibilitas, `accessibilityMode` bernilai `null`.*

### Atur Profil Aksesibilitas Pengguna
Mengatur preferensi profil aksesibilitas pengguna terautentikasi dan menyimpannya ke dalam koleksi Firestore `users`. Endpoint ini bersifat fleksibel dan menerima berbagai format nama field dan pembersihan string.

*   **URL**: `/api/v1/profile/accessibility`
*   **Method**: `POST`
*   **Auth Required**: Ya (Permissive)
*   **Format Request**: `application/json`
*   **Body**:
    ```json
    {
      "mode": "deaf"
    }
    ```
    *   *Kunci yang diterima*: `mode`, `accessibilityMode`, atau `accessibility_mode`.
    *   *Nilai yang diterima*: String dengan spasi, lowercase, atau alias disabilitas (contoh: `"deaf"`, `"TOTALLY BLIND"`).
    *   *Nilai canonical pasca normalisasi*: `TOTALLY_BLIND`, `LOW_VISION`, `DEAF_HEARING` (input `"DEAF"` otomatis dikonversi menjadi `"DEAF_HEARING"`).
*   **Response (200 OK)**:
    ```json
    {
      "success": true,
      "message": "Profile created successfully" // atau "Profile updated successfully"
    }
    ```

### Perbarui Profil Pengguna (Metode PUT Alternatif)
Endpoint alternatif untuk memperbarui konfigurasi mode aksesibilitas pengguna dengan validasi fleksibel yang sama.

*   **URL**: `/api/v1/user/profile`
*   **Method**: `PUT`
*   **Auth Required**: Ya (Permissive)
*   **Format Request**: `application/json`
*   **Body**:
    ```json
    {
      "accessibilityMode": "DEAF"
    }
    ```
*   **Response (200 OK)**:
    ```json
    {
      "success": true,
      "message": "Profile updated successfully",
      "data": {
        "uid": "wJ27Xm...",
        "accessibilityMode": "DEAF_HEARING"
      }
    }
    ```

---

## 2. Endpoint Dokumen (v1 - Asynchronous)

### Upload Dokumen (Asinkron)
Mengunggah file PDF ke Cloud Storage dan mendaftarkan metadata awal ke Firestore dengan status `UPLOADED`. Proses ekstraksi AI berjalan secara terpisah.

*   **URL**: `/api/v1/documents/upload`
*   **Method**: `POST`
*   **Auth Required**: Ya (Permissive)
*   **Format Request**: `multipart/form-data`
*   **Body**:
    *   `file`: File PDF (Maksimal 20MB)
*   **Response (201 Created)**:
    ```json
    {
      "success": true,
      "message": "Document uploaded successfully",
      "data": {
        "id": "1a2b3c..."
      }
    }
    ```

### Proses Dokumen via AI (Asinkron)
Memulai proses ekstraksi teks, pembagian seksi, pembuatan ringkasan, dan analisis aksesibilitas gambar/tabel secara asinkron menggunakan Gemini AI di thread latar belakang.

*   **URL**: `/api/v1/documents/<doc_id>/process`
*   **Method**: `POST`
*   **Auth Required**: Ya (Permissive)
*   **Response (200 OK)**:
    ```json
    {
      "success": true,
      "message": "Processing started",
      "data": {
        "documentId": "1a2b3c...",
        "status": "PROCESSING_AI"
      }
    }
    ```

> [!NOTE]
> **Siklus Hidup Status Pemrosesan Asinkron:**
> Klien disarankan melakukan polling status dokumen pada `/api/v1/documents/<doc_id>`. Status dokumen akan bertransisi secara berurutan sebagai berikut:
> 1. `UPLOADED` : Dokumen baru diunggah.
> 2. `QUEUED` : Dokumen masuk dalam antrean pemrosesan di background thread.
> 3. `EXTRACTING` : Teks dan aset gambar sedang diekstraksi menggunakan MinerU v4.
> 4. `EXTRACTED` : Teks telah diekstraksi dan disimpan di database.
> 5. `PROCESSING_AI` : Model AI sedang menganalisis dokumen untuk ringkasan global, topik, dan pertanyaan terarah.
> 6. `PROCESSING_SECTIONS` : AI sedang mengevaluasi aksesibilitas tiap potongan seksi, gambar, dan tabel.
> 7. `READY` : Pemrosesan selesai. Seluruh data aksesibilitas siap dikonsumsi.
> 8. `FAILED` : Terjadi kesalahan pemrosesan (detail kesalahan dicatat pada properti `errorMessage`).

### Detail Dokumen Lengkap v1
Mengambil data dokumen lengkap milik user yang masuk, termasuk isi teks penuh (`extractedText`/`extracted_text`) dan susunan seksi aksesibilitas terstruktur (`sections`) yang dihasilkan secara asinkron.

*   **URL**: `/api/v1/documents/<doc_id>`
*   **Method**: `GET`
*   **Auth Required**: Ya (Permissive)
*   **Response (200 OK - Hasil Pemrosesan Selesai / READY)**:
    ```json
    {
      "success": true,
      "message": "Document retrieved successfully",
      "data": {
        "id": "1a2b3c...",
        "filename": "materi_biologi.pdf",
        "contentType": "application/pdf",
        "status": "READY",
        "summary": "Ini adalah rangkuman dari isi dokumen...",
        "topics": ["Biologi Sel", "Mitosis"],
        "suggested_questions": ["Apa itu mitosis?", "Sebutkan fase-fase pembelahan sel!"],
        "extracted_text": "# Bab 1: Sel...\n\n...",
        "extractedText": "# Bab 1: Sel...\n\n...",
        "sections": [
          {
            "section_id": 1,
            "type": "text",
            "content": "# Bab 1: Sel",
            "spoken_text_totally_blind": "# Bab 1: Sel"
          },
          {
            "section_id": 2,
            "type": "image",
            "local_image_path": "static/extracted_assets/doc_1a2b3c.../images/cell.png",
            "alt_text_totally_blind": "Diagram sel hewan yang menunjukkan membran sel, nukleus di tengah, dan mitokondria.",
            "visual_explanation_deaf": "Bagian-bagian sel hewan:\n- Nukleus: Pusat kendali sel.\n- Mitokondria: Penghasil energi sel."
          },
          {
            "section_id": 3,
            "type": "table",
            "content": "<table><tr><td>Fase</td><td>Deskripsi</td></tr><tr><td>Profase</td><td>Kromosom memadat</td></tr></table>",
            "table_interpretation_totally_blind": "Pada baris pertama kolom Fase nilainya Fase, kolom Deskripsi nilainya Deskripsi...",
            "table_summary_low_vision": "Tabel ini meringkas fase-fase pembelahan sel.",
            "table_explanation_deaf": "- Profase: Kromosom memadat\n- Metafase: Kromosom berjejer di ekuator"
          }
        ],
        "createdAt": "2026-06-30T10:00:00Z",
        "updatedAt": "2026-06-30T10:05:00Z",
        "ownerId": "user-uid"
      }
    }
    ```

---

## 3. Endpoint Dokumen (Legacy / Synchronous / MVP)

### Upload & Proses Dokumen Langsung (Sinkron)
Mengunggah file dan langsung melakukan pemrosesan ekstraksi teks, pembagian potongan seksi, analisis visual, dan ringkasan global secara sinkron (blocking). Dokumen langsung disimpan ke database dengan status `READY`.

*   **URL**: `/api/v1/documents` atau `/documents`
*   **Method**: `POST`
*   **Auth Required**: Ya (Permissive)
*   **Format Request**: `multipart/form-data`
*   **Body**:
    *   `file`: File PDF (Maksimal 16MB)
*   **Response (201 Created)**:
    ```json
    {
      "success": true,
      "message": "Document uploaded and processed successfully",
      "data": {
        "id": "1a2b3c..."
      }
    }
    ```

---

### Struktur Objek pada Field `sections`

Setiap objek dalam array `sections` mewakili satu potongan materi dengan format bervariasi bergantung pada properti `type`:

1. **Tipe Teks (`type: "text"`)**:
   * `section_id` (Integer): Indeks urutan seksi.
   * `content` (String): Teks Markdown asli.
   * `spoken_text_totally_blind` (String): Hasil optimasi kalimat oleh Gemini agar nyaman didengar oleh pembaca layar tunanetra (mengubah ekspresi rumus matematika, LaTeX, dan URL menjadi deskripsi verbal bahasa Indonesia).

2. **Tipe Gambar (`type: "image"`)**:
   * `section_id` (Integer): Indeks urutan seksi.
   * `local_image_path` (String): Path berkas gambar lokal pada server (ephemeral).
   * `imageUrl` / `image_url` (String): URL publik berkas gambar yang diunggah ke Firebase Storage (permanen).
   * `alt_text_totally_blind` (String): Deskripsi gambar mendalam dan linier dari Gemini untuk Screen Reader.
   * `visual_explanation_deaf` (String): Penjelasan gambar pendek berbasis poin untuk siswa tunarungu.

3. **Tipe Tabel (`type: "table"`)**:
   * `section_id` (Integer): Indeks urutan seksi.
   * `content` (String): Kode markup tabel HTML mentah (`<table>...</table>`).
   * `table_interpretation_totally_blind` (String): Pembacaan data tabel linier baris-per-baris untuk tunanetra.
   * `table_summary_low_vision` (String): Ringkasan tren utama data tabel untuk siswa Low Vision.
   * `table_explanation_deaf` (String): Penjelasan informasi tabel berbasis poin ringkas untuk siswa tunarungu.

4. **Tipe Pengecualian / Filter (`type: "decorative_ignored"` / `"image_not_found"`)**:
   * `"decorative_ignored"`: Penanda gambar dekoratif/kecil (< 15KB) agar dilewati oleh pembaca bantuan visual.
   * `"image_not_found"`: Penanda jika berkas fisik gambar tidak ditemukan di sistem lokal server.

---

### Multimodal Accessibility Filter & Logic

Untuk memastikan keselarasan konsumsi data di sisi Frontend (Web/Mobile Apps), perhatikan panduan logika berikut:

> [!NOTE]
> **Penyaringan Gambar Dekoratif (< 15KB)**
> Gambar dengan ukuran file sangat kecil (di bawah 15KB) otomatis dikategorikan sebagai elemen dekoratif (seperti garis pembatas, logo kecil, ornamen) dan diubah tipenya menjadi `"decorative_ignored"` tanpa memanggil proses interpretasi AI Gemini demi menghemat kuota token dan meningkatkan relevansi konten.

> [!TIP]
> **Konsumsi Data berdasarkan Profil Aksesibilitas Pengguna:**
> - **TOTALLY_BLIND (Tunanetra Total):** Frontend disarankan menggunakan Screen Reader untuk membacakan seksi teks biasa dengan memprioritaskan field `spoken_text_totally_blind` (bukan `content` agar rumus dan URL terdengar jelas), narasi tabel dari `table_interpretation_totally_blind`, serta detail gambar pada `alt_text_totally_blind`.
> - **LOW_VISION (Kurang Awas):** Tampilkan gambar dengan opsi zoom/kontras tinggi dan sertakan `alt_text_totally_blind` atau `table_summary_low_vision` sebagai teks bantuan visual.
> - **DEAF_HEARING (Tunarungu):** Tampilkan gambar fisik secara visual dan sertakan penjelasan sederhana berbentuk poin pada `visual_explanation_deaf`. Untuk tabel, tampilkan visual tabel HTML bersama penjelasannya dari `table_explanation_deaf` di bawahnya.

---

### List Dokumen User (Paginated)
Mengembalikan daftar dokumen milik user terautentikasi, diurutkan berdasarkan tanggal buat terbaru (`createdAt DESC`). Endpoint ini efisien karena tidak memuat `extracted_text`/`extractedText` dan `sections`.

*   **URL**: `/api/v1/documents` atau `/documents`
*   **Method**: `GET`
*   **Auth Required**: Ya (Permissive)
*   **Query Parameters**:
    *   `page` (Optional): Halaman data (Default: `1`)
    *   `pageSize` (Optional): Jumlah dokumen per halaman (Default: `20`, Maksimal: `100`)
*   **Response (200 OK)**:
    ```json
    {
      "data": [
        {
          "id": "1a2b3c...",
          "filename": "laporan_keuangan.pdf",
          "contentType": "application/pdf",
          "status": "READY",
          "summary": "Ringkasan dokumen...",
          "storagePath": "documents/1a2b3c...pdf",
          "downloadUrl": "https://storage.googleapis...",
          "createdAt": "2026-06-30T10:00:00Z",
          "updatedAt": "2026-06-30T10:05:00Z"
        }
      ],
      "pagination": {
        "page": 1,
        "pageSize": 20,
        "total": 1,
        "hasNext": false
      }
    }
    ```

### Dapatkan Metadata Dokumen Legacy
Mendapatkan informasi dasar dokumen tanpa mengembalikan field teks yang besar dan array seksi (`sections`).

*   **URL**: `/documents/<doc_id>`
*   **Method**: `GET`
*   **Auth Required**: Ya (Permissive)
*   **Response (200 OK)**:
    ```json
    {
      "success": true,
      "message": "Document retrieved successfully",
      "data": {
        "document": {
          "id": "1a2b3c...",
          "filename": "laporan_keuangan.pdf",
          "contentType": "application/pdf",
          "status": "READY",
          "summary": "Ringkasan dokumen...",
          "storagePath": "documents/1a2b3c...pdf",
          "downloadUrl": "https://storage.googleapis...",
          "createdAt": "2026-06-30T10:00:00Z",
          "updatedAt": "2026-06-30T10:05:00Z",
          "ownerId": "user-uid"
        }
      }
    }
    ```

---

## 4. Endpoint Chat

### Tanya Jawab dengan Dokumen (RAG)
Mengajukan pertanyaan mengenai isi dokumen tertentu. Sistem akan mencari referensi pada data ekstraksi teks dokumen dan menjawabnya menggunakan Gemini AI.

*   **URL**: `/api/v1/chat` atau `/chat`
*   **Method**: `POST`
*   **Auth Required**: Ya (Permissive)
*   **Format Request**: `application/json`
*   **Body**:
    ```json
    {
      "doc_id": "1a2b3c...",
      "message": "Berapakah laba bersih perusahaan tahun ini?"
    }
    ```
*   **Response (200 OK)**:
    ```json
    {
      "success": true,
      "message": "Chat successful",
      "data": {
        "reply": "Berdasarkan dokumen laporan keuangan halaman 3, laba bersih perusahaan tahun ini adalah Rp 500.000.000."
      }
    }
    ```

---

## 5. Endpoint Pemrosesan Gambar (Single Image Upload)

### Unggah & Proses Gambar Mandiri (Asinkron)
Mengunggah satu file gambar mandiri (misalnya hasil foto kamera HP) secara asinkron tanpa dokumen PDF. Gambar akan disimpan secara permanen di Firestore dalam koleksi `uploaded_images` sebagai riwayat pemindaian gambar (*Scan History*), dan pemrosesan deskripsi dilakukan di latar belakang (background thread).

*   **URL**: `/api/v1/images/process`
*   **Method**: `POST`
*   **Auth Required**: Ya (Permissive)
*   **Format Request**: `multipart/form-data`
*   **Body**:
    *   `file`: File Gambar (.jpg, .jpeg, .png - Maksimal 16MB)
*   **Response (202 Accepted)**:
    ```json
    {
      "success": true,
      "message": "Image processing started",
      "data": {
        "id": "5960582b-b087-4ec2-913c-27358317e78b",
        "status": "PROCESSING",
        "progress": 0
      }
    }
    ```

### Cek Status & Detail Pemrosesan Gambar
Mengambil status riwayat dan perkembangan pemrosesan gambar berdasarkan ID tertentu. Endpoint ini mengembalikan status progres selama pemrosesan latar belakang berjalan dan detail konten aksesibilitas jika sudah selesai.

*   **URL**: `/api/v1/images/<image_id>`
*   **Method**: `GET`
*   **Auth Required**: Ya (Permissive)
*   **Response (200 OK - Sedang Diproses)**:
    ```json
    {
      "success": true,
      "data": {
        "id": "5960582b-b087-4ec2-913c-27358317e78b",
        "ownerId": "user-uid",
        "filename": "materi_grafik.png",
        "status": "PROCESSING",
        "progress": 60,
        "currentStep": "Analyzing image",
        "imageUrl": "https://storage.googleapis.com/.../5960582b-b087-4ec2-913c-27358317e78b.png",
        "createdAt": "2026-07-06T06:00:00Z",
        "updatedAt": "2026-07-06T06:01:00Z"
      }
    }
    ```
*   **Response (200 OK - Selesai / READY)**:
    ```json
    {
      "success": true,
      "data": {
        "id": "5960582b-b087-4ec2-913c-27358317e78b",
        "ownerId": "user-uid",
        "filename": "materi_grafik.png",
        "status": "READY",
        "progress": 100,
        "currentStep": "Completed",
        "imageUrl": "https://storage.googleapis.com/.../5960582b-b087-4ec2-913c-27358317e78b.png",
        "accessibility_content": {
          "alt_text_totally_blind": "Grafik fungsi kuadrat terbuka ke atas dengan titik puncak (0,0)...",
          "visual_explanation_deaf": "- Menunjukkan grafik y = x^2\n- Titik minimum berada di titik asal (0,0)"
        },
        "createdAt": "2026-07-06T06:00:00Z",
        "updatedAt": "2026-07-06T06:03:00Z"
      }
    }
    ```
*   **Response (200 OK - Gagal / FAILED)**:
    ```json
    {
      "success": true,
      "data": {
        "id": "5960582b-b087-4ec2-913c-27358317e78b",
        "ownerId": "user-uid",
        "filename": "materi_grafik.png",
        "status": "FAILED",
        "progress": 100,
        "currentStep": "Failed",
        "errorMessage": "Gemini API access denied. Please verify your API key and project status.",
        "imageUrl": "https://storage.googleapis.com/.../5960582b-b087-4ec2-913c-27358317e78b.png",
        "createdAt": "2026-07-06T06:00:00Z",
        "updatedAt": "2026-07-06T06:01:00Z"
      }
    }
    ```

### List Riwayat Gambar Mandiri
Mendapatkan semua gambar mandiri yang pernah diunggah oleh pengguna terautentikasi beserta hasil analisis aksesibilitasnya.

*   **URL**: `/api/v1/images`
*   **Method**: `GET`
*   **Auth Required**: Ya (Permissive)
*   **Response (200 OK)**:
    ```json
    {
      "success": true,
      "data": [
        {
          "id": "5960582b-b087-4ec2-913c-27358317e78b",
          "ownerId": "user-uid",
          "filename": "materi_grafik.png",
          "status": "READY",
          "progress": 100,
          "currentStep": "Completed",
          "imageUrl": "https://storage.googleapis.com/.../5960582b-b087-4ec2-913c-27358317e78b.png",
          "accessibility_content": {
            "alt_text_totally_blind": "Grafik fungsi kuadrat terbuka ke atas dengan titik puncak (0,0)...",
            "visual_explanation_deaf": "- Menunjukkan grafik y = x^2\n- Titik minimum berada di titik asal (0,0)"
          },
          "createdAt": "2026-07-06T06:00:00Z",
          "updatedAt": "2026-07-06T06:03:00Z"
        }
      ]
    }
    ```

---

## 6. Endpoint Umpan Balik & Evaluasi (Feedback)

### Kirim Feedback Pengguna
Mengirim rating dan tag evaluasi untuk seksi dokumen atau analisis gambar. Jika terdeteksi rating rendah (`BAD`) atau tag negatif, sistem otomatis memicu alur optimasi prompt.

*   **URL**: `/api/v1/feedback`
*   **Method**: `POST`
*   **Auth Required**: Ya (Permissive)
*   **Format Request**: `application/json`
*   **Body**:
    ```json
    {
      "targetId": "1a2b3c...",
      "targetType": "DOCUMENT",
      "rating": "BAD",
      "tags": ["Inaccurate", "Hard to Understand"],
      "comment": "Konversi rumus matematika kurang tepat."
    }
    ```
    *   `targetType`: `"DOCUMENT"` atau `"IMAGE"`.
    *   `rating`: `"EXCELLENT"`, `"GOOD"`, `"OKAY"`, atau `"BAD"`.
    *   `tags` (List of Strings): tag penilai, misalnya `["Missing Information", "Too Complicated", "Inaccurate", "Hard to Understand"]`.
    *   `comment` (String, Optional): Komentar opsional dari pengguna, maksimal 300 karakter.
*   **Response (200 OK)**:
    ```json
    {
      "data": {
        "id": "feedback-uuid"
      },
      "message": "Feedback submitted successfully. Thank you for helping us improve Inclusia!",
      "success": true
    }
    ```

### Jalankan Optimasi Prompt Umpan Balik (Feedback Loop)
Memproses seluruh feedback negatif yang berstatus `PENDING_OPTIMIZATION`. Gemini AI akan secara otomatis memformulasi ulang dan merevisi sistem prompt di Firestore demi meningkatkan kualitas pemrosesan materi berikutnya.

*   **URL**: `/api/v1/feedback/optimize`
*   **Method**: `POST`
*   **Auth Required**: Ya (Permissive)
*   **Response (200 OK)**:
    ```json
    {
      "success": true,
      "message": "Processed 1 pending optimizations.",
      "data": {
        "processedCount": 1
      }
    }
    ```
