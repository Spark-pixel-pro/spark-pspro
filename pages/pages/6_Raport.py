import streamlit as st
from supabase import create_client
from groq import Groq
import pandas as pd
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
GROQ_API_KEY = st.secrets["GROQ_API_KEY"]
GMAIL_EMAIL = st.secrets["GMAIL_EMAIL"]
GMAIL_HASLO = st.secrets["GMAIL_HASLO"]
FIRMA_NAZWA = st.secrets["FIRMA_NAZWA"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
groq_client = Groq(api_key=GROQ_API_KEY)

st.set_page_config(page_title="Spark - Raport tygodniowy", layout="wide")

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
</style>
""", unsafe_allow_html=True)

st.title("📊 Raport tygodniowy")
st.caption(f"Podsumowanie aktywności Sparka dla {FIRMA_NAZWA} — do wysyłki mailem")


def zbierz_statystyki():
    granica = (datetime.now() - timedelta(days=7)).isoformat()

    response = supabase.table("klienci").select("*").execute()
    wszyscy = response.data or []

    df = pd.DataFrame(wszyscy)
    if df.empty:
        return None

    df["ostatnia_wizyta"] = pd.to_datetime(df["ostatnia_wizyta"], errors="coerce")
    granica_dt = pd.to_datetime(granica)

    nowi_w_tygodniu = df[df["ostatnia_wizyta"] >= granica_dt]

    zainteresowania = df["zainteresowania"].dropna()
    top_tematy = []
    if not zainteresowania.empty:
        all_terms = zainteresowania.str.split(",").explode().str.strip()
        all_terms = all_terms[all_terms != ""]
        top_tematy = all_terms.value_counts().head(5).index.tolist()

    return {
        "laczna_liczba_klientow": len(df),
        "nowi_w_tygodniu": len(nowi_w_tygodniu),
        "suma_wizyt": int(df["liczba_wizyt"].sum()),
        "top_tematy": top_tematy,
        "lista_nowych": nowi_w_tygodniu[["imie", "email", "zainteresowania"]].to_dict("records") if not nowi_w_tygodniu.empty else []
    }


def generuj_tresc_raportu(statystyki):
    tematy_tekst = ", ".join(statystyki["top_tematy"]) if statystyki["top_tematy"] else "brak danych"

    prompt = f"""Napisz krótki, przyjazny raport tygodniowy dla właściciela firmy {FIRMA_NAZWA} o aktywności asystenta AI Spark.

Dane z ostatnich 7 dni:
- Nowi klienci w tym tygodniu: {statystyki['nowi_w_tygodniu']}
- Łączna liczba klientów w bazie: {statystyki['laczna_liczba_klientow']}
- Suma wszystkich wizyt: {statystyki['suma_wizyt']}
- Najczęstsze tematy rozmów: {tematy_tekst}

Napisz to jako krótki, konkretny mail — 4-6 zdań, ciepły ale rzeczowy ton, po polsku. Nie zmyślaj dodatkowych danych poza podanymi. Podpisz jako "Spark — Twój asystent AI"."""

    completion = groq_client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[{"role": "user", "content": prompt}]
    )
    return completion.choices[0].message.content


def wyslij_raport_mailem(tresc, statystyki):
    try:
        msg = MIMEMultipart()
        msg["From"] = GMAIL_EMAIL
        msg["To"] = GMAIL_EMAIL
        msg["Subject"] = f"📊 Raport tygodniowy Sparka — {FIRMA_NAZWA}"

        lista_nowych_tekst = ""
        if statystyki["lista_nowych"]:
            lista_nowych_tekst = "\n\nNowi klienci w tym tygodniu:\n"
            for k in statystyki["lista_nowych"]:
                lista_nowych_tekst += f"- {k.get('imie', '—')} ({k.get('email', '—')}) — {k.get('zainteresowania', '—')}\n"

        pelna_tresc = tresc + lista_nowych_tekst

        msg.attach(MIMEText(pelna_tresc, "plain"))

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(GMAIL_EMAIL, GMAIL_HASLO)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        st.error(f"Błąd wysyłki: {e}")
        return False


statystyki = zbierz_statystyki()

if statystyki is None:
    st.info("Baza jest jeszcze pusta — brak danych do raportu.")
else:
    col1, col2, col3 = st.columns(3)
    col1.metric("Nowi klienci (7 dni)", statystyki["nowi_w_tygodniu"])
    col2.metric("Łącznie klientów", statystyki["laczna_liczba_klientow"])
    col3.metric("Suma wizyt", statystyki["suma_wizyt"])

    if statystyki["top_tematy"]:
        st.write("**Najczęstsze tematy:** " + ", ".join(statystyki["top_tematy"]))

    if st.button("✨ Wygeneruj treść raportu", type="primary"):
        with st.spinner("Piszę raport..."):
            tresc = generuj_tresc_raportu(statystyki)
            st.session_state["tresc_raportu"] = tresc

    if "tresc_raportu" in st.session_state:
        st.divider()
        edytowalna_tresc = st.text_area(
            "Treść raportu (możesz edytować):",
            value=st.session_state["tresc_raportu"],
            height=200
        )
        if st.button("📤 Wyślij raport mailem"):
            sukces = wyslij_raport_mailem(edytowalna_tresc, statystyki)
            if sukces:
                st.success("Raport wysłany!")
