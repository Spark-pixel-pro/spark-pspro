import streamlit as st
from supabase import create_client
from groq import Groq
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ====== KONFIGURACJA ======
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
GROQ_KEY = st.secrets["GROQ_API_KEY"]
GMAIL_EMAIL = st.secrets["GMAIL_EMAIL"]
GMAIL_HASLO = st.secrets["GMAIL_HASLO"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
groq_client = Groq(api_key=GROQ_KEY)

st.set_page_config(page_title="Spark - Follow-upy", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #111111; }
    h1, h2, h3 { color: #FFD600 !important; }
</style>
""", unsafe_allow_html=True)

st.title("📬 Follow-upy do klientów")
st.caption("Klienci bez odpowiedzi od 24h+ — sprawdź gotową treść i wyślij ręcznie")


def generuj_tresc_maila(imie, zainteresowania):
    prompt = f"""Napisz krótki, ciepły ale profesjonalny mail przypominający do klienta firmy PS PRO Solutions
(świadectwa charakterystyki energetycznej budynków).

Klient: {imie}
Rozmawiał wcześniej o: {zainteresowania}

Klient napisał do nas, ale nie sfinalizował zamówienia. Napisz przypomnienie, zapytaj czy nadal jest zainteresowany,
zaproponuj kontakt. Maksymalnie 4-5 zdań. Podpisz jako "Zespół PS PRO Solutions". Nie dodawaj tematu maila, tylko treść."""

    completion = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}]
    )
    return completion.choices[0].message.content


def wyslij_email_do_klienta(email_klienta, tresc, imie):
    try:
        msg = MIMEMultipart()
        msg["From"] = GMAIL_EMAIL
        msg["To"] = email_klienta
        msg["Subject"] = "PS PRO Solutions — czy nadal jesteś zainteresowany/a?"
        msg.attach(MIMEText(tresc, "plain"))

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(GMAIL_EMAIL, GMAIL_HASLO)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        st.error(f"Błąd wysyłki: {e}")
        return False


granica_czasu = (datetime.now() - timedelta(hours=24)).isoformat()

response = supabase.table("klienci").select("*").execute()
wszyscy = response.data or []

do_wyslania = [
    k for k in wszyscy
    if k.get("ostatnia_wizyta", "") < granica_czasu
    and not k.get("followup_wyslany", False)
]

if not do_wyslania:
    st.info("Brak klientów oczekujących na follow-up. Wszyscy albo odpowiedzieli, albo jeszcze nie minęło 24h.")
else:
    st.write(f"**{len(do_wyslania)}** klientów czeka na follow-up:")

    for klient in do_wyslania:
        with st.expander(f"👤 {klient.get('imie', 'Brak imienia')} — {klient.get('email', 'brak email')}"):
            st.write(f"**Telefon:** {klient.get('telefon', '—')}")
            st.write(f"**Zainteresowania:** {klient.get('zainteresowania', '—')}")
            st.write(f"**Ostatnia wizyta:** {klient.get('ostatnia_wizyta', '—')}")

            klucz_tresc = f"tresc_{klient['id']}"
            if klucz_tresc not in st.session_state:
                with st.spinner("Generuję treść maila..."):
                    st.session_state[klucz_tresc] = generuj_tresc_maila(
                        klient.get("imie", "Kliencie"),
                        klient.get("zainteresowania", "nasze usługi")
                    )

            tresc_edytowalna = st.text_area(
                "Treść maila (możesz edytować przed wysłaniem):",
                value=st.session_state[klucz_tresc],
                height=180,
                key=f"edit_{klient['id']}"
            )

            col1, col2 = st.columns([1, 4])
            with col1:
                if st.button("📤 Wyślij", key=f"wyslij_{klient['id']}", type="primary"):
                    sukces = wyslij_email_do_klienta(
                        klient.get("email"),
                        tresc_edytowalna,
                        klient.get("imie", "")
                    )
                    if sukces:
                        supabase.table("klienci").update({
                            "followup_wyslany": True,
                            "followup_data": datetime.now().isoformat()
                        }).eq("id", klient["id"]).execute()
                        st.success("Wysłano! Odśwież stronę żeby zaktualizować listę.")
