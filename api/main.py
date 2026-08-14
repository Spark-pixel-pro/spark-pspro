from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client
from groq import Groq
import cohere
import pandas as pd
import math
import os

app = FastAPI(title="Spark API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
COHERE_API_KEY = os.environ["COHERE_API_KEY"]
FIRMA_NAZWA = os.environ["FIRMA_NAZWA"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
groq_client = Groq(api_key=GROQ_API_KEY)
cohere_client = cohere.Client(COHERE_API_KEY)


def wyczysc_nan(obj):
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: wyczysc_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [wyczysc_nan(v) for v in obj]
    return obj


@app.get("/")
def root():
    return {"status": "Spark API działa"}


# ====== LOGOWANIE PRACOWNIKÓW ======
class DaneLogowania(BaseModel):
    email: str
    haslo: str


def zweryfikuj_pracownika(email: str, haslo: str):
    response = supabase.table("pracownicy").select("*").eq("email", email).execute()
    if not response.data:
        return None
    pracownik = response.data[0]
    if pracownik["haslo"] != haslo:
        return None
    return pracownik


@app.post("/login")
def login(dane: DaneLogowania):
    pracownik = zweryfikuj_pracownika(dane.email, dane.haslo)
    if not pracownik:
        raise HTTPException(status_code=403, detail="Nieprawidłowy email lub hasło")
    return {
        "imie": pracownik["imie"],
        "nazwisko": pracownik["nazwisko"],
        "email": pracownik["email"],
        "stanowisko": pracownik.get("stanowisko", "")
    }


# ====== STATYSTYKI (Dashboard) ======
@app.get("/stats")
def get_stats():
    response = supabase.table("klienci").select("*").execute()
    dane = response.data or []

    if not dane:
        return {
            "total_clients": 0, "total_visits": 0, "returning_clients": 0,
            "visits_by_day": [], "top_interests": [], "clients": []
        }

    df = pd.DataFrame(dane)
    df["ostatnia_wizyta"] = pd.to_datetime(df["ostatnia_wizyta"], errors="coerce")
    df["liczba_wizyt"] = pd.to_numeric(df["liczba_wizyt"], errors="coerce").fillna(1).astype(int)

    total_clients = len(df)
    total_visits = int(df["liczba_wizyt"].sum())
    returning_clients = int((df["liczba_wizyt"] > 1).sum())

    df_z_data = df.dropna(subset=["ostatnia_wizyta"])
    visits_by_day = []
    if not df_z_data.empty:
        grouped = df_z_data.groupby(df_z_data["ostatnia_wizyta"].dt.date).size()
        visits_by_day = [{"date": str(d), "visits": int(v)} for d, v in grouped.items()]

    interests = df["zainteresowania"].dropna()
    top_interests = []
    if not interests.empty:
        all_terms = interests.str.split(",").explode().str.strip()
        all_terms = all_terms[all_terms != ""]
        counts = all_terms.value_counts().head(10)
        top_interests = [{"term": t, "count": int(c)} for t, c in counts.items()]

    clients_list = df[["imie", "telefon", "email", "liczba_wizyt", "ostatnia_wizyta", "zainteresowania"]].copy()
    clients_list["ostatnia_wizyta"] = clients_list["ostatnia_wizyta"].astype(str)
    clients_list = clients_list.astype(object).where(pd.notnull(clients_list), None)
    clients_list = clients_list.sort_values("ostatnia_wizyta", ascending=False)

    wynik = {
        "total_clients": total_clients, "total_visits": total_visits,
        "returning_clients": returning_clients, "visits_by_day": visits_by_day,
        "top_interests": top_interests, "clients": clients_list.to_dict("records")
    }
    return wyczysc_nan(wynik)


# ====== ŚWIADECTWA ======
class DaneSwiadectwa(BaseModel):
    email: str
    haslo: str
    rodzaj: str
    przeznaczenie: str
    rok: int
    powierzchnia_af: float
    powierzchnia_uzytkowa: float
    eu: float
    ek: float
    ep: float
    ep_referencyjne: float
    co2: float
    uoze: float
    zrodlo_ogrzewanie: str
    zrodlo_cwu: str


def get_query_embedding(text):
    response = cohere_client.embed(
        texts=[text], model="embed-multilingual-v3.0", input_type="search_query"
    )
    return response.embeddings[0]


def znajdz_przyklady_stylu(zapytanie, match_count=3):
    try:
        wektor = get_query_embedding(zapytanie)
        response = supabase.rpc(
            "match_wiedza", {"query_embedding": wektor, "match_count": match_count}
        ).execute()
        fragmenty = response.data or []
        return "\n\n---\n\n".join([f["fragment"][:600] for f in fragmenty])
    except Exception:
        return ""


@app.post("/generate-certificate-description")
def generate_certificate_description(dane: DaneSwiadectwa):
    pracownik = zweryfikuj_pracownika(dane.email, dane.haslo)
    if not pracownik:
        raise HTTPException(status_code=403, detail="Nieprawidłowy email lub hasło")

    przyklady = znajdz_przyklady_stylu(f"opis świadectwa energetycznego {dane.rodzaj}")
    info_przyklady = f"\n\nPrzykłady stylu opisowego z wcześniejszych dokumentów firmy (wzoruj się na tonie, NIE kopiuj liczb):\n{przyklady}" if przyklady else ""

    prompt = f"""Jesteś asystentem firmy {FIRMA_NAZWA}, zajmującej się świadectwami charakterystyki energetycznej.

Na podstawie poniższych, JUŻ OBLICZONYCH przez audytora danych, napisz przystępne wyjaśnienie dla klienta — właściciela budynku — co te wskaźniki dla niego oznaczają w praktyce.

DANE BUDYNKU:
- Rodzaj: {dane.rodzaj}
- Przeznaczenie: {dane.przeznaczenie}
- Rok oddania do użytkowania: {dane.rok}
- Powierzchnia ogrzewana (Af): {dane.powierzchnia_af} m²
- Powierzchnia użytkowa: {dane.powierzchnia_uzytkowa} m²

WSKAŹNIKI (już obliczone przez audytora):
- Wskaźnik EU: {dane.eu} kWh/(m²·rok)
- Wskaźnik EK: {dane.ek} kWh/(m²·rok)
- Wskaźnik EP oceniany budynek: {dane.ep} kWh/(m²·rok)
- Wymagania dla nowego budynku (EP referencyjne): {dane.ep_referencyjne} kWh/(m²·rok)
- Emisja CO2: {dane.co2} t CO2/(m²·rok)
- Udział OZE (Uoze): {dane.uoze}%

ŹRÓDŁA ENERGII:
- Ogrzewanie: {dane.zrodlo_ogrzewanie}
- Ciepła woda użytkowa: {dane.zrodlo_cwu}

Zasady:
- Pisz po polsku, prostym, przystępnym językiem — klient NIE jest specjalistą
- Porównaj EP z EP referencyjnym i wyjaśnij czy to korzystny wynik
- NIE zmyślaj żadnych dodatkowych liczb
- Zakończ krótką, praktyczną wskazówką
- Długość: 150-200 słów{info_przyklady}"""

    completion = groq_client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[{"role": "user", "content": prompt}]
    )
    return {"opis": completion.choices[0].message.content}


# ====== ASYSTENT MALI DO KLIENTÓW ======
class DaneMaila(BaseModel):
    email: str
    haslo: str
    sytuacja: str
    wiadomosc_klienta: str = ""
    ton: str = "neutralny"


@app.post("/generate-client-email")
def generate_client_email(dane: DaneMaila):
    pracownik = zweryfikuj_pracownika(dane.email, dane.haslo)
    if not pracownik:
        raise HTTPException(status_code=403, detail="Nieprawidłowy email lub hasło")

    kontekst_wiedzy = znajdz_przyklady_stylu(dane.sytuacja, match_count=3)
    info_wiedza = f"\n\nKontekst z firmowej bazy wiedzy (fakty, procedury, cennik — użyj jeśli pasuje):\n{kontekst_wiedzy}" if kontekst_wiedzy else ""
    info_wiadomosc = f"\n\nOryginalna wiadomość od klienta, na którą odpowiadasz:\n\"{dane.wiadomosc_klienta}\"" if dane.wiadomosc_klienta else ""

    opisy_tonu = {
        "neutralny": "profesjonalny, uprzejmy",
        "cieply": "ciepły, przyjazny, ale wciąż profesjonalny",
        "formalny": "formalny, rzeczowy"
    }
    ton_opis = opisy_tonu.get(dane.ton, "profesjonalny, uprzejmy")

    prompt = f"""Jesteś asystentem firmy {FIRMA_NAZWA}. Napisz gotowy mail do klienta.

Sytuacja: {dane.sytuacja}{info_wiadomosc}{info_wiedza}

Zasady:
- Pisz po polsku, tonem: {ton_opis}
- Jeśli masz kontekst z bazy wiedzy (ceny, procedury, terminy) — wykorzystaj go, ale NIE zmyślaj faktów, których tam nie ma
- Jeśli nie masz pewnych informacji (np. dokładnej ceny), napisz to ogólnie i zasugeruj kontakt telefoniczny zamiast zmyślać liczby
- Struktura: krótkie powitanie, sedno sprawy, jasne zakończenie z następnym krokiem
- Długość: 80-150 słów
- Nie dodawaj tematu maila, tylko treść
- Podpisz jako "Zespół {FIRMA_NAZWA}\""""

    completion = groq_client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[{"role": "user", "content": prompt}]
    )
    return {"tresc": completion.choices[0].message.content}
import requests as http_requests

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_REPO = "Spark-pixel-pro/spark-pspro"
GITHUB_WORKFLOW = "monitoring_przepisow.yml"


class DaneLogowaniaSame(BaseModel):
    email: str
    haslo: str


@app.post("/trigger-przepisy-check")
def trigger_przepisy_check(dane: DaneLogowaniaSame):
    pracownik = zweryfikuj_pracownika(dane.email, dane.haslo)
    if not pracownik:
        raise HTTPException(status_code=403, detail="Nieprawidłowy email lub hasło")

    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/{GITHUB_WORKFLOW}/dispatches"
    response = http_requests.post(
        url,
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json"
        },
        json={"ref": "main"}
    )

    if response.status_code == 204:
        return {"status": "uruchomiono", "wiadomosc": "Sprawdzanie przepisów rozpoczęte. Pełny raport przyjdzie mailem za kilka minut."}
    else:
        raise HTTPException(status_code=500, detail=f"Nie udało się uruchomić sprawdzania: {response.status_code} {response.text}")
@app.get("/przepisy-raporty")
def get_przepisy_raporty():
    response = supabase.table("raporty_przepisow").select("*").order("data_utworzenia", desc=True).limit(10).execute()
    dane = response.data or []
    return {"raporty": dane}
