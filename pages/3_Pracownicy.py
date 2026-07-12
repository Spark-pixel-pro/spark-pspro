import streamlit as st
from supabase import create_client
from sentence_transformers import SentenceTransformer
from groq import Groq

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
st.caption("Asystent wewnętrzny PS PRO Solutions")

BRAK_ODPOWIEDZI_TEKST = "Nie znalazłem tej informacji w bazie wiedzy"


@st.cache_resource
def load_embedding_model():
    return SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')


def search_knowledge(question, match_count=6):
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
        fragment = chunk['fragment']
        if len(fragment) > 800:
            fragment = fragment[:800] + "..."
        parts.append(f"[Źródło: {chunk['zrodlo']}]\n{fragment}")
    return "\n\n---\n\n".join(parts)


SYSTEM_PROMPT = f"""Jesteś Spark, wewnętrznym asystentem pracownikow firmy PS PRO Solutions, zajmującej się świadectwami charakterystyki energetycznej budynkow.

Zasady:
- Odpowiadaj WYŁĄCZNIE na podstawie dostarczonego kontekstu z bazy wiedzy firmy.
- Jeśli w kontekście nie ma odpowiedzi, powiedz DOKŁADNIE tymi słowami: "{BRAK_ODPOWIEDZI_TEKST}."
- Zawsze podawaj z jakiego dokumentu pochodzi informacja.
- Odpowiadaj krótko, konkretnie, po polsku, tonem kolegi z pracy.
- Nie zmyślaj przepisów ani procedur.
- Jeśli źrodło wyraźnie nie pasuje do pytania, zignoruj je i nie cytuj."""


def zapytaj_internet(pytanie):
    completion = groq_client.chat.completions.create(
        model="compound-beta",
        messages=[
            {"role": "system", "content": "Odpowiadaj krótko i konkretnie po polsku, na podstawie aktualnych informacji z internetu."},
            {"role": "user", "content": pytanie}
        ]
    )
    return completion.choices[0].message.content


if "employee_messages" not in st.session_state:
    st.session_state.employee_messages = []
if "pending_web_question" not in st.session_state:
    st.session_state.pending_web_question = None

for message in st.session_state.employee_messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if st.session_state.pending_web_question:
    with st.chat_message("assistant"):
        st.markdown("🤔 Nie znalazłem tej informacji w firmowej bazie wiedzy. Chcesz, żebym sprawdził w internecie?")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ Tak, sprawdź w internecie", key="web_yes"):
                pytanie = st.session_state.pending_web_question
                with st.spinner("Szukam w internecie..."):
                    odpowiedz_net = zapytaj_internet(pytanie)
                tresc = "🌐 **Ogólna wiedza z internetu — zweryfikuj przed zastosowaniem, to NIE jest firmowa procedura:**\n\n" + odpowiedz_net
                st.session_state.employee_messages.append({"role": "assistant", "content": tresc})
                st.session_state.pending_web_question = None
                st.rerun()
        with col2:
            if st.button("❌ Nie, dziękuję", key="web_no"):
                st.session_state.employee_messages.append({"role": "assistant", "content": "OK, nie sprawdzam w internecie."})
                st.session_state.pending_web_question = None
                st.rerun()

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
                user_prompt = "Pytanie pracownika: " + question + "\n\n(Nie znaleziono powiązanych fragmentów.)"

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

    if BRAK_ODPOWIEDZI_TEKST in answer:
        st.session_state.pending_web_question = question
        st.rerun()
