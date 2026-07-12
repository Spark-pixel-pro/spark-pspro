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


SYSTEM_PROMPT = """Jesteś Spark, wewnętrznym asystentem pracownikow firmy PS PRO Solutions, zajmującej się świadectwami charakterystyki energetycznej budynkow.

Odpowiadasz pracownikom na pytania o procedury, przepisy, przykłady wcześniejszych świadectw i wiedzę techniczną firmy.

Zasady:
- Odpowiadaj WYŁĄCZNIE na podstawie dostarczonego kontekstu z bazy wiedzy firmy.
- Jeśli w kontekście nie ma odpowiedzi na pytanie, powiedz wprost: Nie znalazłem tej informacji w bazie wiedzy, sprawdź u przełożonego lub w oryginalnych dokumentach.
- Zawsze podawaj z jakiego dokumentu pochodzi informacja.
- Odpowiadaj krótko, konkretnie, po polsku, tonem kolegi z pracy, pomocnym, ale rzeczowym.
- Nie zmyślaj przepisów ani procedur, ktorych nie ma w kontekście.
- Jeśli ktorys z dostarczonych fragmentow wyraźnie nie pasuje do pytania, na przyklad nazwa pliku to zdjęcie bez sensownej treści, zignoruj go i nie cytuj jako źrodła."""


if "employee_messages" not in st.session_state:
    st.session_state.employee_messages = []

for message in st.session_state.employee_messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

question = st.chat_input("Zapytaj o procedurę, przepis, przykład świadectwa...")

if question:
    st.session_state.employee_messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Szukam w bazie wiedzy..."):
            chunks = search_knowledge(question)
            context = build_context(chunks)

            if context:
                user_prompt = "Kontekst z bazy wiedzy firmy:\n\n" + context + "\n\n---\n\nPytanie pracownika: " + question
            else:
                user_prompt = "Pytanie pracownika: " + question + "\n\n(Nie znaleziono żadnych powiązanych fragmentów w bazie wiedzy.)"

            completion = groq_client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ]
            )

            answer = completion.choices[0].message.content
            st.markdown(answer)

            if chunks:
                with st.expander("📄 Źródła użyte do odpowiedzi"):
                    unique_sources = set(c["zrodlo"] for c in chunks)
                    for source in sorted(unique_sources):
                        st.write(f"- {source}")

    st.session_state.employee_messages.append({"role": "assistant", "content": answer})
