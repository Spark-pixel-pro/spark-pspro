import streamlit as st
from supabase import create_client
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from sentence_transformers import SentenceTransformer
import PyPDF2
import docx
import io

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
st.caption("Pobiera pliki z folderu na Drive, dzieli na fragmenty i zapisuje do bazy wiedzy Sparka")


@st.cache_resource
def load_embedding_model():
    return SentenceTransformer('all-MiniLM-L6-v2')


def get_drive_service():
    creds_dict = dict(st.secrets["gdrive_service_account"])
    creds = service_account.Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )
    return build("drive", "v3", credentials=creds)


def list_files(service, folder_id):
    query = f"'{folder_id}' in parents and trashed = false"
    results = service.files().list(
        q=query,
        fields="files(id, name, mimeType)",
        pageSize=1000
    ).execute()
    return results.get("files", [])


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


def extract_text(service, file):
    mime = file["mimeType"]
    name = file["name"]

    try:
        if mime == "application/vnd.google-apps.document":
            return export_google_file(service, file["id"], "text/plain")

        elif mime == "application/vnd.google-apps.spreadsheet":
            return export_google_file(service, file["id"], "text/csv")

        elif mime == "application/vnd.google-apps.presentation":
            return export_google_file(service, file["id"], "text/plain")

        elif mime == "application/pdf":
            buffer = download_file(service, file["id"])
            reader = PyPDF2.PdfReader(buffer)
            text = ""
            for page in reader.pages:
                page_text = page.extract_text() or ""
                text += page_text
            return text

        elif mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            buffer = download_file(service, file["id"])
            document = docx.Document(buffer)
            return "\n".join([p.text for p in document.paragraphs])

        elif mime == "text/plain":
            buffer = download_file(service, file["id"])
            return buffer.read().decode("utf-8", errors="ignore")

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


if st.button("🚀 Synchronizuj teraz", type="primary"):
    model = load_embedding_model()
    service = get_drive_service()

    with st.spinner("Pobieram listę plików z Google Drive..."):
        files = list_files(service, GDRIVE_FOLDER_ID)

    st.info(f"Znaleziono {len(files)} plików w folderze.")

    progress = st.progress(0)
    status = st.empty()
    total_chunks = 0

    for idx, file in enumerate(files):
        status.text(f"Przetwarzam: {file['name']} ({idx + 1}/{len(files)})")

        text = extract_text(service, file)

        if text and text.strip():
            char_count = len(text.strip())
            st.write(f"✅ **{file['name']}** — wyciągnięto {char_count} znaków tekstu")

            supabase.table("wiedza").delete().eq("zrodlo", file["name"]).execute()

            chunks = chunk_text(text)
            for chunk in chunks:
                embedding = model.encode(chunk).tolist()
                supabase.table("wiedza").insert({
                    "zrodlo": file["name"],
                    "fragment": chunk,
                    "embedding": embedding
                }).execute()
                total_chunks += 1
        else:
            st.write(f"⚠️ **{file['name']}** — brak wyciągniętego tekstu (0 znaków)")

        progress.progress((idx + 1) / len(files))

    status.text("")
    st.success(f"✅ Gotowe! Przetworzono {len(files)} plików, zapisano {total_chunks} fragmentów wiedzy.")

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
    st.write("Baza wiedzy jest jeszcze pusta — kliknij 'Synchronizuj teraz' powyżej.")
