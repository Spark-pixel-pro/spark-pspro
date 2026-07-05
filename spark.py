
import streamlit as st
from groq import Groq
import requests
from bs4 import BeautifulSoup
import smtplib
import json
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from supabase import create_client

GROQ_KEY = st.secrets["GROQ_API_KEY"]
GMAIL_EMAIL = st.secrets["GMAIL_EMAIL"]
GMAIL_HASLO = st.secrets["GMAIL_HASLO"]
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

st.set_page_config(page_title="Spark - PS Pro Solutions", layout="centered")

st.markdown("""
<style>
    .stApp { background-color: #111111; }
    .header-wrap { display: flex; align-items: center; gap: 16px; padding: 1.5rem 0 0.5rem 0; }
    .header-logo img { height: 56px; filter: brightness(0) invert(1); }
    .header-text .title { font-size: 1.6rem; font-weight: 800; color: #FFD600; letter-spacing: 2px; }
    .header-text .subtitle { font-size: 0.8rem; color: #888888; letter-spacing: 1px; }
    .divider { border: none; border-top: 1px solid #FFD600; opacity: 0.25; margin: 0.8rem 0 1.5rem 0; }
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"] {
        background-color: #FFD600 !important; color: #111111 !important; font-weight: 600;
        border-radius: 16px 16px 4px 16px; padding: 0.75rem 1rem; }
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) [data-testid="stChatMessageContent"] {
        background-color: #1C1C1C !important; color: #FFFFFF !important;
        border: 1px solid #2A2A2A; border-radius: 16px 16px 16px 4px; padding: 0.75rem 1rem; }
    .stChatInputContainer { background-color: #1C1C1C !important; border: 1.5px solid #FFD600 !important; border-radius: 14px !important; }
    .stChatInputContainer textarea { color: #FFFFFF !important; background-color: transparent !important; }
    #MainMenu, header, footer { visibility: hidden; }
    .block-container { padding-top: 0 !important; }
</style>
<div class="header-wrap">
    <div class="header-logo"><img src="https://ps-pro.pl/images/logo.svg" alt="PS PRO"></div>
    <div class="header-text">
        <div class="title">SPARK</div>
        <div class="subtitle">ASYSTENT PS PRO SOLUTIONS</div>
    </div>
</div>
<hr class="divider">
""", unsafe_allow_html=True)

@st.cache_data
def czytaj_strone(url):
    r = requests.get(url)
    soup = BeautifulSoup(r.text, "html.parser")
    return soup.get_text(separator=" ", strip=True)[:6000]

def znajdz_klienta(email):
    try:
        wynik = supabase.table("klienci").select("*").eq("email", email).execute()
        if wynik.data:
            return wynik.data[0]
    except:
        pass
    return None

def zapisz_klienta(imie, telefon, email, temat):
    try:
        istniejacy = znajdz_klienta(email)
        if istniejacy:
            supabase.table("klienci").update({
                "ostatnia_wizyta": datetime.now().isoformat(),
                "liczba_wizyt": istniejacy["liczba_wizyt"] + 1,
                "zainteresowania": temat
            }).eq("email", email).execute()
        else:
            supabase.table("klienci").insert({
                "imie": imie,
                "telefon": telefon,
                "email": email,
                "zainteresowania": temat,
                "historia": "Pierwsza wizyta"
            }).execute()
    except Exception as e:
        st.error("Blad bazy: " + str(e))

def wyslij_maila(imie, telefon, email_klienta, powrot=False):
    try:
        msg = MIMEMultipart()
        msg["From"] = GMAIL_EMAIL
        msg["To"] = GMAIL_EMAIL
        if powrot:
            msg["Subject"] = "Powracajacy klient ze Sparka!"
        else:
            msg["Subject"] = "Nowy lead ze Sparka!"
        data = datetime.now().strftime("%Y-%m-%d %H:%M")
        linie = ["Klient:", "", "Imie: " + imie, "Telefon: " + telefon, "Email: " + email_klienta, "Data: " + data, "", "Skontaktuj sie!"]
        tresc = chr(10).join(linie)
        msg.attach(MIMEText(tresc, "plain"))
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(GMAIL_EMAIL, GMAIL_HASLO)
        server.send_message(msg)
        server.quit()
        return True
    except:
        return False

client = Groq(api_key=GROQ_KEY)
wiedza = czytaj_strone("https://ps-pro.pl/")

SYSTEM_PROMPT = (
    "Jestes Spark, asystent firmy PS Pro Solutions. "
    "Firma zajmuje sie swiadectwami energetycznymi, audytami i dokumentacja budowlana. "
    "NAJWAZNIEJSZA ZASADA: W kazdej odpowiedzi ZAWSZE prosic o dane kontaktowe: imie, telefon, email. "
    "Gdy uzytkownik poda imie I telefon I email napisz: KONTAKT|imie|telefon|email "
    "Wiedza o firmie: " + wiedza[:4000]
)

def czysta_historia(historia):
    return [{"role": m["role"], "content": m["content"]} for m in historia]

if "historia" not in st.session_state:
    st.session_state.historia = []
if "kontakt_zebrany" not in st.session_state:
    st.session_state.kontakt_zebrany = False
if "klient_info" not in st.session_state:
    st.session_state.klient_info = None

for msg in st.session_state.historia:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

if pytanie := st.chat_input("Napisz wiadomosc do Sparka..."):
    with st.chat_message("user"):
        st.write(pytanie)
    st.session_state.historia.append({"role": "user", "content": pytanie})

    with st.chat_message("assistant"):
        with st.spinner(""):
            odpowiedz = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "system", "content": SYSTEM_PROMPT}] + czysta_historia(st.session_state.historia)
            )
            tekst = odpowiedz.choices[0].message.content

            if "KONTAKT|" in tekst and not st.session_state.kontakt_zebrany:
                czesci = tekst.split("|")
                if len(czesci) >= 4:
                    imie = czesci[1].strip()
                    telefon = czesci[2].strip()
                    email_k = czesci[3].strip().split()[0]

                    istniejacy = znajdz_klienta(email_k)
                    powrot = istniejacy is not None

                    zapisz_klienta(imie, telefon, email_k, pytanie)
                    wyslij_maila(imie, telefon, email_k, powrot)
                    st.session_state.kontakt_zebrany = True
                    st.session_state.klient_info = istniejacy

                    if powrot:
                        wizyty = istniejacy["liczba_wizyt"] + 1
                        tekst = "Witaj z powrotem " + imie + "! To juz Twoja " + str(wizyty) + ". wizyta. Pamietam Cie! Jak moge pomoc tym razem?"
                        st.info("Powracajacy klient!")
                    else:
                        tekst = "Dziekuje " + imie + "! Zapisalem Twoje dane. Nasz zespol skontaktuje sie wkrotce!"
                        st.success("Nowy lead zapisany!")

            st.write(tekst)

    st.session_state.historia.append({"role": "assistant", "content": tekst})
