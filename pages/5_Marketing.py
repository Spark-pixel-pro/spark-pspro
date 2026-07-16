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
st.caption(f"Twórz posty i artykuły bazujące na wiedzy o {FIRMA_NAZWA} i aktualnych trendach")


def get_query_embedding(text):
    response = cohere_client.embed(
        texts=[text],
        model="embed-multilingual-v3.0",
        input_type="search_query"
    )
    return response.embeddings[0]


def znajdz_kontekst_firmy(temat, match_count=4):
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


def research_w_internecie(temat, platforma):
    prompt = f"""Wyszukaj aktualne, praktyczne informacje przydatne do napisania posta marketingowego na {platforma} na temat: {temat}

Szukaj: aktualnych trendów, dobrych praktyk dla tego typu treści, ewentualnie ciekawych faktów lub statystyk związanych z tematem.
Odpowiedz krótko, w punktach, po polsku. Maksymalnie 5-6 punktów."""

    completion = groq_client.chat.completions.create(
        model="groq/compound",
        messages=[{"role": "user", "content": prompt}]
    )
    return completion.choices[0].message.content


def generuj_tresc(temat, platforma, kontekst_firmy, kontekst_internet):
    opisy_platform = {
        "Facebook": "dłuższy post na Facebook, ciepły i konwersacyjny ton, może zawierać pytanie na końcu angażujące czytelników, 3-6 zdań",
        "Instagram": "krótki, chwytliwy post na Instagram, energiczny ton, można użyć emoji, max 3-4 zdania, zakończ 3-5 trafnymi hashtagami",
        "Blog": "dłuższy, wartościowy fragment artykułu na bloga, przystępny ton bez żargonu, 150-250 słów"
    }

    info_firma = f"\n\nKontekst o firmie:\n{kontekst_firmy}" if kontekst_firmy else ""
    info_internet = f"\n\nAktualne informacje/inspiracje z internetu:\n{kontekst_internet}" if kontekst_internet else ""

    prompt = f"""Jesteś asystentem marketingowym firmy {FIRMA_NAZWA}.

Napisz {opisy_platform[platforma]} na temat: {temat}

Zasady:
- Pisz po polsku, przystępnym językiem, bez żargonu technicznego
- Ton: profesjonalny, ale ciepły i ludzki, nie korporacyjny
- Nie zmyślaj konkretnych liczb ani faktów, których nie ma w podanym kontekście
- Nie używaj nazwy firmy nachalnie więcej niż raz-dwa razy{info_firma}{info_internet}"""

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

col3, col4 = st.columns(2)
with col3:
    uzyj_wiedzy = st.checkbox("📚 Wykorzystaj firmową bazę wiedzy", value=True)
with col4:
    uzyj_internetu = st.checkbox("🌐 Sprawdź trendy/inspiracje w internecie", value=False)

if st.button("✨ Generuj treść", type="primary"):
    if not temat.strip():
        st.warning("Wpisz temat, o którym ma być treść.")
    else:
        kontekst_firmy = ""
        kontekst_internet = ""

        if uzyj_wiedzy:
            with st.spinner("Szukam kontekstu w bazie wiedzy firmy..."):
                kontekst_firmy = znajdz_kontekst_firmy(temat)

        if uzyj_internetu:
            with st.spinner("Szukam inspiracji i trendów w internecie..."):
                kontekst_internet = research_w_internecie(temat, platforma)

        with st.spinner("Piszę treść..."):
            wygenerowana_tresc = generuj_tresc(temat, platforma, kontekst_firmy, kontekst_internet)
            st.session_state["ostatnia_tresc"] = wygenerowana_tresc
            st.session_state["ostatni_kontekst_firmy"] = kontekst_firmy
            st.session_state["ostatni_kontekst_internet"] = kontekst_internet

if "ostatnia_tresc" in st.session_state:
    st.divider()
    st.subheader(f"📝 Wygenerowana treść ({platforma})")
    edytowalna_tresc = st.text_area(
        "Możesz edytować przed skopiowaniem:",
        value=st.session_state["ostatnia_tresc"],
        height=200
    )
    st.code(edytowalna_tresc, language=None)

    if st.session_state.get("ostatni_kontekst_firmy"):
        with st.expander("📄 Kontekst z bazy wiedzy firmy"):
            st.write(st.session_state["ostatni_kontekst_firmy"])

    if st.session_state.get("ostatni_kontekst_internet"):
        with st.expander("🌐 Informacje znalezione w internecie"):
            st.write(st.session_state["ostatni_kontekst_internet"])
