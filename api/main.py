from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client
import pandas as pd
import os

app = FastAPI(title="Spark API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


@app.get("/")
def root():
    return {"status": "Spark API działa"}


@app.get("/stats")
def get_stats():
    response = supabase.table("klienci").select("*").execute()
    dane = response.data or []

    if not dane:
        return {
            "total_clients": 0,
            "total_visits": 0,
            "returning_clients": 0,
            "visits_by_day": [],
            "top_interests": [],
            "clients": []
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
    clients_list = clients_list.where(pd.notnull(clients_list), None)
    clients_list = clients_list.sort_values("ostatnia_wizyta", ascending=False)

    return {
        "total_clients": total_clients,
        "total_visits": total_visits,
        "returning_clients": returning_clients,
        "visits_by_day": visits_by_day,
        "top_interests": top_interests,
        "clients": clients_list.to_dict("records")
    }
