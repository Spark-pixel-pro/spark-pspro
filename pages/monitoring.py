import os
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

GMAIL_EMAIL = os.environ["GMAIL_EMAIL"]
GMAIL_HASLO = os.environ["GMAIL_HASLO"]
FIRMA_NAZWA = os.environ["FIRMA_NAZWA"]

STREAMLIT_URL = os.environ["STREAMLIT_URL"]
EDGE_FUNCTION_URL = os.environ["EDGE_FUNCTION_URL"]
SUPABASE_ANON_KEY = os.environ["SUPABASE_ANON_KEY"]


def sprawdz_streamlit():
    try:
        response = requests.get(STREAMLIT_URL, timeout=15)
        if response.status_code == 200:
            return True, "OK"
        else:
            return False, f"Kod odpowiedzi: {response.status_code}"
    except Exception as e:
        return False, str(e)


def sprawdz_edge_function():
    try:
        response = requests.post(
            EDGE_FUNCTION_URL,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
                "apikey": SUPABASE_ANON_KEY
            },
            json={"wiadomosc": "test monitoringu", "tryb": "klient", "historia": []},
            timeout=20
        )
        if response.status_code == 200 and "odpowiedz" in response.json():
            return True, "OK"
        else:
            return False, f"Kod odpowiedzi: {response.status_code}, treść: {response.text[:200]}"
    except Exception as e:
        return False, str(e)


def wyslij_alert(problemy):
    msg = MIMEMultipart()
    msg["From"] = GMAIL_EMAIL
    msg["To"] = GMAIL_EMAIL
    msg["Subject"] = f"🚨 ALERT: Problem ze Sparkiem — {FIRMA_NAZWA}"

    tresc = f"Wykryto problem z systemem Spark dla {FIRMA_NAZWA}:\n\n"
    for nazwa, szczegoly in problemy:
        tresc += f"❌ {nazwa}: {szczegoly}\n"
    tresc += "\nSprawdź appkę jak najszybciej."

    msg.attach(MIMEText(tresc, "plain"))

    server = smtplib.SMTP("smtp.gmail.com", 587)
    server.starttls()
    server.login(GMAIL_EMAIL, GMAIL_HASLO)
    server.send_message(msg)
    server.quit()


if __name__ == "__main__":
    problemy = []

    ok_streamlit, szczegoly_streamlit = sprawdz_streamlit()
    if not ok_streamlit:
        problemy.append(("Aplikacja Streamlit", szczegoly_streamlit))
    else:
        print("✅ Streamlit działa poprawnie")

    ok_edge, szczegoly_edge = sprawdz_edge_function()
    if not ok_edge:
        problemy.append(("Edge Function (spark-brain)", szczegoly_edge))
    else:
        print("✅ Edge Function działa poprawnie")

    if problemy:
        print(f"⚠️ Wykryto {len(problemy)} problem(ów) — wysyłam alert...")
        wyslij_alert(problemy)
        print("Alert wysłany.")
    else:
        print("Wszystko działa poprawnie — brak alertu.")
