import os
import time
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


def zapytaj_z_ponowieniem(prompt, max_prob=3):
    for proba in range(max_prob):
        try:
            completion = groq_client.chat.completions.create(
                model="groq/compound-mini",
                messages=[{"role": "user", "content": prompt}]
            )
            return completion.choices[0].message.content
        except Exception as e:
            tekst_bledu = str(e)
            if "429" in tekst_bledu:
                czas_oczekiwania = 35
                print(f"Limit zapytań osiągnięty, czekam {czas_oczekiwania}s (próba {proba + 1}/{max_prob})...")
                time.sleep(czas_oczekiwania)
            elif "413" in tekst_bledu:
                return "⚠️ Odpowiedź była zbyt obszerna do przetworzenia — spróbuj sprawdzić ten temat ręcznie."
            else:
                return f"⚠️ Nie udało się sprawdzić tego tematu: {e}"
    return "⚠️ Nie udało się uzyskać odpowiedzi po kilku próbach (limit zapytań)."


def sprawdz_temat(zapytanie):
    prompt = f"""Sprawdź w internecie, czy w ciągu ostatnich 30 dni pojawiły się w Polsce nowe lub zmienione przepisy dotyczące: {zapytanie}

Szukaj konkretnie: nowych rozporządzeń, nowelizacji ustaw, zmian w wymaganiach.
Jeśli nic istotnego się nie zmieniło, napisz wprost: "Brak istotnych zmian w ostatnim okresie."
Jeśli są zmiany, opisz je krótko w punktach, z podaniem daty/źródła jeśli to możliwe.
Odpowiadaj po polsku, maksymalnie 120 słów."""
    return zapytaj_z_ponowieniem(prompt)


def sprawdz_nadchodzace_zmiany(zapytanie):
    prompt = f"""Sprawdź w internecie, czy w Polsce są obecnie w toku prac legislacyjnych (projekty ustaw, projekty rozporządzeń, konsultacje publiczne, zapowiedziane nowelizacje) dotyczące: {zapytanie}

Szukaj konkretnie: projektów aktów prawnych będących w konsultacjach, zapowiedzi Ministerstwa, planowanych terminów wejścia w życie.
Jeśli nic nie jest obecnie planowane, napisz wprost: "Brak zapowiedzianych zmian na horyzoncie."
Jeśli coś się szykuje, opisz krótko w punktach: czego dotyczy, na jakim jest etapie, przewidywany termin.
Odpowiadaj po polsku, maksymalnie 120 słów."""
    return zapytaj_z_ponowieniem(prompt)


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
        print(f"Sprawdzam zmiany wsteczne: {nazwa}...")
        wynik_wsteczny = sprawdz_temat(zapytanie)
        wyniki.append((f"{nazwa} — CO SIĘ JUŻ ZMIENIŁO", wynik_wsteczny))
        print(wynik_wsteczny)

        print("Czekam przed kolejnym zapytaniem...")
        time.sleep(20)

        print(f"Sprawdzam nadchodzące zmiany: {nazwa}...")
        wynik_nadchodzacy = sprawdz_nadchodzace_zmiany(zapytanie)
        wyniki.append((f"{nazwa} — CO SIĘ SZYKUJE", wynik_nadchodzacy))
        print(wynik_nadchodzacy)
        print()

        time.sleep(20)

    wyslij_podsumowanie(wyniki)
    print("Podsumowanie wysłane mailem!")
