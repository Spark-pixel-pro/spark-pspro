import streamlit as st
from supabase import create_client
import pandas as pd

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
FIRMA_NAZWA = st.secrets["FIRMA_NAZWA"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

st.set_page_config(page_title="Spark - Dashboard", layout="wide")

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
    [data-testid="stMetricValue"] { color: #FFD600 !important; }
    [data-testid="stMetricLabel"] { color: #cccccc !important; }
    [data-testid="stDataFrame"] { background-color: #1a1a1a; }
</style>
""", unsafe_allow_html=True)

st.title("📊 Dashboard Sparka")
st.caption(f"Podgląd wszystkich klientów i rozmów zapisanych w bazie — {FIRMA_NAZWA}")

response = supabase.table("klienci").select("*").execute()
data = response.data

if not data:
    st.info("Baza jest jeszcze pusta — nikt nie rozmawiał ze Sparkiem od strony zapisu do bazy.")
else:
    df = pd.DataFrame(data)
    df["ostatnia_wizyta"] = pd.to_datetime(df["ostatnia_wizyta"])
    total_clients = len(df)
    total_visits = int(df["liczba_wizyt"].sum())
    returning = int((df["liczba_wizyt"] > 1).sum())

    col1, col2, col3 = st.columns(3)
    col1.metric("Liczba klientów", total_clients)
    col2.metric("Suma wizyt", total_visits)
    col3.metric("Powracający klienci", returning)

    st.subheader("Wizyty w czasie")
    df_by_day = df.groupby(df["ostatnia_wizyta"].dt.date).size()
    st.bar_chart(df_by_day)

    st.subheader("Najczęstsze zainteresowania klientów")
    interests = df["zainteresowania"].dropna()
    if not interests.empty:
        all_terms = interests.str.split(",").explode().str.strip()
        all_terms = all_terms[all_terms != ""]
        counts = all_terms.value_counts().head(10)
        if not counts.empty:
            st.bar_chart(counts)
        else:
            st.write("Brak jeszcze zapisanych zainteresowań.")
    else:
        st.write("Brak jeszcze zapisanych zainteresowań.")

    st.subheader("Lista wszystkich klientów")
    df_show = df[["imie", "telefon", "email", "liczba_wizyt", "ostatnia_wizyta", "zainteresowania"]].copy()
    df_show = df_show.sort_values("ostatnia_wizyta", ascending=False)
    df_show.columns = ["Imię", "Telefon", "Email", "Liczba wizyt", "Ostatnia wizyta", "Zainteresowania"]
    st.dataframe(df_show, use_container_width=True, hide_index=True)
