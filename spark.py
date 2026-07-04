
import streamlit as st
from groq import Groq
import requests
from bs4 import BeautifulSoup
import PyPDF2
import smtplib
import json
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

GROQ_KEY = st.secrets["GROQ_API_KEY"]
GMAIL_EMAIL = st.secrets["GMAIL_EMAIL"]
GMAIL_HASLO = st.secrets["GMAIL_HASLO"]

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

def wyslij_maila(imie, telefon, email_klienta):
    try:
        msg = MIMEMultipart()
        msg["From"] = GMAIL_EMAIL
        msg["To"] = GMAIL_EMAIL
        msg["Subject"] = "Nowy lead ze Sparka!"
        data = datetime.now().strftime("%Y-%m-%d %H:%M")
        linie = ["Nowy klient!", "", "Imie: " + imie, "Telefon: " + telefon, "Email: " + email_klienta, "Data: " + data, "", "Skontaktuj sie!"]
        tresc = chr(10).join(linie)
        msg.attach(MIMEText(tresc, "plain"))
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(GMAIL_EMAIL, GMAIL_HASLO)
        server.send_message(msg)
        server.quit()
    except:
        pass

def zapisz_kontakt(dane):
    plik = "kontakty.json"
    kontakty = []
    if os.path.exists(plik):
        with open(plik, "r") as f:
            kontakty = json.load(f)
    kontakty.append(dane)
    with open(plik, "w") as f:
        json.dump(kontakty, f, ensure_ascii=False, indent=2)

client = Groq(api_key=GROQ_KEY)
wiedza = czytaj_strone("https://ps-pro.pl/")

def czysta_historia(historia):
    return [{"role": m["role"], "content": m["content"]} for m in historia]

def spark_central(pytanie, historia):
    routing = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": "Odpowiedz TYLKO jednym slowem: SPRZEDAZ, WIEDZA, HR lub OGOLNE"},
            {"role": "user", "content": pytanie}
        ]
    ).choices[0].message.content.strip().upper()

    if "SPRZEDAZ" in routing:
        system = ("Jestes Agent Sprzedazy PS Pro Solutions. "
                  "Twoj cel to zebranie danych kontaktowych. "
                  "Schemat: 1) Krotko odpowiedz 2) Zapytaj o imie telefon i email "
                  "3) Gdy klient poda dane napisz: KONTAKT|imie|telefon|email "
                  "Wiedza: " + wiedza[:3000])
    elif "HR" in routing:
        system = "Jestes Agent HR PS Pro Solutions. Znasz procedury i rekrutacje."
    else:
        system = "Jestes Agent Wiedzy PS Pro Solutions. Wyjasniasz uslugi firmy. Wiedza: " + wiedza[3000:6000]

    return client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "system", "content": system}] + czysta_historia(historia) + [{"role": "user", "content": pytanie}]
    ).choices[0].message.content

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
            tekst = spark_central(pytanie, st.session_state.historia)
            if "KONTAKT|" in tekst and not st.session_state.kontakt_zebrany:
                czesci = tekst.split("|")
                if len(czesci) >= 4:
                    imie = czesci[1]
                    telefon = czesci[2]
                    email_k = czesci[3].split()[0]
                    wyslij_maila(imie, telefon, email_k)
                    zapisz_kontakt({"imie": imie, "telefon": telefon, "email": email_k, "data": datetime.now().strftime("%Y-%m-%d %H:%M")})
                    st.session_state.kontakt_zebrany = True
                    tekst = "Dziekuje! Zapisalem Twoje dane. Nasz zespol skontaktuje sie wkrotce!"
                    st.success("Lead zapisany!")
            st.write(tekst)
    st.session_state.historia.append({"role": "assistant", "content": tekst})
