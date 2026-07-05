import streamlit as st
from groq import Groq
import requests
from bs4 import BeautifulSoup
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from supabase import create_client
import os

GROQ_KEY = st.secrets["GROQ_API_KEY"]
GMAIL_EMAIL = st.secrets["GMAIL_EMAIL"]
GMAIL_HASLO = st.secrets["GMAIL_HASLO"]
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
client = Groq(api_key=GROQ_KEY)

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
    try:
        r = requests.get(url, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        return soup.get_text(separator=" ", strip=True)[:5000]
    except:
        return ""

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
    except:
        pass

def wyslij_maila(imie, telefon, email_klienta, powrot=False):
    try:
        msg = MIMEMultipart()
        msg["From"] = GMAIL_EMAIL
        msg["To"] = GMAIL_EMAIL
        msg["Subject"] = "Powracajacy klient!" if powrot else "Nowy lead ze Sparka!"
        data = datetime.now().strftime("%Y-%m-%d %H:%M")
        linie = ["Klient:", "", "Imie: " + imie, "Telefon: " + telefon, "Email: " + email_klienta, "Data: " + data]
        msg.attach(MIMEText(chr(10).join(linie), "plain"))
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(GMAIL_EMAIL, GMAIL_HASLO)
        server.send_message(msg)
        server.quit()
    except:
        pass

wiedza = czytaj_strone("https://ps-pro.pl/")

SYSTEM_PROMPT = (
    "Jestes Spark, asystent firmy PS Pro Solutions. "
    "Odpowiadaj KROTKO — max 2-3 zdania. "
    "Firma zajmuje sie swiadectwami energetycznymi i audytami. "
    "ZAWSZE pros o dane: imie, telefon, email. "
    "Gdy klient poda imie I telefon I email napisz: KONTAKT|imie|telefon|email "
    "Wiedza: " + wiedza[:3000]
)

def czysta_historia(historia):
    return [{"role": m["role"], "content": m["content"]} for m in historia if "role" in m and "content" in m]

if "historia" not in st.session_state:
    st.session_state.historia = []
if "kontakt_zebrany" not in st.session_state:
    st.session_state.kontakt_zebrany = False

for msg in st.session_state.historia:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

if pytanie := st.chat_input("Napisz wiadomosc do Sparka..."):
    with st.chat_message("user"):
        st.write(pytanie)
    st.session_state.historia.append({"role": "user", "content": pytanie})

    with st.chat_message("assistant"):
        with st.spinner(""):
            odp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "system", "content": SYSTEM_PROMPT}] + czysta_historia(st.session_state.historia)
            )
            tekst = odp.choices[0].message.content

            if "KONTAKT|" in tekst and not st.session_state.kontakt_zebrany:
                czesci = tekst.split("|")
                if len(czesci) >= 4:
                    imie = czesci[1].strip()
                    telefon = czesci[2].strip()
                    email_k = czesci[3].strip().split()[0]
                    istniejacy = znajdz_klienta(email_k)
                    zapisz_klienta(imie, telefon, email_k, pytanie)
                    wyslij_maila(imie, telefon, email_k, istniejacy is not None)
                    st.session_state.kontakt_zebrany = True
                    if istniejacy:
                        tekst = "Witaj z powrotem " + imie + "! Jak moge pomoc?"
                    else:
                        tekst = "Dziekuje " + imie + "! Oddzwonimy wkrotce!"
                    st.success("Lead zapisany!")

            st.write(tekst)

    st.session_state.historia.append({"role": "assistant", "content": tekst})
