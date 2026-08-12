import os
import time
from groq import Groq
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

GROQ_API_KEY = os.environ["GROQ_API_KEY"]
GMAIL_EMAIL = os.environ["GMAIL_EMAIL"]
GMAIL_HASLO = os.environ["GMAIL_HASLO"]
FIRMA_NAZWA = os.environ["FIRMA_NAZWA"]

groq_client = Groq(api_key=GROQ_API_KEY)

# ====== FONT Z OBSŁUGĄ POLSKICH ZNAKÓW ======
FONT_NORMAL = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
try:
    sciezka_dejavu = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    sciezka_dejavu_bold = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    if os.path.exists(sciezka_dejavu):
        pdfmetrics.registerFont(TTFont("DejaVuSans", sciezka_dejavu))
        FONT_NORMAL = "DejaVuSans"
    if os.path.exists(sciezka_dejavu_bold):
        pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", sciezka_dejavu_bold))
        FONT_BOLD = "DejaVuSans-Bold"
except Exception as e:
    print(f"Nie udało się załadować fontu z polskimi znakami, używam domyślnego: {e}")


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
                return "Odpowiedź była zbyt obszerna do przetworzenia — spróbuj sprawdzić ten temat ręcznie."
            else:
                return f"Nie udało się sprawdzić tego tematu: {e}"
    return "Nie udało się uzyskać odpowiedzi po kilku próbach (limit zapytań)."


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


def wygeneruj_pdf(wyniki, sciezka_pliku):
    doc = SimpleDocTemplate(
        sciezka_pliku, pagesize=A4,
        topMargin=20 * mm, bottomMargin=20 * mm, leftMargin=20 * mm, rightMargin=20 * mm
    )
    styles = getSampleStyleSheet()

    styl_tytul = ParagraphStyle(
        "TytulPL", parent=styles["Title"], fontName=FONT_BOLD,
        fontSize=18, textColor=HexColor("#12294D"), spaceAfter=4
    )
    styl_podtytul = ParagraphStyle(
        "PodtytulPL", parent=styles["Normal"], fontName=FONT_NORMAL,
        fontSize=10, textColor=HexColor("#5C6B82"), spaceAfter=20
    )
    styl_naglowek_sekcji = ParagraphStyle(
        "NaglowekSekcjiPL", parent=styles["Heading2"], fontName=FONT_BOLD,
        fontSize=12, textColor=HexColor("#E8792C"), spaceBefore=16, spaceAfter=8
    )
    styl_tresc = ParagraphStyle(
        "TrescPL", parent=styles["Normal"], fontName=FONT_NORMAL,
        fontSize=10, leading=15, textColor=HexColor("#1A1A1A")
    )

    elementy = []
    elementy.append(Paragraph("Monitoring przepisów", styl_tytul))
    elementy.append(Paragraph(
        f"{FIRMA_NAZWA} &mdash; {datetime.now().strftime('%d.%m.%Y')}",
        styl_podtytul
    ))

    for temat, wynik in wyniki:
        elementy.append(Paragraph(temat, styl_naglowek_sekcji))
        tresc_html = wynik.replace("\n", "<br/>")
        elementy.append(Paragraph(tresc_html, styl_tresc))
        elementy.append(Spacer(1, 10))

    elementy.append(Spacer(1, 20))
    elementy.append(Paragraph(
        "Automatyczne sprawdzenie przez Spark &mdash; zawsze zweryfikuj istotne zmiany w oficjalnych źródłach.",
        ParagraphStyle("StopkaPL", parent=styl_tresc, fontSize=8, textColor=HexColor("#8A8A94"))
    ))

    doc.build(elementy)


def wyslij_podsumowanie(wyniki, sciezka_pdf):
    msg = MIMEMultipart()
    msg["From"] = GMAIL_EMAIL
    msg["To"] = GMAIL_EMAIL
    msg["Subject"] = f"⚖️ Monitoring przepisów — {FIRMA_NAZWA} — {datetime.now().strftime('%d.%m.%Y')}"

    tresc = f"Cotygodniowe sprawdzenie aktualności przepisów dla {FIRMA_NAZWA}.\n\nPełny raport w załączonym pliku PDF.\n\n"
    for temat, wynik in wyniki:
        tresc += f"{'='*50}\n{temat}\n{'='*50}\n{wynik}\n\n"

    msg.attach(MIMEText(tresc, "plain"))

    with open(sciezka_pdf, "rb") as f:
        zalacznik = MIMEApplication(f.read(), _subtype="pdf")
        nazwa_pliku = f"monitoring-przepisow-{datetime.now().strftime('%Y-%m-%d')}.pdf"
        zalacznik.add_header("Content-Disposition", "attachment", filename=nazwa_pliku)
        msg.attach(zalacznik)

    server = smtplib.SMTP("smtp.gmail.com", 587)
    server.starttls()
    server.login(GMAIL_EMAIL, GMAIL_HASLO)
    server.send_message(msg)
    server.quit()


if __name__ == "__main__":
    zapytania_bazowe = [
        "prawo budowlane, warunki techniczne budynków, Polska",
        "świadectwa charakterystyki energetycznej budynków, metodologia obliczeniowa, Polska",
    ]

    wyniki = []
    for zapytanie in zapytania_bazowe:
        nazwa_bazowa = "Przepisy budowlane (ogólne)" if "budowlane" in zapytanie else "Świadectwa charakterystyki energetycznej"

        print(f"Sprawdzam zmiany wsteczne: {nazwa_bazowa}...")
        wynik_wsteczny = sprawdz_temat(zapytanie)
        wyniki.append((f"{nazwa_bazowa} — co się już zmieniło", wynik_wsteczny))
        print(wynik_wsteczny)

        print("Czekam przed kolejnym zapytaniem...")
        time.sleep(20)

        print(f"Sprawdzam nadchodzące zmiany: {nazwa_bazowa}...")
        wynik_nadchodzacy = sprawdz_nadchodzace_zmiany(zapytanie)
        wyniki.append((f"{nazwa_bazowa} — co się szykuje", wynik_nadchodzacy))
        print(wynik_nadchodzacy)
        print()

        time.sleep(20)

    sciezka_pdf = "monitoring-przepisow.pdf"
    wygeneruj_pdf(wyniki, sciezka_pdf)
    print("PDF wygenerowany!")

    wyslij_podsumowanie(wyniki, sciezka_pdf)
    print("Podsumowanie z załącznikiem PDF wysłane mailem!")
