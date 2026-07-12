import streamlit as st
from supabase import create_client
from sentence_transformers import SentenceTransformer
from groq import Groq

# ====== KONFIGURACJA ======
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
GROQ_API_KEY = st.secrets["GROQ_API_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
groq_client = Groq(api_key=GROQ_API_KEY)

st.set_page_config(page_title="Spark - Panel Pracowników", layout="centered")

st.markdown("""
<style>
    .stApp { background-color: #111111; }
    h1, h2, h3 { color: #FFD600 !important; }
    .stChatMessage { background-color: #1a1a1a; }
</style>
""", unsafe_allow_html=True)

st.title("👷 Spark — Panel Pracowników")
st.caption("Asystent wewnętrzny PS PRO Solutions — pyta bazę wiedzy firmy (procedury, przykłady świadectw, przepisy)")


@st.cache_resource
def load_embedding_model():
    return SentenceTransformer('all-MiniLM-L6-v2')


def search_knowledge(question, match_count=10):
    model = load_embedding_model()
    query_embedding = model.encode(question).tolist()

    response = supabase.rpc(
        "match_wiedza",
        {"query_embedding": query_embedding, "match_count": match_count}
    ).execute()

    return response.data


def build_context(chunks):
    if not chunks:
        return ""
    parts = []
    for chunk in chunks:
        parts.append(f"[Źródło: {chunk['zrodlo']}]\n{chunk['fragment']}")
    return "\n\n---\n\n".join(parts)


SYSTEM_PROMPT = """Jesteś Spark, wewnętrznym asystentem pracowników firmy PS PRO Solutions, zajmującej się świadectwami
