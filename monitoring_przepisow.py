import os
from groq import Groq
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

GROQ_API_KEY = os.environ["GROQ_API_KEY"]
GMAIL_EMAIL = os.environ["GMAIL_EMAIL"]
GMAIL_HASLO = os.environ["GMAIL_HASLO"]
FIRMA_NAZWA = os.environ["FIRMA_NAZWA"]

groq_client = Groq(api_key=GROQ_API_KEY)


def sprawdz_temat(zapytanie, opis):
    prompt = f"""Sprawdź w internecie, czy w ciągu ostatnich 30 dni pojawiły się w Polsce nowe lub zmienione przepisy dotyczące: {zapytanie}

Szukaj konkretnie: nowych rozporządzeń, nowelizacji ustaw, zmian w wymaganiach.
Jeśli nic istotnego się nie zmieniło, napisz wprost: "Brak istotnych zmian w ostatnim okresie."
Jeśli są zmiany, opisz je krótko w punktach, z podaniem daty/źródła jeśli to możliwe.
Odpowiadaj po polsku, maksymalnie 150 słów."""

    try:
        completion = groq_client.chat.completions.create(
            model="groq/compound-mini",
            messages=[{"role": "user", "content": prompt}]
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"⚠️ Nie udało się sprawdzić tego tematu: {e}"


def wyslij_podsumowanie(wyniki):
    msg = MIMEMultipart()
    msg["From"] = GMAIL_EMAIL
    msg["To"] = GMAIL_EMAIL
    msg["Subject"] = f"⚖️ Monitoring przepisów — {FIRMA_NAZWA} — {datetime.now().strftime('%d.%m.%Y')}"

    tresc = f"Cotygodniowe sprawdzenie aktualności przepisów dla {FIRMA_NAZWA}:\n\n"
    for temat, wynik in wyniki:
        tresc += f"{'='*50}\n{temat}\n{'='*50}\n{wynik}\n\n"
    tresc += "\n(Automatyczne sprawdzenie przez Spark — zawsze zweryfikuj istotne zmiany w oficjalnych źródłach.)"

    msg.attach(MIMEText(tresc, "plain"))

    server = smtplib.SMTP("smtp.gmail.com", 587)
    server.starttls()
    server.login(GMAIL_EMAIL, GMAIL_HASLO)
    server.send_message(msg)
    server.quit()


if __name__ == "__main__":
    tematy = [
        ("📐 Przepisy budowlane (ogólne)", "prawo budowlane, warunki techniczne budynków, Polska"),
        ("📄 Świadectwa charakterystyki energetycznej", "świadectwa charakterystyki energetycznej budynków, metodologia obliczeniowa, Polska"),
    ]

    wyniki = []
    for nazwa, zapytanie in tematy:
        print(f"Sprawdzam: {nazwa}...")
        wynik = sprawdz_temat(zapytanie, nazwa)
        wyniki.append((nazwa, wynik))
        print(wynik)
        print()

    wyslij_podsumowanie(wyniki)
    print("Podsumowanie wysłane mailem!")
