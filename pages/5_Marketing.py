import streamlit as st
from supabase import create_client
import cohere
from groq import Groq
import requests
from bs4 import BeautifulSoup
import re
import json
from datetime import datetime

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
GROQ_API_KEY = st.secrets["GROQ_API_KEY"]
COHERE_API_KEY = st.secrets["COHERE_API_KEY"]
STABILITY_API_KEY = st.secrets["STABILITY_API_KEY"]
FIRMA_NAZWA = st.secrets["FIRMA_NAZWA"]
FIRMA_STRONA = st.secrets["FIRMA_STRONA"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
groq_client = Groq(api_key=GROQ_API_KEY)
cohere_client = cohere.Client(COHERE_API_KEY)

STORAGE_BUCKET = "marketing-obrazy"

st.set_page_config(page_title="Spark - Marketing", layout="wide")

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
    .stTextArea textarea { background-color: #1a1a1a; color: #f0f0f0; }
</style>
""", unsafe_allow_html=True)

st.title("📢 Generator treści marketingowych")
st.caption(f"Twórz posty, obrazy, planuj kalendarz i baw się treścią dla {FIRMA_NAZWA}")


# ====== FUNKCJE POMOCNICZE ======

def ma_obraz(plan):
    url = plan.get("obraz_url")
    return bool(url and url.strip())


def get_query_embedding(text):
    response = cohere_client.embed(
        texts=[text],
        model="embed-multilingual-v3.0",
        input_type="search_query"
    )
    return response.embeddings[0]


def znajdz_kontekst_firmy(temat, match_count=4):
    try:
        wektor = get_query_embedding(temat)
        response = supabase.rpc(
            "match_wiedza",
            {"query_embedding": wektor, "match_count": match_count}
        ).execute()
        fragmenty = response.data or []
        if not fragmenty:
            return ""
        return "\n\n".join([f["fragment"][:500] for f in fragmenty])
    except Exception:
        return ""


@st.cache_data(ttl=3600)
def czytaj_blog_firmy(url):
    try:
        r = requests.get(url, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        return soup.get_text(separator=" ", strip=True)[:4000]
    except Exception:
        return ""


def research_w_internecie(temat, platforma):
    prompt = f"""Wyszukaj aktualne, praktyczne informacje przydatne do napisania posta marketingowego na {platforma} na temat: {temat}

Szukaj: aktualnych trendów, dobrych praktyk dla tego typu treści, ewentualnie ciekawych faktów lub statystyk związanych z tematem.
Odpowiedz krótko, w punktach, po polsku. Maksymalnie 5-6 punktów."""

    try:
        completion = groq_client.chat.completions.create(
            model="groq/compound-mini",
            messages=[{"role": "user", "content": prompt}]
        )
        return completion.choices[0].message.content
    except Exception as e:
        st.warning(f"⚠️ Nie udało się pobrać danych z internetu (spróbuj ponownie za chwilę): {e}")
        return ""


def pobierz_wzorzec_stylu(platforma):
    try:
        response = supabase.table("wzorce_stylu").select("przyklad").eq("platforma", platforma).execute()
        if response.data:
            return response.data[0]["przyklad"]
        return ""
    except Exception:
        return ""


def zapisz_wzorzec_stylu(platforma, przyklad):
    supabase.table("wzorce_stylu").upsert({
        "platforma": platforma,
        "przyklad": przyklad,
        "updated_at": datetime.now().isoformat()
    }).execute()


def generuj_tresc(temat, platforma, kontekst_firmy, kontekst_internet, kontekst_blog, wzorzec_stylu):
    opisy_platform = {
        "Facebook": "dłuższy post na Facebook, ciepły i konwersacyjny ton, może zawierać pytanie na końcu angażujące czytelników, 3-6 zdań",
        "Instagram": "krótki, chwytliwy post na Instagram, energiczny ton, można użyć emoji, max 3-4 zdania, zakończ 3-5 trafnymi hashtagami",
        "Blog": "dłuższy, wartościowy fragment artykułu na bloga, przystępny ton bez żargonu, 150-250 słów"
    }

    info_firma = f"\n\nKontekst o firmie (baza wiedzy):\n{kontekst_firmy}" if kontekst_firmy else ""
    info_internet = f"\n\nAktualne informacje/inspiracje z internetu:\n{kontekst_internet}" if kontekst_internet else ""
    info_blog = f"\n\nTreść ze strony/bloga firmy (dla kontekstu i stylu):\n{kontekst_blog}" if kontekst_blog else ""
    info_wzorzec = f"\n\nPrzykład wcześniejszego posta tej firmy na {platforma} — naśladuj JEGO STYL I TON (nie kopiuj treści):\n{wzorzec_stylu}" if wzorzec_stylu else ""

    prompt = f"""Jesteś asystentem marketingowym firmy {FIRMA_NAZWA}.

Napisz {opisy_platform[platforma]} na temat: {temat}

Zasady:
- Pisz po polsku, przystępnym językiem, bez żargonu technicznego
- Ton: profesjonalny, ale ciepły i ludzki, nie korporacyjny
- Nie zmyślaj konkretnych liczb ani faktów, których nie ma w podanym kontekście
- Nie używaj nazwy firmy nachalnie więcej niż raz-dwa razy{info_firma}{info_internet}{info_blog}{info_wzorzec}"""

    completion = groq_client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[{"role": "user", "content": prompt}]
    )
    return completion.choices[0].message.content


def generuj_pomysly_kalendarza(liczba_pomyslow, kontekst_firmy, kontekst_blog):
    info_firma = f"\n\nKontekst o firmie:\n{kontekst_firmy}" if kontekst_firmy else ""
    info_blog = f"\n\nTreść ze strony firmy:\n{kontekst_blog}" if kontekst_blog else ""

    prompt = f"""Jesteś asystentem marketingowym firmy {FIRMA_NAZWA}.

Wygeneruj {liczba_pomyslow} pomysłów na treści marketingowe na najbliższe tygodnie.

Dla każdego pomysłu podaj:
- temat (krótki, konkretny)
- platforma (Facebook, Instagram lub Blog)
- sugerowany_termin (np. "poniedziałek, tydzień 1" - bazuj na ogólnych dobrych praktykach: B2B lepiej działa w dni robocze rano, Instagram wieczorem itp.)
- uzasadnienie (1 zdanie, czemu ten temat/termin ma sens){info_firma}{info_blog}

Odpowiedz WYŁĄCZNIE poprawnym JSON-em, jako lista obiektów z kluczami: temat, platforma, sugerowany_termin, uzasadnienie. Bez żadnego dodatkowego tekstu przed ani po."""

    completion = groq_client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[{"role": "user", "content": prompt}]
    )
    tekst = completion.choices[0].message.content.strip()

    tekst = re.sub(r"^```json\s*", "", tekst)
    tekst = re.sub(r"^```\s*", "", tekst)
    tekst = re.sub(r"\s*```$", "", tekst)

    try:
        return json.loads(tekst)
    except Exception:
        return []


def generuj_prompt_obrazu(temat, platforma, kontekst_firmy=""):
    info_kontekst = f"\n\nKontekst o branży/usługach firmy:\n{kontekst_firmy}" if kontekst_firmy else ""

    prompt = f"""Na podstawie tego tematu posta marketingowego: "{temat}" (platforma: {platforma}, firma: {FIRMA_NAZWA}){info_kontekst}

Napisz KRÓTKI, konkretny prompt PO ANGIELSKU do generatora obrazów AI, opisujący zdjęcie ŚCIŚLE związane z konkretnym tematem posta.

Zasady:
- UNIKAJ pokazywania ludzi (zwłaszcza "businessman at laptop", "person in office") — to zbyt generyczne
- Zamiast tego pokaż KONKRETNE przedmioty, sceny lub symbole bezpośrednio związane z tematem (np. dla tematu o dofinansowaniach na energię odnawialną: panele słoneczne na dachu, dokumenty z wykresami energii, dom z pompą ciepła)
- Dodaj do sceny subtelny akcent w kolorze żółtym (#FFD600) — np. detal, oświetlenie, element dekoracyjny — jako nawiązanie do barw firmy
- Styl: profesjonalna fotografia, naturalne światło, czysta, nowoczesna kompozycja
- Tylko opis wizualny sceny — bez tekstu do wstawienia w obraz
- Maksymalnie 2-3 zdania
- Odpowiedz WYŁĄCZNIE samym promptem, bez żadnych dodatkowych komentarzy"""

    completion = groq_client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[{"role": "user", "content": prompt}]
    )
    return completion.choices[0].message.content.strip()


def generuj_obraz(prompt_obrazu):
    response = requests.post(
        "https://api.stability.ai/v2beta/stable-image/generate/core",
        headers={
            "Authorization": f"Bearer {STABILITY_API_KEY}",
            "Accept": "image/*"
        },
        files={"none": ""},
        data={
            "prompt": prompt_obrazu,
            "output_format": "png",
            "aspect_ratio": "1:1"
        }
    )

    if response.status_code == 200:
        return response.content
    else:
        raise Exception(f"Błąd generowania obrazu ({response.status_code}): {response.text}")


def zapisz_obraz_w_storage(obraz_bytes, plan_id):
    nazwa_pliku = f"plan_{plan_id}_{int(datetime.now().timestamp())}.png"
    supabase.storage.from_(STORAGE_BUCKET).upload(
        nazwa_pliku,
        obraz_bytes,
        {"content-type": "image/png"}
    )
    url_response = supabase.storage.from_(STORAGE_BUCKET).get_public_url(nazwa_pliku)
    return url_response


# ====== ZAKŁADKI ======
tab1, tab2, tab3 = st.tabs(["✨ Generator treści", "🎨 Wzorce stylu", "📅 Kalendarz treści"])

# ---- ZAKŁADKA 1: GENERATOR ----
with tab1:
    col1, col2 = st.columns([2, 1])
    with col1:
        temat = st.text_input("O czym ma być treść?", placeholder="np. jak asystent AI pomaga pracownikom szukać dokumentów")
    with col2:
        platforma = st.selectbox("Platforma", ["Facebook", "Instagram", "Blog"], key="platforma_generator")

    colA, colB, colC = st.columns(3)
    with colA:
        uzyj_wiedzy = st.checkbox("📚 Baza wiedzy firmy", value=True)
    with colB:
        uzyj_internetu = st.checkbox("🌐 Trendy z internetu", value=False)
    with colC:
        uzyj_bloga = st.checkbox("📰 Treść z bloga firmy", value=False)

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        generuj_tekst_klik = st.button("✨ Generuj treść", type="primary")
    with col_btn2:
        generuj_obraz_klik = st.button("🖼️ Generuj obraz")

    if generuj_tekst_klik:
        if not temat.strip():
            st.warning("Wpisz temat, o którym ma być treść.")
        else:
            kontekst_firmy = ""
            kontekst_internet = ""
            kontekst_blog = ""

            if uzyj_wiedzy:
                with st.spinner("Szukam kontekstu w bazie wiedzy firmy..."):
                    kontekst_firmy = znajdz_kontekst_firmy(temat)

            if uzyj_internetu:
                with st.spinner("Szukam inspiracji i trendów w internecie..."):
                    kontekst_internet = research_w_internecie(temat, platforma)

            if uzyj_bloga:
                with st.spinner("Czytam blog firmy..."):
                    kontekst_blog = czytaj_blog_firmy(FIRMA_STRONA)

            wzorzec_stylu = pobierz_wzorzec_stylu(platforma)

            with st.spinner("Piszę treść..."):
                wygenerowana_tresc = generuj_tresc(temat, platforma, kontekst_firmy, kontekst_internet, kontekst_blog, wzorzec_stylu)
                st.session_state["ostatnia_tresc"] = wygenerowana_tresc

    if generuj_obraz_klik:
        if not temat.strip():
            st.warning("Wpisz temat, żeby wygenerować obraz.")
        else:
            try:
                with st.spinner("Szukam kontekstu branżowego..."):
                    kontekst_dla_obrazu = znajdz_kontekst_firmy(temat)

                with st.spinner("Tworzę opis obrazu..."):
                    prompt_obrazu = generuj_prompt_obrazu(temat, platforma, kontekst_dla_obrazu)

                with st.spinner("Generuję obraz (to może potrwać do minuty)..."):
                    obraz_bytes = generuj_obraz(prompt_obrazu)
                    st.session_state["ostatni_obraz"] = obraz_bytes
                    st.session_state["ostatni_prompt_obrazu"] = prompt_obrazu
            except Exception as e:
                st.error(f"Nie udało się wygenerować obrazu: {e}")

    if "ostatnia_tresc" in st.session_state:
        st.divider()
        st.subheader("📝 Wygenerowana treść")
        edytowalna_tresc = st.text_area(
            "Możesz edytować przed skopiowaniem:",
            value=st.session_state["ostatnia_tresc"],
            height=200
        )
        st.code(edytowalna_tresc, language=None)

    if "ostatni_obraz" in st.session_state:
        st.divider()
        st.subheader("🖼️ Wygenerowany obraz")
        st.image(st.session_state["ostatni_obraz"], use_container_width=True)
        st.caption(f"Prompt użyty do generowania: {st.session_state.get('ostatni_prompt_obrazu', '')}")
        st.download_button(
            "⬇️ Pobierz obraz",
            data=st.session_state["ostatni_obraz"],
            file_name="post_obraz.png",
            mime="image/png"
        )

# ---- ZAKŁADKA 2: WZORCE STYLU ----
with tab2:
    st.write("Wklej tutaj przykładowy post, który wcześniej publikowałeś — AI będzie się wzorować na jego stylu i tonie przy generowaniu nowych treści.")

    platforma_wzorca = st.selectbox("Dla jakiej platformy?", ["Facebook", "Instagram", "Blog"], key="platforma_wzorzec")

    obecny_wzorzec = pobierz_wzorzec_stylu(platforma_wzorca)

    nowy_wzorzec = st.text_area(
        f"Przykładowy post ({platforma_wzorca}):",
        value=obecny_wzorzec,
        height=180,
        placeholder="Wklej tutaj treść jednego ze swoich wcześniejszych postów..."
    )

    if st.button("💾 Zapisz wzorzec stylu"):
        zapisz_wzorzec_stylu(platforma_wzorca, nowy_wzorzec)
        st.success(f"Zapisano wzorzec stylu dla {platforma_wzorca}!")

# ---- ZAKŁADKA 3: KALENDARZ TREŚCI ----
with tab3:
    st.write("Wygeneruj listę pomysłów na treści na najbliższe tygodnie, z sugerowanymi terminami.")

    liczba_pomyslow = st.slider("Ile pomysłów wygenerować?", 3, 15, 8)
    uzyj_wiedzy_kalendarz = st.checkbox("📚 Uwzględnij bazę wiedzy firmy", value=True, key="wiedza_kalendarz")
    uzyj_bloga_kalendarz = st.checkbox("📰 Uwzględnij treść bloga", value=False, key="blog_kalendarz")

    if st.button("📅 Generuj pomysły do kalendarza", type="primary"):
        kontekst_firmy = ""
        kontekst_blog = ""

        if uzyj_wiedzy_kalendarz:
            with st.spinner("Szukam kontekstu w bazie wiedzy..."):
                kontekst_firmy = znajdz_kontekst_firmy("usługi firmy, korzyści dla klientów, częste pytania")

        if uzyj_bloga_kalendarz:
            with st.spinner("Czytam blog firmy..."):
                kontekst_blog = czytaj_blog_firmy(FIRMA_STRONA)

        with st.spinner("Generuję pomysły..."):
            pomysly = generuj_pomysly_kalendarza(liczba_pomyslow, kontekst_firmy, kontekst_blog)

            if pomysly:
                for pomysl in pomysly:
                    supabase.table("content_plan").insert({
                        "temat": pomysl.get("temat", ""),
                        "platforma": pomysl.get("platforma", ""),
                        "sugerowany_termin": pomysl.get("sugerowany_termin", ""),
                        "uzasadnienie": pomysl.get("uzasadnienie", ""),
                        "status": "do akceptacji"
                    }).execute()
                st.success(f"Wygenerowano i zapisano {len(pomysly)} pomysłów!")
            else:
                st.error("Nie udało się wygenerować pomysłów — spróbuj ponownie.")

    st.divider()
    st.subheader("Zaplanowane treści")

    response = supabase.table("content_plan").select("*").order("created_at", desc=True).execute()
    plany = response.data or []

    if not plany:
        st.info("Brak zaplanowanych treści — wygeneruj pomysły powyżej.")
    else:
        filtr_status = st.selectbox("Pokaż:", ["Wszystkie", "do akceptacji", "zatwierdzone", "opublikowane", "odrzucone"])

        for plan in plany:
            if filtr_status != "Wszystkie" and plan.get("status") != filtr_status:
                continue

            with st.expander(f"📌 {plan.get('temat', 'Brak tematu')} — {plan.get('platforma', '')} ({plan.get('status', '')})"):
                st.write(f"**Sugerowany termin:** {plan.get('sugerowany_termin', '—')}")
                st.write(f"**Uzasadnienie:** {plan.get('uzasadnienie', '—')}")

                if plan.get("tresc"):
                    st.text_area("Gotowa treść:", value=plan["tresc"], height=120, key=f"tresc_{plan['id']}", disabled=True)

                if ma_obraz(plan):
                    st.image(plan["obraz_url"], width=300)

                col1, col2, col3, col4, col5 = st.columns(5)
                with col1:
                    etykieta_tekst = "🔄 Nowy tekst" if plan.get("tresc") else "✍️ Tekst"
                    if st.button(etykieta_tekst, key=f"napisz_{plan['id']}"):
                        with st.spinner("Piszę..."):
                            wzorzec = pobierz_wzorzec_stylu(plan.get("platforma", "Facebook"))
                            tresc = generuj_tresc(
                                plan.get("temat", ""),
                                plan.get("platforma", "Facebook"),
                                "", "", "", wzorzec
                            )
                            supabase.table("content_plan").update({"tresc": tresc}).eq("id", plan["id"]).execute()
                            st.rerun()
                with col2:
                    etykieta_obraz = "🔄 Nowy obraz" if ma_obraz(plan) else "🖼️ Obraz"
                    if st.button(etykieta_obraz, key=f"obraz_{plan['id']}"):
                        try:
                            with st.spinner("Generuję obraz..."):
                                kontekst_dla_obrazu = znajdz_kontekst_firmy(plan.get("temat", ""))
                                prompt_obrazu = generuj_prompt_obrazu(plan.get("temat", ""), plan.get("platforma", "Facebook"), kontekst_dla_obrazu)
                                obraz_bytes = generuj_obraz(prompt_obrazu)
                                url = zapisz_obraz_w_storage(obraz_bytes, plan["id"])
                                supabase.table("content_plan").update({"obraz_url": url}).eq("id", plan["id"]).execute()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Błąd generowania obrazu: {e}")
                with col3:
                    if st.button("✅ Zatwierdź", key=f"zatwierdz_{plan['id']}"):
                        supabase.table("content_plan").update({"status": "zatwierdzone"}).eq("id", plan["id"]).execute()
                        st.rerun()
                with col4:
                    if st.button("📤 Opublikowane", key=f"opublikuj_{plan['id']}"):
                        supabase.table("content_plan").update({"status": "opublikowane"}).eq("id", plan["id"]).execute()
                        st.rerun()
                with col5:
                    if st.button("🗑️ Usuń", key=f"usun_{plan['id']}"):
                        supabase.table("content_plan").delete().eq("id", plan["id"]).execute()
                        st.rerun()
