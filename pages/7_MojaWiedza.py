import streamlit as st
from supabase import create_client
import cohere
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
import time
from datetime import datetime

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
COHERE_API_KEY = st.secrets["COHERE_API_KEY"]
FIRMA_NAZWA = st.secrets["FIRMA_NAZWA"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
cohere_client = cohere.Client(COHERE_API_KEY)

st.set_page_config(page_title="Spark - Moja wiedza", layout="wide")

import streamlit.components.v1 as components

components.html("""
<script>
  const link = document.createElement('link');
  link.rel = 'manifest';
  link.href = '/app/static/manifest.json';
  window.parent.document.head.appendChild(link);
</script>
""", height=0)

# ====== OCHRONA HASŁEM (KLIENT) ======
if "zalogowany_klient" not in st.session_state:
    st.session_state.zalogowany_klient = False

if not st.session_state.zalogowany_klient:
    st.title("🔒 Panel wiedzy firmy")
    haslo = st.text_input("Hasło:", type="password")
    if st.button("Zaloguj"):
        if haslo == st.secrets["KLIENT_HASLO"]:
            st.session_state.zalogowany_klient = True
            st.rerun()
        else:
            st.error("Nieprawidłowe hasło")
    st.stop()

st.markdown("""
<style>
    .stApp { background-color: #111111; }
    h1, h2, h3 { color: #FFD600 !important; }
</style>
""", unsafe_allow_html=True)

st.title("📚 Moja wiedza")
st.caption(f"Dodawaj i zarządzaj dokumentami, na których opiera się Spark — {FIRMA_NAZWA}")


def get_embeddings_batch(texts, input_type="search_document", max_retries=5):
    for attempt in range(max_retries):
        try:
            response = cohere_client.embed(
                texts=texts,
                model="embed-multilingual-v3.0",
                input_type=input_type
            )
            return response.embeddings
        except Exception as e:
            if "429" in str(e) or "rate" in str(e).lower():
                time.sleep(10 * (attempt + 1))
            else:
                raise
    raise Exception("Nie udało się przetworzyć po kilku próbach.")


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


def extract_xls_text(file_bytes, engine):
    all_text = []
    excel_file = pd.ExcelFile(io.BytesIO(file_bytes), engine=engine)
    for sheet_name in excel_file.sheet_names:
        df = excel_file.parse(sheet_name, header=None)
        all_text.append(f"[Arkusz: {sheet_name}]")
        all_text.append(df.to_string(index=False, header=False))
    return "\n".join(all_text)


def wyciagnij_tekst(plik):
    nazwa = plik.name
    rozszerzenie = nazwa.lower().split(".")[-1]
    zawartosc = plik.read()

    try:
        if rozszerzenie == "pdf":
            reader = PyPDF2.PdfReader(io.BytesIO(zawartosc))
            text = ""
            for page in reader.pages:
                text += page.extract_text() or ""
            if text.strip():
                return text
            else:
                st.write(f"🔍 '{nazwa}' wygląda na skan — odczytuję obrazem (chwilę to potrwa)...")
                return ocr_pdf_bytes(zawartosc)
        elif rozszerzenie == "docx":
            document = docx.Document(io.BytesIO(zawartosc))
            return "\n".join([p.text for p in document.paragraphs])
        elif rozszerzenie == "doc":
            return extract_old_doc_text(zawartosc)
        elif rozszerzenie == "odt":
            return extract_odt_text(io.BytesIO(zawartosc))
        elif rozszerzenie == "xlsx":
            return extract_xls_text(zawartosc, "openpyxl")
        elif rozszerzenie == "xls":
            return extract_xls_text(zawartosc, "xlrd")
        elif rozszerzenie == "txt":
            return zawartosc.decode("utf-8", errors="ignore")
        elif rozszerzenie in ["jpg", "jpeg", "png", "webp"]:
            st.write(f"🔍 Odczytuję tekst ze zdjęcia '{nazwa}'...")
            return ocr_image_bytes(zawartosc)
        else:
            st.warning(f"⚠️ Nieobsługiwany format pliku: {nazwa}")
            return None
    except Exception as e:
        st.warning(f"⚠️ Nie udało się odczytać '{nazwa}': {e}")
        return None


def chunk_text(text, chunk_size=500):
    words = text.split()
    chunks = []
    for i in range(0, len(words), chunk_size):
        chunk = " ".join(words[i:i + chunk_size])
        if chunk.strip():
            chunks.append(chunk)
    return chunks


def dodaj_do_wiedzy(nazwa_pliku, tekst):
    chunks = chunk_text(tekst)
    if not chunks:
        return 0

    batch_size = 90
    all_embeddings = []
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        embeddings = get_embeddings_batch(batch)
        all_embeddings.extend(embeddings)

    new_ids = []
    for chunk, embedding in zip(chunks, all_embeddings):
        result = supabase.table("wiedza").insert({
            "zrodlo": f"Wgrane przez klienta/{nazwa_pliku}",
            "fragment": chunk,
            "embedding": embedding
        }).execute()
        if result.data:
            new_ids.append(result.data[0]["id"])

    supabase.table("tekst_cache").upsert({
        "zrodlo": f"Wgrane przez klienta/{nazwa_pliku}",
        "tekst": tekst
    }).execute()

    return len(new_ids)


# ====== SEKCJA WGRYWANIA ======
st.subheader("➕ Dodaj nowy dokument")
st.write("Obsługiwane formaty: PDF, Word (.docx, .doc), Excel (.xlsx, .xls), OpenDocument (.odt), zdjęcia (.jpg, .png), zwykły tekst (.txt)")

uploaded_files = st.file_uploader(
    "Wybierz plik lub przeciągnij tutaj",
    accept_multiple_files=True,
    type=["pdf", "docx", "doc", "odt", "xlsx", "xls", "txt", "jpg", "jpeg", "png", "webp"]
)

if uploaded_files and st.button("📤 Dodaj do wiedzy Sparka", type="primary"):
    for plik in uploaded_files:
        with st.spinner(f"Przetwarzam {plik.name}..."):
            tekst = wyciagnij_tekst(plik)
            if tekst and tekst.strip():
                liczba_fragmentow = dodaj_do_wiedzy(plik.name, tekst)
                st.success(f"✅ '{plik.name}' dodane — Spark już z tego korzysta ({liczba_fragmentow} fragmentów wiedzy)")
            else:
                st.warning(f"⚠️ Nie udało się wyciągnąć tekstu z '{plik.name}'")

st.divider()

# ====== SEKCJA LISTY ======
st.subheader("📄 Aktualna wiedza Sparka")

response = supabase.table("wiedza").select("zrodlo").execute()
if response.data:
    unique_sources = sorted(set(row["zrodlo"] for row in response.data))
    st.write(f"Spark korzysta obecnie z **{len(unique_sources)}** dokumentów.")

    for source in unique_sources:
        col1, col2 = st.columns([5, 1])
        with col1:
            nazwa_wyswietlana = source.replace("Wgrane przez klienta/", "📎 ")
            st.write(nazwa_wyswietlana)
        with col2:
            if st.button("🗑️ Usuń", key=f"usun_{source}"):
                supabase.table("wiedza").delete().eq("zrodlo", source).execute()
                supabase.table("tekst_cache").delete().eq("zrodlo", source).execute()
                st.rerun()
else:
    st.info("Spark nie ma jeszcze żadnej wiedzy — dodaj pierwszy dokument powyżej.")
