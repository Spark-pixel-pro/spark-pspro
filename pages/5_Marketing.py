import streamlit as st
from supabase import create_client
import cohere
from groq import Groq
import re

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
GROQ_API_KEY = st.secrets["GROQ_API_KEY"]
COHERE_API_KEY = st.secrets["COHERE_API_KEY"]
FIRMA_NAZWA = st.secrets["FIRMA_NAZWA"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
groq_client = Groq(api_key=GROQ_API_KEY)
cohere_client = cohere.Client(COHERE_API_KEY)

st.set_page_config(page_title="Spark - Marketing", layout="wide")

# ====== OCHRONA HASŁEM (ADMIN) ======
if "zalogowany_admin" not in st.session_state:
    st.session_state.zalogowany_admin = False

if not st.session_state.zalogowany_admin:
    st.title("🔒 Dostęp ograniczony")
    haslo = st.text_input("Hasło administratora:", type="password")
    if st.button("Zaloguj"):
        if haslo == st.secrets["ADMIN_HASLO"]:
            st.session_state.zalogowany_admin = True
            st.rerun()
        else:
            st.error("Nieprawidłowe hasło")
    st.stop()

st.markdown("""
<style>
    .stApp { background-color: #111111; }
    h1, h2, h3 { color: #FFD600 !important; }
    .stTextArea textarea { background-color: #1a1a1a; color: #f0f0f0; }
</style>
""", unsafe_allow_html=True)

st.title("📢 Generator treści marketingowych")
st.caption(f"Twórz posty i artykuły bazujące na wiedzy o {FIRMA_NAZWA}")


def get_query_embedding(text):
    response = cohere_client.embed(
        texts=[text],
        model="embed-multilingual-v3.0",
        input_type="search_query"
    )
    return response.embeddings[0]


def znajdz_kontekst(temat, match_count=4):
    try:
        wektor = get_query_embedding(temat)
        response = supabase.rpc(
            "match_wiedza",
            {"query_embedding": wektor, "match_count": match_count}
        ).execute()
        fragmenty = response.data or []
        if not fragmenty:
            return ""
        return "\n\n".join([f["fragment"][:500] for f in fragmenty])
    except Exception:
        return ""


def generuj_tresc(temat, platforma, kontekst):
    opisy_platform = {
        "Facebook": "dłuższy post na Facebook, ciepły i konwersacyjny ton, może zawierać pytanie na końcu angażujące czytelników, 3-6 zdań",
        "Instagram": "krótki, chwytliwy post na Instagram, energiczny ton, można użyć emoji, max 3-4 zdania, zakończ 3-5 trafnymi hashtagami",
        "Blog": "dłuższy, wartościowy fragment artykułu na bloga, przystępny ton bez żargonu, 150-250 słów"
    }

    kontekst_info = f"\n\nDodatkowy kontekst o firmie:\n{kontekst}" if kontekst else ""

    prompt = f"""Jesteś asystentem marketingowym firmy {FIRMA_NAZWA}.

Napisz {opisy_platform[platforma]} na temat: {temat}

Zasady:
- Pisz po polsku, przystępnym językiem, bez żargonu technicznego
- Ton: profesjonalny, ale ciepły i ludzki, nie korporacyjny
- Nie zmyślaj konkretnych liczb ani faktów, których nie ma w kontekście
- Nie używaj nazwy firmy nachalnie więcej niż raz-dwa razy{kontekst_info}"""

    completion = groq_client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[{"role": "user", "content": prompt}]
    )
    return completion.choices[0].message.content


col1, col2 = st.columns([2, 1])
with col1:
    temat = st.text_input("O czym ma być treść?", placeholder="np. jak asystent AI pomaga pracownikom szukać dokumentów")
with col2:
    platforma = st.selectbox("Platforma", ["Facebook", "Instagram", "Blog"])

uzyj_wiedzy = st.checkbox("Wykorzystaj firmową bazę wiedzy jako kontekst", value=True)

if st.button("✨ Generuj treść", type="primary"):
    if not temat.strip():
        st.warning("Wpisz temat, o którym ma być treść.")
    else:
        with st.spinner("Szukam kontekstu i piszę..."):
            kontekst = znajdz_kontekst(temat) if uzyj_wiedzy else ""
            wygenerowana_tresc = generuj_tresc(temat, platforma, kontekst)
            st.session_state["ostatnia_tresc"] = wygenerowana_tresc
            st.session_state["ostatni_kontekst"] = kontekst

if "ostatnia_tresc" in st.session_state:
    st.divider()
    st.subheader(f"📝 Wygenerowana treść ({platforma})")
    edytowalna_tresc = st.text_area(
        "Możesz edytować przed skopiowaniem:",
        value=st.session_state["ostatnia_tresc"],
        height=200
    )
    st.code(edytowalna_tresc, language=None)

    if st.session_state.get("ostatni_kontekst"):
        with st.expander("📄 Kontekst użyty z bazy wiedzy"):
            st.write(st.session_state["ostatni_kontekst"])
