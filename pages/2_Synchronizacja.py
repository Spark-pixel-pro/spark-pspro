import streamlit as st
from supabase import create_client
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from sentence_transformers import SentenceTransformer
from pdf2image import convert_from_bytes
from PIL import Image
from odf.opendocument import load as odf_load
from odf import text as odf_text
from odf.table import TableCell
from odf.teletype import extractText
import pytesseract
import PyPDF2
import docx
import pandas as pd
import io
import subprocess
import tempfile
import os

# ====== KONFIGURACJA ======
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
GDRIVE_FOLDER_ID = st.secrets["GDRIVE_FOLDER_ID"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

st.set_page_config(page_title="Spark - Synchronizacja", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #111111; }
    h1, h2, h3 { color: #FFD600 !important; }
</style>
""", unsafe_allow_html=True)

st.title("🔄 Synchronizacja wiedzy z Google Drive")
st.caption("Pobiera pliki, dzieli na fragmenty, zapisuje do bazy wiedzy Sparka. Używa cache tekstu — zmiana modelu embeddingowego nie wymaga ponownego OCR.")


@st.cache_resource
def load_embedding_model():
    return SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')


def get_drive_service():
    creds_dict = dict(st.secrets["gdrive_service_account"])
    creds = service_account.Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )
    return build("drive", "v3", credentials=creds)


def list_files(service, folder_id, path=""):
    all_files = []
    query = f"'{folder_id}' in parents and trashed = false"
    results = service.files().list(
        q=query,
        fields="files(id, name, mimeType, size)",
        pageSize=1000
    ).execute()
    items = results.get("files", [])

    for item in items:
        if item["mimeType"] == "application/vnd.google-apps.folder":
            subfolder_path = f"{path}/{item['name']}" if path else item["name"]
            all_files.extend(list_files(service, item["id"], subfolder_path))
        else:
            item["folder_path"] = path
            all_files.append(item)

    return all_files


def get_cached_text(source_label):
    response = supabase.table("tekst_cache").select("tekst").eq("zrodlo", source_label).execute()
    if response.data:
        return response.data[0]["tekst"]
    return None


def save_to_cache(source_label, text):
    supabase.table("tekst_cache").upsert({
        "zrodlo": source_label,
        "tekst": text
    }).execute()


def download_file(service, file_id):
    request = service.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buffer.seek(0)
    return buffer


def export_google_file(service, file_id, mime_type):
    request = service.files().export_media(fileId=file_id, mimeType=mime_type)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buffer.seek(0)
    return buffer.read().decode("utf-8", errors="ignore")


def ocr_image_bytes(image_bytes):
    image = Image.open(io.BytesIO(image_bytes))
    return pytesseract.image_to_string(image, lang="pol")


def ocr_pdf_bytes(pdf_bytes, max_pages=15):
    pages = convert_from_bytes(pdf_bytes, dpi=120, last_page=max_pages)
    full_text = ""
    for page_image in pages:
        full_text += pytesseract.image_to_string(page_image, lang="pol") + "\n"
    return full_text


def extract_odt_text(buffer):
    doc = odf_load(buffer)
    all_text = []
    for p in doc.getElementsByType(odf_text.P):
        t = extractText(p)
        if t.strip():
            all_text.append(t)
    for h in doc.getElementsByType(odf_text.H):
        t = extractText(h)
        if t.strip():
            all_text.append(t)
    for li in doc.getElementsByType(odf_text.ListItem):
        t = extractText(li)
        if t.strip():
            all_text.append(t)
    for cell in doc.getElementsByType(TableCell):
        t = extractText(cell)
        if t.strip():
            all_text.append(t)
    return "\n".join(all_text)


def extract_old_doc_text(doc_bytes):
    with tempfile.NamedTemporaryFile(suffix=".doc", delete=False) as tmp:
        tmp.write(doc_bytes)
        tmp_path = tmp.name
    try:
        result = subprocess.run(["antiword", tmp_path], capture_output=True, text=True, timeout=30)
        return result.stdout
    finally:
        os.unlink(tmp_path)


def extract_old_xls_text(xls_bytes):
    all_text = []
    excel_file = pd.ExcelFile(io.BytesIO(xls_bytes), engine="xlrd")
    for sheet_name in excel_file.sheet_names:
        df = excel_file.parse(sheet_name, header=None)
        all_text.append(f"[Arkusz: {sheet_name}]")
        all_text.append(df.to_string(index=False, header=False))
    return "\n".join(all_text)


def extract_xlsx_text(xlsx_bytes):
    all_text = []
    excel_file = pd.ExcelFile(io.BytesIO(xlsx_bytes), engine="openpyxl")
    for sheet_name in excel_file.sheet_names:
        df = excel_file.parse(sheet_name, header=None)
        all_text.append(f"[Arkusz: {sheet_name}]")
        all_text.append(df.to_string(index=False, header=False))
    return "\n".join(all_text)


def extract_text_from_drive(service, file):
    mime = file["mimeType"]
    name = file["name"]

    try:
        file_size = int(file.get("size", 0))
        if file_size > 15 * 1024 * 1024:
            st.warning(f"⚠️ Pomijam '{name}' — plik zbyt duży ({file_size // 1024 // 1024} MB).")
            return None

        if mime == "application/vnd.google-apps.document":
            return export_google_file(service, file["id"], "text/plain")
        elif mime == "application/vnd.google-apps.spreadsheet":
            return export_google_file(service, file["id"], "text/csv")
        elif mime == "application/vnd.google-apps.presentation":
            return export_google_file(service, file["id"], "text/plain")
        elif mime == "application/pdf":
            buffer = download_file(service, file["id"])
            pdf_bytes = buffer.read()
            reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
            text = ""
            for page in reader.pages:
                text += page.extract_text() or ""
            if text.strip():
                return text
            else:
                st.write(f"🔍 '{name}' wygląda na skan — uruchamiam OCR...")
                return ocr_pdf_bytes(pdf_bytes)
        elif mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            buffer = download_file(service, file["id"])
            document = docx.Document(buffer)
            return "\n".join([p.text for p in document.paragraphs])
        elif mime == "application/msword":
            buffer = download_file(service, file["id"])
            return extract_old_doc_text(buffer.read())
        elif mime == "application/vnd.ms-excel":
            buffer = download_file(service, file["id"])
            return extract_old_xls_text(buffer.read())
        elif mime == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
            buffer = download_file(service, file["id"])
            return extract_xlsx_text(buffer.read())
        elif mime == "application/vnd.oasis.opendocument.text":
            buffer = download_file(service, file["id"])
            return extract_odt_text(buffer)
        elif mime == "text/plain":
            buffer = download_file(service, file["id"])
            return buffer.read().decode("utf-8", errors="ignore")
        elif mime in ["image/jpeg", "image/png", "image/webp"]:
            buffer = download_file(service, file["id"])
            st.write(f"🔍 OCR obrazu '{name}'...")
            return ocr_image_bytes(buffer.read())
        else:
            st.warning(f"⚠️ Pomijam '{name}' — nieobsługiwany typ pliku: {mime}")
            return None

    except Exception as e:
        st.warning(f"⚠️ Nie udało się przetworzyć pliku '{name}': {e}")
        return None


def chunk_text(text, chunk_size=500):
    words = text.split()
    chunks = []
    for i in range(0, len(words), chunk_size):
        chunk = " ".join(words[i:i + chunk_size])
        if chunk.strip():
            chunks.append(chunk)
    return chunks


def save_embeddings(source_label, chunks, model):
    new_ids = []
    for chunk in chunks:
        embedding = model.encode(chunk).tolist()
        result = supabase.table("wiedza").insert({
            "zrodlo": source_label,
            "fragment": chunk,
            "embedding": embedding
        }).execute()
        if result.data:
            new_ids.append(result.data[0]["id"])
    if new_ids:
        supabase.table("wiedza").delete().eq("zrodlo", source_label).not_.in_("id", new_ids).execute()
    return len(new_ids)


col1, col2 = st.columns(2)
with col1:
    force_redownload = st.checkbox("🔁 Wymuś ponowne pobranie z Drive (ignoruj cache tekstu)")
with col2:
    force_reembed_only = st.checkbox("⚡ Przelicz TYLKO wektory z cache (bez łączenia z Drive)")

if st.button("🚀 Synchronizuj teraz", type="primary"):
    model = load_embedding_model()

    progress = st.progress(0)
    status = st.empty()
    total_chunks = 0
    processed_count = 0
    cache_hits = 0

    if force_reembed_only:
        response = supabase.table("tekst_cache").select("zrodlo, tekst").execute()
        cached_files = response.data or []
        st.info(f"Znaleziono {len(cached_files)} plików w cache. Przeliczam tylko wektory (bez Google Drive)...")

        for idx, item in enumerate(cached_files):
            source_label = item["zrodlo"]
            text = item["tekst"]
            status.text(f"Przeliczam wektory: {source_label} ({idx + 1}/{len(cached_files)})")

            if text and text.strip():
                chunks = chunk_text(text)
                saved = save_embeddings(source_label, chunks, model)
                total_chunks += saved
                processed_count += 1

            progress.progress((idx + 1) / len(cached_files))

        status.text("")
        st.success(f"✅ Gotowe! Przeliczono wektory dla {processed_count} plików, zapisano {total_chunks} fragmentów.")

    else:
        service = get_drive_service()
        with st.spinner("Pobieram listę plików z Google Drive..."):
            files = list_files(service, GDRIVE_FOLDER_ID)

        st.info(f"Znaleziono {len(files)} plików.")

        for idx, file in enumerate(files):
            source_label = f"{file.get('folder_path', '')}/{file['name']}" if file.get('folder_path') else file['name']
            status.text(f"Przetwarzam: {source_label} ({idx + 1}/{len(files)})")

            text = None
            if not force_redownload:
                text = get_cached_text(source_label)
                if text is not None:
                    cache_hits += 1

            if text is None:
                text = extract_text_from_drive(service, file)
                if text and text.strip():
                    save_to_cache(source_label, text)

            if text and text.strip():
                char_count = len(text.strip())
                chunks = chunk_text(text)
                saved = save_embeddings(source_label, chunks, model)
                total_chunks += saved
                processed_count += 1
                st.write(f"✅ **{source_label}** — {char_count} znaków, zapisano {saved} fragmentów")
            else:
                st.write(f"⚠️ **{source_label}** — brak tekstu (0 znaków)")

            progress.progress((idx + 1) / len(files))

        status.text("")
        st.success(f"✅ Gotowe! Przetworzono {processed_count} plików ({cache_hits} z cache, błyskawicznie), zapisano {total_chunks} fragmentów.")

st.divider()
st.subheader("📊 Aktualny stan bazy wiedzy")

response = supabase.table("wiedza").select("zrodlo").execute()
if response.data:
    unique_sources = set(row["zrodlo"] for row in response.data)
    st.write(f"**{len(unique_sources)}** zsynchronizowanych plików, **{len(response.data)}** fragmentów wiedzy w bazie.")
    with st.expander("Zobacz listę plików"):
        for source in sorted(unique_sources):
            st.write(f"- {source}")
else:
    st.write("Baza wiedzy jest jeszcze pusta.")
