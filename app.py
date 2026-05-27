"""Streamlit dashboard para FelyFit KOL System.

Run:
  streamlit run app.py

Tabs:
  1. Scouting    — corre scouting, ve candidatas nuevas, aprueba/rechaza
  2. Pipeline    — todas las candidatas filtradas por status
  3. Collabs     — registra collabs, ve EMV ratios en vivo
  4. Settings    — tunear multiplicadores EMV, hashtags semilla
"""

import base64
import json
import os
from datetime import datetime
from typing import List, Optional

import pandas as pd
import streamlit as st

import apify_jobs
import auth
import config
import db
import lookup_infographic
import scoring


# Helper para convertir path local de foto -> data URI base64
# (Streamlit ImageColumn no soporta paths locales, solo URLs/data URIs)
def _to_image_src(path_or_url: Optional[str]) -> Optional[str]:
    if not path_or_url:
        return None
    if path_or_url.startswith("http"):
        return path_or_url
    if not os.path.exists(path_or_url):
        return None
    try:
        with open(path_or_url, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        return f"data:image/jpeg;base64,{b64}"
    except Exception:
        return None


st.set_page_config(page_title="FelyFit KOL", page_icon=":material/spa:", layout="wide")


# ============================================================
# CUSTOM CSS — aesthetic FelyFit (blush, serif, bento cards)
# ============================================================
_CUSTOM_CSS = """
<style>
  /* Typography:
     - Headers + Metric labels: Bowlby One (chunky display)
     - Body: Quicksand (rounded sans-serif legible) */
  @import url('https://fonts.googleapis.com/css2?family=Bowlby+One&family=Quicksand:wght@400;500;600;700&display=swap');

  /* Palette vars */
  :root {
    --blush: #F5DDE0;
    --rose: #E5879A;
    --cream: #FBF4F2;
    --burgundy: #722F37;
    --burgundy-deep: #5A1F26;
    --plum: #3D2B30;
    --sage: #8EA58C;
    --sage-light: #E5EFE0;
    --terracotta: #A56C54;
  }

  /* Global typography — Be Bold inspired */
  html, body, [class*="css"] {
    font-family: 'Quicksand', 'Helvetica Neue', Arial, sans-serif !important;
    font-weight: 500 !important;
    color: #3D2B30;
  }
  h1, h2, h3, h4, h5 {
    font-family: 'Bowlby One', sans-serif !important;
    font-weight: 400 !important;
    letter-spacing: -0.01em;
    color: #3D2B30 !important;
    text-transform: lowercase;
  }
  h1 { font-size: 2.6rem !important; line-height: 1.0 !important; }
  h2 { font-size: 2.0rem !important; line-height: 1.05 !important; }
  h3 { font-size: 1.5rem !important; line-height: 1.1 !important; }
  /* strong / bold en body */
  strong, b { font-weight: 700 !important; }

  /* Backgrounds */
  .stApp {
    background: linear-gradient(180deg, #FBF4F2 0%, #F8E8E8 100%);
  }
  section[data-testid="stSidebar"] {
    background-color: #F5DDE0 !important;
    border-right: 1px solid #E5879A33;
  }

  /* Cards — metrics, expanders, containers */
  div[data-testid="stMetric"] {
    background: #FFFFFF;
    padding: 16px 20px;
    border-radius: 18px;
    border: 1px solid #F0C9CE;
    box-shadow: 0 2px 8px rgba(229, 135, 154, 0.08);
  }
  /* Asegurar que NINGÚN elemento usa default serif del browser */
  * { font-family: 'Quicksand', 'Helvetica Neue', Arial, sans-serif; }

  /* Metric label — Bowlby One. Selector agresivo: aplica a wrapper + hijos
     (p/div/span) porque Streamlit envuelve el texto en un <p> que tiene
     font-family propio que rompe la herencia. */
  div[data-testid="stMetricLabel"],
  div[data-testid="stMetricLabel"] *,
  div[data-testid="stMetricLabel"] p,
  div[data-testid="stMetricLabel"] div,
  div[data-testid="stMetricLabel"] label {
    font-family: 'Bowlby One', 'Helvetica Neue', sans-serif !important;
    font-weight: 400 !important;
    text-transform: lowercase;
    letter-spacing: 0.02em;
    color: #8E5A65 !important;
  }
  div[data-testid="stMetricLabel"] p {
    font-size: 0.85rem !important;
  }

  /* Metric value — también Bowlby */
  div[data-testid="stMetricValue"],
  div[data-testid="stMetricValue"] *,
  div[data-testid="stMetricValue"] p,
  div[data-testid="stMetricValue"] div {
    font-family: 'Bowlby One', 'Helvetica Neue', sans-serif !important;
    font-weight: 400 !important;
    color: #3D2B30 !important;
  }

  /* Expander */
  div[data-testid="stExpander"] {
    background: #FFFFFF;
    border-radius: 18px;
    border: 1px solid #F0C9CE;
    box-shadow: 0 2px 8px rgba(229, 135, 154, 0.06);
  }
  div[data-testid="stExpander"] summary {
    padding: 14px 20px;
    border-radius: 18px;
  }

  /* Containers / bordered blocks */
  div[data-testid="stVerticalBlockBorderWrapper"] {
    background: #FFFFFFCC;
    border-radius: 20px !important;
    border: 1px solid #F0C9CE !important;
    box-shadow: 0 2px 12px rgba(229, 135, 154, 0.08);
  }

  /* Buttons — primary = rose */
  button[kind="primary"], .stButton > button[kind="primary"] {
    background-color: #E5879A !important;
    border: none !important;
    border-radius: 12px !important;
    color: white !important;
    font-family: 'Quicksand', 'Helvetica Neue', Arial, sans-serif !important;
    font-weight: 700 !important;
    padding: 10px 20px !important;
    transition: all 0.2s ease;
  }
  button[kind="primary"]:hover {
    background-color: #D26A7F !important;
    box-shadow: 0 4px 12px rgba(229, 135, 154, 0.3) !important;
  }
  .stButton > button:not([kind="primary"]) {
    background-color: #FFFFFF !important;
    border: 1px solid #F0C9CE !important;
    border-radius: 12px !important;
    color: #3D2B30 !important;
  }
  .stButton > button:not([kind="primary"]):hover {
    background-color: #FBF4F2 !important;
    border-color: #E5879A !important;
  }

  /* Tabs — rounded */
  button[role="tab"] {
    border-radius: 12px 12px 0 0 !important;
    font-family: 'Quicksand', 'Helvetica Neue', Arial, sans-serif !important;
    font-weight: 600 !important;
  }
  button[role="tab"][aria-selected="true"] {
    color: #E5879A !important;
    border-bottom: 2px solid #E5879A !important;
  }

  /* Dataframes — softer */
  div[data-testid="stDataFrame"] {
    border-radius: 16px;
    overflow: hidden;
    border: 1px solid #F0C9CE;
  }

  /* Selectbox, multiselect, slider — pill style */
  div[data-baseweb="select"] > div, div[data-baseweb="input"] > div {
    border-radius: 12px !important;
  }

  /* Info/success/warning boxes */
  div[data-testid="stAlert"] {
    border-radius: 16px;
    border: none;
  }

  /* Sidebar radio (Página picker) */
  section[data-testid="stSidebar"] [role="radiogroup"] label {
    padding: 8px 12px;
    border-radius: 10px;
    margin-bottom: 4px;
    transition: background 0.15s;
  }
  section[data-testid="stSidebar"] [role="radiogroup"] label:hover {
    background: #FFFFFF80;
  }
  /* Sidebar — "Página" label + opciones del radio en Bowlby One.
     Target preciso: solo nodos de texto (p) para no afectar los Material icons,
     que viven en <span class="material-symbols-rounded ...">. */
  section[data-testid="stSidebar"] [data-testid="stWidgetLabel"],
  section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p,
  section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] div,
  section[data-testid="stSidebar"] [role="radiogroup"] label p,
  section[data-testid="stSidebar"] [role="radiogroup"] label > div > p {
    font-family: 'Bowlby One', 'Helvetica Neue', sans-serif !important;
    font-weight: 400 !important;
    text-transform: lowercase;
    letter-spacing: 0.01em;
    color: #3D2B30 !important;
  }
  section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {
    font-size: 0.85rem !important;
    color: #8E5A65 !important;
  }
  section[data-testid="stSidebar"] [role="radiogroup"] label p {
    font-size: 1.0rem !important;
  }

  /* Progress bar */
  div[data-testid="stProgress"] > div > div {
    background-color: #E5879A !important;
  }

  /* Dividers — softer */
  hr {
    border-color: #F0C9CE !important;
    opacity: 0.5;
  }

  /* Sidebar title — hidden, replaced by custom logo */
  section[data-testid="stSidebar"] h1 {
    display: none;
  }
  /* Reducir padding-top del sidebar para que el logo suba */
  section[data-testid="stSidebar"] > div:first-child {
    padding-top: 0 !important;
  }
  section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {
    padding-top: 0.5rem !important;
  }

  /* Custom logo */
  .ff-logo-wrap {
    position: relative;
    width: 100%;
    height: 130px;
    margin: 4px 0 24px 0;
  }
  .ff-logo-blob {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
  }
  .ff-logo-text {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    pointer-events: none;
  }
  .ff-logo-name {
    font-family: 'Bowlby One', sans-serif;
    font-size: 2.6rem;
    line-height: 0.85;
    color: var(--blush);
    letter-spacing: -0.02em;
    text-transform: lowercase;
  }
  .ff-logo-tag {
    font-family: 'Quicksand', 'Helvetica Neue', Arial, sans-serif;
    font-weight: 600;
    font-size: 0.62rem;
    color: var(--blush);
    letter-spacing: 0.28em;
    text-transform: uppercase;
    margin-top: 6px;
    opacity: 0.85;
  }

  /* Y2K-style decorative accent (used inline) */
  .ff-star {
    display: inline-block;
    width: 14px;
    height: 14px;
    margin: 0 6px -2px 0;
    color: var(--burgundy);
  }

  /* Hide streamlit branding */
  #MainMenu {visibility: hidden;}
  footer {visibility: hidden;}
</style>
"""
st.markdown(_CUSTOM_CSS, unsafe_allow_html=True)


# ============================================================
# Reject reasons — alineadas con ejes de filtro del sistema.
# Cada razón es accionable: si una se repite mucho, sabemos qué tunear.
# ============================================================
REJECT_REASONS = [
    "No es nicho (fitness/wellness)",            # → tunear keywords de niche
    "No es MX / fuera de target geo",            # → mejorar country detector
    "Es marca/estudio/gym (no individual)",      # → mejorar account_type classifier
    "Estética no encaja con FelyFit",            # → señal subjetiva, hard to automate
    "Audiencia parece comprada",                 # → mejorar bot detection
    "Edad/demo no target",                       # → revisar criterio demo
    "Ya colaboramos antes",                      # → check de históricos
    "Cuenta inactiva / posts viejos",            # → tunear max_days_since_last_post
    "Hombre (no female)",                        # → mejorar gender detector
    "Otro",
]


# ============================================================
# Helpers
# ============================================================
def fetch_df(sql: str, params: tuple = ()) -> pd.DataFrame:
    with db.connect() as conn:
        if params:
            return pd.read_sql_query(sql, conn, params=params)
        return pd.read_sql_query(sql, conn)


def _normalize_for_dup(s: str) -> str:
    """Para comparar handles/nombres ignorando ruido."""
    if not s:
        return ""
    return "".join(c for c in s.lower() if c.isalnum())


def find_possible_dups(handle: str, full_name: Optional[str]) -> list:
    """Encuentra otras filas que podrian ser la misma persona.
    Compara handle normalizado (sin puntos/guiones) y nombre normalizado."""
    h_norm = _normalize_for_dup(handle)
    n_norm = _normalize_for_dup(full_name or "")

    with db.connect() as conn:
        rows = conn.execute(
            "SELECT handle, full_name, status, lark_record_id "
            "FROM candidates WHERE handle != ?",
            (handle,),
        ).fetchall()

    matches = []
    for r in rows:
        other_h = _normalize_for_dup(r["handle"])
        other_n = _normalize_for_dup(r["full_name"] or "")
        # Match si: handles normalizados iguales, o nombres iguales (y nombre no vacio)
        if (other_h and other_h == h_norm) or (n_norm and other_n == n_norm):
            matches.append(dict(r))
    return matches


def ig_url(handle: str) -> str:
    return f"https://instagram.com/{handle.replace(' ', '')}"


# ============================================================
# Colored metrics — sage green (good) / soft terracotta (bad)
# Comparando contra IDEAL_CRITERIA del KOL FelyFit
# ============================================================
_METRIC_COLORS = {
    "good": {  # sage hint
        "bg": "#E5EFE0", "border": "#8EA58C",
        "label": "#5A7857", "value": "#344C3D",
    },
    "ok": {  # white card con borde blush (contraste vs fondo cream)
        "bg": "#FFFFFF", "border": "#E5879A66",
        "label": "#8E5A65", "value": "#3D2B30",
    },
    "bad": {  # terracotta más profundo
        "bg": "#E8C2B0", "border": "#A56C54",
        "label": "#7A4233", "value": "#4D2A20",
    },
    "neutral": {  # white card con borde gris suave
        "bg": "#FFFFFF", "border": "#E0D5D2",
        "label": "#8E5A65", "value": "#3D2B30",
    },
}


def _colored_metric(label: str, value: str, mood: str = "neutral",
                    sublabel: Optional[str] = None) -> str:
    """HTML para una metric card con color según mood."""
    c = _METRIC_COLORS.get(mood, _METRIC_COLORS["neutral"])
    sub = f'<div style="font-size:0.75rem;color:{c["label"]};margin-top:4px;opacity:0.75;">{sublabel}</div>' if sublabel else ""
    return (
        f'<div style="background:{c["bg"]};padding:14px 18px;border-radius:18px;'
        f'border:1px solid {c["border"]};box-shadow:0 2px 8px rgba(229,135,154,0.08);'
        f'min-height:90px;display:flex;flex-direction:column;justify-content:center;">'
        f'<div style="font-family:\'Quicksand\',sans-serif;font-weight:600;font-size:0.75rem;'
        f'text-transform:uppercase;letter-spacing:0.05em;color:{c["label"]};margin-bottom:6px;">{label}</div>'
        f'<div style="font-family:\'Bowlby One\',sans-serif;font-weight:400;'
        f'font-size:1.8rem;color:{c["value"]};line-height:1.1;">{value}</div>'
        f'{sub}'
        f'</div>'
    )


def _eval_followers(n: Optional[int]) -> str:
    if not n:
        return "bad"
    # Sweet spot 10K-100K (mid/micro)
    if 10_000 <= n <= 100_000:
        return "good"
    if 2_000 <= n <= 500_000:
        return "ok"
    return "bad"


def _eval_er(er: Optional[float], tier: Optional[str]) -> str:
    if er is None or er <= 0:
        return "bad"
    tier_min = config.IDEAL_CRITERIA["er_min_by_tier"].get(tier or "micro", 0.025)
    if er >= tier_min * 1.5:
        return "good"
    if er >= tier_min:
        return "ok"
    return "bad"


def _eval_fit(fit: Optional[float]) -> str:
    if fit is None:
        return "bad"
    if fit >= 70:
        return "good"
    if fit >= 40:
        return "ok"
    return "bad"


def _eval_ff_ratio(followers: int, following: int) -> str:
    if not following or following == 0:
        return "neutral"
    ratio = followers / following
    if ratio >= 10:
        return "good"
    if ratio >= 2:
        return "ok"
    return "bad"


def _eval_country(country: Optional[str]) -> str:
    if country == "MX":
        return "good"
    if country is None:
        return "ok"
    return "bad"


def _eval_gender(gender: Optional[str]) -> str:
    if gender == "female":
        return "good"
    if gender is None:
        return "ok"
    return "bad"


def _eval_account_type(at: Optional[str]) -> str:
    if at == "individual":
        return "good"
    if at in ("studio", "brand", "collective"):
        return "bad"
    return "ok"


def _eval_tier(tier: Optional[str]) -> str:
    """Sweet spot tiers para FelyFit en esta fase."""
    if tier in ("micro", "mid"):
        return "good"
    if tier in ("nano", "macro"):
        return "ok"
    if tier == "mega":
        return "bad"  # caro, dudoso ROI para FelyFit
    return "neutral"


def status_counts() -> pd.DataFrame:
    return fetch_df("SELECT status, COUNT(*) as n FROM candidates GROUP BY status ORDER BY n DESC")


def set_candidate_status(handle: str, new_status: str, notes: Optional[str] = None) -> None:
    with db.connect() as conn:
        if notes:
            conn.execute("UPDATE candidates SET status=?, notes=? WHERE handle=?",
                         (new_status, notes, handle))
        else:
            conn.execute("UPDATE candidates SET status=? WHERE handle=?", (new_status, handle))


def approve_to_lark(handle: str) -> dict:
    """Aprueba localmente Y pushea a Lark."""
    import lark_sync
    set_candidate_status(handle, "approved")
    return lark_sync.push_candidate_to_lark(handle)


# ============================================================
# Header con totales
# ============================================================
def render_header() -> None:
    sc = status_counts()
    total = int(sc["n"].sum()) if not sc.empty else 0

    cols = st.columns(7)
    cols[0].metric("Total", total)
    by = {row["status"]: int(row["n"]) for _, row in sc.iterrows()}
    cols[1].metric("Discovered", by.get("discovered", 0))
    cols[2].metric("Approved", by.get("approved", 0))
    cols[3].metric("Contacted", by.get("contacted", 0))
    cols[4].metric("Responded", by.get("responded", 0))
    cols[5].metric("Negotiating", by.get("negotiating", 0))
    cols[6].metric("Active", by.get("active", 0))


# ============================================================
# PAGE: Scouting
# ============================================================
def page_scouting() -> None:
    st.header(":material/search: Scouting")

    # ============== ACTIVIDAD DEL BOT AUTÓNOMO ==============
    # Scouts ejecutados por scheduled_scout.py (cron / launchd) en últimas 24h.
    # Sirve para saber qué encontró el sistema sin que yo entrara a correrlo.
    bot_activity = fetch_df("""
        SELECT COUNT(*) runs,
               COALESCE(SUM(candidates_new), 0) new_,
               COALESCE(SUM(apify_compute_usd), 0) usd,
               MAX(started_at) last_run
        FROM scout_runs
        WHERE started_at >= datetime('now', '-24 hours')
    """)
    if not bot_activity.empty and int(bot_activity.iloc[0]["runs"]) > 0:
        r = bot_activity.iloc[0]
        st.info(
            f":material/robot_2: **Actividad últimas 24h** — "
            f"{int(r['runs'])} runs · {int(r['new_'])} candidatas nuevas · "
            f"${float(r['usd']):.4f} gastado · último: {r['last_run']}"
        )

    # ============== SCOUT FROM SEEDS — discovery por red ==============
    # Usa relatedProfiles de tus aptas para encontrar candidates similares.
    # Es el equivalente al algoritmo de IG cuando entras a un perfil y ves "Suggested".
    with st.container(border=True):
        st.markdown("**:material/hub: Scout from seeds — discovery por red**")
        seeds = apify_jobs.get_seed_handles()
        edges_count = fetch_df(
            "SELECT COUNT(*) AS n FROM related_profiles_edges"
        ).iloc[0]["n"]
        candidate_pool = fetch_df("""
            SELECT COUNT(DISTINCT related_handle) AS n
            FROM related_profiles_edges
            WHERE related_handle NOT IN (SELECT handle FROM candidates)
        """).iloc[0]["n"]

        sc1, sc2, sc3 = st.columns(3)
        sc1.metric("Seeds (aptas)", len(seeds))
        sc2.metric("Edges captured", int(edges_count))
        sc3.metric("Candidates nuevos potenciales", int(candidate_pool))

        st.caption(
            "Usa tus candidates aprobadas como semillas. Apify ya nos da "
            "'perfiles similares' por cada seed. Las que aparecen en más seeds "
            "= mejor candidate. Costo ~$0.30 USD por corrida full."
        )

        seed_c1, seed_c2 = st.columns([1, 1])
        seed_target = seed_c1.number_input(
            "Target aptas finales", min_value=1, max_value=30, value=8,
            key="seed_scout_target",
        )
        seed_overlap = seed_c2.slider(
            "Overlap mínimo (cuántas seeds deben recomendar)",
            min_value=1, max_value=5, value=1,
            help="Si subes a 2, solo candidates recomendadas por ≥2 seeds. Más estricto, más relevante.",
        )

        if st.button(":material/explore: Correr scout from seeds",
                     type="primary", key="run_seed_scout"):
            if len(seeds) == 0:
                st.error("No tienes seeds. Aprueba al menos 1 candidata en Felynder primero.")
            else:
                progress = st.empty()
                with st.spinner("Corriendo discovery por red…"):
                    result = apify_jobs.scout_from_seeds(
                        target_passing=int(seed_target),
                        min_overlap=int(seed_overlap),
                        max_candidates_to_enrich=30,
                        allowed_account_types=["individual"],
                        allowed_countries=["MX"],
                        allowed_genders=["female"],
                        progress_callback=lambda msg: progress.info(msg),
                    )
                progress.empty()
                if result.get("message"):
                    st.warning(result["message"])
                else:
                    rr = result["refresh_result"]
                    st.success(
                        f"✅ Done · refreshed {rr['refreshed']} seeds · "
                        f"ranked {result['ranked_candidates']} candidates · "
                        f"enriquecidas {result['enriched']} · "
                        f"aptas {result['passing']} · "
                        f"auto_rejected {result['auto_rejected']}"
                    )
                    st.session_state.active_page = ":material/swipe: Felynder"
                    st.rerun()

    st.subheader(":material/add_circle: Nuevo scout")

    # ============== PASO 1 — PARAMETROS ==============
    with st.container(border=True):
        st.markdown("**Paso 1 · Parámetros del scout** (lo que NO cumpla se descarta)")

        type_col, foll_col = st.columns(2)
        ACCOUNT_TYPE_OPTIONS = ["individual", "studio", "brand", "nonprofit", "collective", "unknown"]
        ACCOUNT_TYPE_FRIENDLY = {
            "individual": "👤 Individual (creadora)",
            "studio":     "🏢 Studio / Estudio",
            "brand":      "🛍️ Brand / Marca",
            "nonprofit":  "❤️ Nonprofit / ONG",
            "collective": "👥 Collective / Equipo",
            "unknown":    "❓ Unknown (bio vacía)",
        }
        allowed_types = type_col.multiselect(
            "Tipos de cuenta a incluir",
            ACCOUNT_TYPE_OPTIONS,
            default=["individual"],
            format_func=lambda x: ACCOUNT_TYPE_FRIENDLY[x],
            help="El sistema clasifica cada cuenta por bio/nombre.",
        )

        foll_min, foll_max = foll_col.slider(
            "Rango de followers",
            min_value=1_000, max_value=2_000_000,
            value=(2_000, 500_000), step=1_000,
        )

        country_col, gender_col = st.columns(2)
        COUNTRY_OPTIONS = ["MX", "US", "AR", "CO", "ES", "PE", "CL", "BR", "UNKNOWN"]
        COUNTRY_FRIENDLY = {
            "MX": "🇲🇽 México", "US": "🇺🇸 USA", "AR": "🇦🇷 Argentina",
            "CO": "🇨🇴 Colombia", "ES": "🇪🇸 España", "PE": "🇵🇪 Perú",
            "CL": "🇨🇱 Chile", "BR": "🇧🇷 Brasil",
            "UNKNOWN": "❓ País no detectable",
        }
        allowed_countries = country_col.multiselect(
            "Países permitidos",
            COUNTRY_OPTIONS,
            default=["MX"],
            format_func=lambda x: COUNTRY_FRIENDLY[x],
            help="Detección autoritativa de IG About. UNKNOWN = no detectable.",
        )

        GENDER_OPTIONS = ["female", "male", "unknown"]
        GENDER_FRIENDLY = {
            "female": "👩 Mujer",
            "male": "👨 Hombre",
            "unknown": "❓ No detectable por nombre",
        }
        allowed_genders = gender_col.multiselect(
            "Género",
            GENDER_OPTIONS,
            default=["female", "unknown"],
            format_func=lambda x: GENDER_FRIENDLY[x],
            help="Detección por primer nombre. Por default: mujer + indeterminado (para no perder nombres ambiguos). Quita 'unknown' si quieres filtro estricto.",
        )

    # ============== PASO 2 — TARGET ==============
    with st.container(border=True):
        st.markdown("**Paso 2 · Fuente del scout**")
        scout_type = st.radio(
            "Tipo de scout",
            ["🎯 Tema (multi-hashtag automático)",
             "🔖 Hashtag específico",
             "🤝 Menciones de competidora"],
            horizontal=False, key="scout_type_radio",
            help="**Tema** intenta varios hashtags MX automáticamente hasta cumplir tu target. **Hashtag específico** solo intenta uno (recomendado solo si sabes lo que buscas).",
        )
        col1, col2 = st.columns([3, 1])
        target_passing = col2.number_input(
            "Cantidad APTAS a revisar",
            min_value=1, max_value=100, value=10, step=1,
            help="El sistema scrapea hasta encontrar este número de candidatas que pasen TODOS los filtros.",
        )

        if scout_type.startswith("🎯"):
            theme = col1.selectbox(
                "Tema",
                options=list(config.HASHTAG_THEMES.keys()),
            )
            target = theme
            scout_type_key = "theme"
            n_hashtags = len(config.HASHTAG_THEMES.get(theme, []))
            col1.caption(f"🔁 Intentará hasta {n_hashtags} hashtags MX automáticamente: "
                         + ", ".join(f"#{h}" for h in config.HASHTAG_THEMES[theme][:5])
                         + ("..." if n_hashtags > 5 else ""))
        elif scout_type.startswith("🔖"):
            seed = config.SCOUTING_DEFAULTS["hashtags_seed"]
            hashtag = col1.selectbox("Hashtag", options=seed + ["(otro - escribir abajo)"])
            custom = col1.text_input("Hashtag custom (sin #)",
                                     value="" if hashtag != "(otro - escribir abajo)" else "")
            target = custom or hashtag
            scout_type_key = "hashtag"
        else:
            seed = config.SCOUTING_DEFAULTS["competitor_handles_seed"]
            competitor = col1.selectbox("Competidora", options=seed + ["(otro - escribir abajo)"])
            custom = col1.text_input("Handle custom (sin @)",
                                     value="" if competitor != "(otro - escribir abajo)" else "")
            target = custom or competitor
            scout_type_key = "competitor_mention"

    # ============== PASO 3 — RUN ==============
    # Costo estimado: target * ~$0.05 (4-5x scrape + enrichment del que pasa)
    est_cost = int(target_passing) * 0.05
    st.caption(f"💰 Costo estimado: ~${est_cost:.2f} USD (puede variar según pass rate del hashtag)")
    if st.button("🚀 Ejecutar scout hasta tener candidatas aptas", type="primary",
                 use_container_width=True):
        progress_placeholder = st.empty()

        def progress_cb(msg):
            progress_placeholder.info(msg)

        with st.spinner(f"Buscando {int(target_passing)} candidatas aptas en {target}..."):
            try:
                if scout_type_key == "theme":
                    result = apify_jobs.scout_theme_until_target(
                        theme=target,
                        target_passing=int(target_passing),
                        allowed_account_types=allowed_types,
                        allowed_countries=allowed_countries,
                        allowed_genders=allowed_genders,
                        followers_min_override=foll_min,
                        followers_max_override=foll_max,
                        progress_callback=progress_cb,
                    )
                    if result.get("hashtags_tried"):
                        result["attempts"] = len(result["hashtags_tried"])
                    else:
                        result["attempts"] = 0
                else:
                    result = apify_jobs.scout_until_target(
                        scout_type=scout_type_key,
                        source=target,
                        target_passing=int(target_passing),
                        allowed_account_types=allowed_types,
                        allowed_countries=allowed_countries,
                        allowed_genders=allowed_genders,
                        followers_min_override=foll_min,
                        followers_max_override=foll_max,
                    )
                progress_placeholder.empty()
                # Breakdown de razones de auto-rechazo (para entender por qué tan pocas pasan)
                reasons = {}
                if result["run_ids"]:
                    rejected_rows = fetch_df(
                        "SELECT filter_reason FROM candidates "
                        "WHERE scout_run_id IN ({}) AND status='auto_rejected'".format(
                            ",".join(["?"] * len(result["run_ids"]))
                        ),
                        tuple(result["run_ids"])
                    )
                    for _, row in rejected_rows.iterrows():
                        reason = (row["filter_reason"] or "").split("(")[0].split("<")[0].strip()
                        # Simplificar razones
                        if "país" in reason or "country" in reason:
                            key = "🌍 país no permitido"
                        elif "tipo de cuenta" in reason:
                            key = "🏢 tipo no permitido (studio/brand/etc)"
                        elif "followers" in reason or "1K" in reason:
                            key = "👥 followers fuera de rango"
                        elif "ER" in reason:
                            key = "📉 ER bajo para su tier"
                        elif "niche" in reason:
                            key = "🚫 no menciona nichos relevantes"
                        elif "bot" in reason or "likes/comments" in reason:
                            key = "🤖 sospechoso de bots"
                        else:
                            key = "❓ otra razón"
                        reasons[key] = reasons.get(key, 0) + 1

                hashtags_msg = ""
                if result.get("hashtags_tried"):
                    hashtags_msg = f" · intenté {len(result['hashtags_tried'])} hashtags: " + \
                                   ", ".join(f"#{h['hashtag']} ({h['passing']})"
                                             for h in result["hashtags_tried"])

                if result["passing"] > 0:
                    st.success(
                        f"✅ **{result['passing']} aptas encontradas** "
                        f"(target: {result['target']}) · "
                        f"{result['auto_rejected']} filtradas · "
                        f"{result['scraped']} scrapeadas · "
                        f"costo ${result['compute_usd']:.4f}{hashtags_msg}"
                    )
                    if not result["reached_target"]:
                        st.warning(
                            f"⚠️ Solo encontré {result['passing']} de {result['target']} pedidas. "
                            "Considera escoger otro tema o relajar filtros."
                        )
                    # Auto-redirect SOLO si hay aptas para revisar
                    st.session_state.active_page = ":material/swipe: Felynder"
                    st.rerun()
                else:
                    st.error(
                        f"❌ **0 aptas encontradas** de {result['target']} pedidas. "
                        f"{result['auto_rejected']} candidatas fueron filtradas. "
                        f"Scrapeadas: {result['scraped']} · costo ${result['compute_usd']:.4f}"
                    )
                    if reasons:
                        st.markdown("**¿Por qué se filtraron?**")
                        for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
                            st.write(f"- {reason}: **{count}**")
                        st.info(
                            "💡 **Sugerencias**: prueba un hashtag más específico de MX "
                            "(`#fitnessmexico`, `#mujeresfit`, `#correrenmexico`), "
                            "o incluye **UNKNOWN** en países permitidos, "
                            "o relaja el rango de followers."
                        )
                    # NO redirect — quédate aquí para que veas el feedback
            except Exception as e:
                st.error(f"Error: {e}")
                st.exception(e)

    # ===== Últimos scout runs — agrupando theme scouts por session_id =====
    last_runs_raw = fetch_df("""
        SELECT id, source, source_detail, candidates_seen, candidates_new,
               apify_compute_usd, status, started_at, finished_at,
               session_id, session_label
        FROM scout_runs ORDER BY id DESC LIMIT 50
    """)
    if not last_runs_raw.empty:
        groups = []
        seen_sessions = set()
        for _, r in last_runs_raw.iterrows():
            sid = r["session_id"]
            has_session = pd.notna(sid) and bool(sid)
            if has_session and sid in seen_sessions:
                continue
            if has_session:
                # Theme scout — agrupar todos los runs con este session_id
                sub = last_runs_raw[last_runs_raw["session_id"] == sid]
                groups.append({
                    "key": f"sess_{sid}",
                    "label": r["session_label"] or f"Session {sid[:8]}",
                    "run_ids": [int(x) for x in sub["id"].tolist()],
                    "started_at": sub["started_at"].min(),
                    "hashtags": sub["source_detail"].tolist(),
                    "seen": int(sub["candidates_seen"].fillna(0).sum()),
                    "new": int(sub["candidates_new"].fillna(0).sum()),
                    "cost": float(sub["apify_compute_usd"].fillna(0).sum()),
                    "status_emoji": "✅",
                })
                seen_sessions.add(sid)
            else:
                groups.append({
                    "key": f"run_{r['id']}",
                    "label": r["source_detail"],
                    "run_ids": [int(r["id"])],
                    "started_at": r["started_at"],
                    "hashtags": [r["source_detail"]],
                    "seen": int(r["candidates_seen"] or 0),
                    "new": int(r["candidates_new"] or 0),
                    "cost": float(r["apify_compute_usd"] or 0),
                    "status_emoji": "✅" if r["status"] == "done" else "❌",
                })
            if len(groups) >= 10:
                break

        st.divider()
        with st.expander(f"📊 Últimos {len(groups)} scout runs", expanded=True):
            for g in groups:
                placeholders = ",".join(["?"] * len(g["run_ids"]))
                stats = fetch_df(
                    f"SELECT status, COUNT(*) as n FROM candidates "
                    f"WHERE scout_run_id IN ({placeholders}) GROUP BY status",
                    tuple(g["run_ids"])
                )
                by_status = {row["status"]: int(row["n"]) for _, row in stats.iterrows()}
                pending = by_status.get("discovered", 0)
                approved = by_status.get("approved", 0) + by_status.get("contacted", 0) + by_status.get("active", 0)
                paused = by_status.get("paused", 0)
                auto_rej = by_status.get("auto_rejected", 0)

                if len(g["hashtags"]) > 1:
                    label = f"🎯 {g['label']} ({len(g['hashtags'])} hashtags)"
                else:
                    label = g["label"]

                cols = st.columns([5, 1])
                cols[0].write(
                    f"{g['status_emoji']} **{label}** · "
                    f"vistos: {g['seen']} · nuevas: {g['new']} · "
                    f"📋 pendientes: **{pending}** · ✅ aprobadas: {approved} · "
                    f"🔖 pausadas: {paused} · ❌ auto-rej: {auto_rej} · "
                    f"${g['cost']:.4f} · {g['started_at']}"
                )
                viewing = st.session_state.get("scout_detail_key") == g["key"]
                btn_label = "✕ Ocultar" if viewing else "📋 Ver candidatas"
                if cols[1].button(btn_label, key=f"audit_{g['key']}"):
                    if viewing:
                        st.session_state.pop("scout_detail_key", None)
                        st.session_state.pop("scout_detail_run_ids", None)
                        st.session_state.pop("scout_detail_label", None)
                    else:
                        st.session_state.scout_detail_key = g["key"]
                        st.session_state.scout_detail_run_ids = g["run_ids"]
                        st.session_state.scout_detail_label = label
                    st.rerun()

    # Detalle inline del scout seleccionado (1 o N runs si es theme)
    if "scout_detail_run_ids" in st.session_state:
        _render_scout_detail_multi(
            run_ids=st.session_state.scout_detail_run_ids,
            label=st.session_state.get("scout_detail_label", "Scout"),
        )

    st.divider()
    st.subheader("Candidatas ideales (pasan todos los filtros)")
    st.caption("Solo descubrimientos NUEVOS por scout que cumplen el criterio. "
               "Las que no pasan se eliminan automáticamente — no se acumulan en el sistema.")

    pending = fetch_df("""
        SELECT handle, full_name, followers, engagement_rate, tier, fit_score, source_detail,
               last_enriched_at, contact_email, status, bio, profile_pic_url, external_url
        FROM candidates
        WHERE status='discovered'
          AND lark_record_id IS NULL
          AND source != 'lark_import'
        ORDER BY fit_score DESC NULLS LAST, discovered_at DESC
        LIMIT 100
    """)

    if pending.empty:
        st.info("No hay candidatas pendientes. Corre un scout arriba o `--enrich-pending` desde CLI.")
        return

    not_enriched = pending[pending["fit_score"].isna()]
    if not not_enriched.empty:
        st.warning(f"⚠️ {len(not_enriched)} candidatas sin enriquecer (sin ER ni Fit Score). "
                   "Corre desde terminal: `python scout.py --enrich-pending --limit 5`")

    pending["engagement_rate"] = pd.to_numeric(pending["engagement_rate"], errors="coerce")
    pending["fit_score"] = pd.to_numeric(pending["fit_score"], errors="coerce")

    # Anotar duplicados sospechosos
    pending["⚠️ Dup"] = pending.apply(
        lambda r: "⚠️" if find_possible_dups(r["handle"], r["full_name"]) else "",
        axis=1,
    )
    pending["IG"] = pending["handle"].apply(ig_url)

    enriched = pending[pending["fit_score"].notna()].copy()
    if not enriched.empty:
        enriched["ER %"] = (enriched["engagement_rate"] * 100).round(2)
        enriched["Followers"] = enriched["followers"].fillna(0).astype(int).map("{:,}".format)
        enriched["Fit"] = enriched["fit_score"].round(1)

        # Agrupar por tier: nano -> micro -> mid -> macro -> mega
        TIER_ORDER = ["mega", "macro", "mid", "micro", "nano"]
        TIER_LABEL = {
            "mega": "🌟 Mega (500K+)",
            "macro": "🏆 Macro (150K-500K)",
            "mid":   "✨ Mid (50K-150K)",
            "micro": "📈 Micro (10K-50K)",
            "nano":  "🌱 Nano (3K-10K)",
        }

        enriched["Foto"] = enriched["profile_pic_url"].apply(_to_image_src)
        cols_show = ["Foto", "handle", "full_name", "Followers", "ER %", "Fit",
                     "source_detail", "⚠️ Dup", "IG"]

        for tier in TIER_ORDER:
            tier_df = enriched[enriched["tier"] == tier]
            if tier_df.empty:
                continue
            st.markdown(f"### {TIER_LABEL[tier]}  ·  {len(tier_df)}")
            st.dataframe(
                tier_df[cols_show],
                use_container_width=True, hide_index=True,
                column_config={
                    "Foto": st.column_config.ImageColumn("Foto", width="small"),
                    "IG": st.column_config.LinkColumn("Perfil IG", display_text="abrir →"),
                    "⚠️ Dup": st.column_config.TextColumn("Dup?", width="small"),
                },
            )

        st.divider()
        st.subheader("Aprobar / Rechazar")
        pickable = enriched
        handle_pick = st.selectbox(
            "Selecciona handle",
            options=pickable["handle"].tolist(),
            format_func=lambda h: f"@{h}  (fit {pickable[pickable['handle']==h]['Fit'].iloc[0]})",
        )

        cand = pickable[pickable["handle"] == handle_pick].iloc[0]
        pic_col, info_col = st.columns([1, 4])
        if cand.get("profile_pic_url"):
            try:
                pic_col.image(cand["profile_pic_url"], width=120)
            except Exception:
                pic_col.write("(foto no disponible)")
        with info_col:
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Followers", cand["Followers"])
            col2.metric("ER", f"{cand['ER %']}%")
            col3.metric("Fit Score", cand["Fit"])
            col4.link_button("👁 Ver perfil en IG", ig_url(handle_pick))
            if cand.get("bio"):
                st.caption(f"**Bio:** {cand['bio'][:300]}")

        # Avisos de posible duplicado
        dups = find_possible_dups(handle_pick, cand.get("full_name"))
        if dups:
            st.warning(
                "⚠️ Posible duplicada en la base. Revisa antes de aprobar:\n\n"
                + "\n".join(
                    f"- @{d['handle']} ({d['full_name'] or 'sin nombre'}) — "
                    f"status: {d['status']}, en Lark: {'sí' if d['lark_record_id'] else 'no'}"
                    for d in dups
                )
            )

        notes = st.text_area("Notas (opcional)", "")
        c1, c2, c3 = st.columns([1, 1, 4])
        if c1.button("✅ Aprobar → Lark", type="primary"):
            try:
                result = approve_to_lark(handle_pick)
                st.success(f"Aprobada y pusheada a Lark Creadoras IG: {result.get('record_id')}")
                if notes:
                    set_candidate_status(handle_pick, "approved", notes)
                st.rerun()
            except Exception as e:
                st.error(f"Lark push falló: {e}")
        if c2.button("❌ Rechazar"):
            with db.connect() as conn:
                conn.execute(
                    "UPDATE candidates SET status='rejected', rejected_reason=? WHERE handle=?",
                    (notes or None, handle_pick),
                )
            st.success("Rechazada")
            st.rerun()


# ============================================================
# PAGE: Buscar perfil directo (lookup por handle)
# ============================================================
def page_profile_lookup() -> None:
    st.header(":material/person_search: Stalkear perfil")
    st.caption("Búsqueda directa: pega un handle de IG, te devuelve toda la info del perfil "
               "+ una recomendación de tipo de colaboración basada en sus métricas.")

    col1, col2 = st.columns([3, 1])
    handle_input = col1.text_input("Handle de Instagram (con o sin @)",
                                   placeholder="ejemplo: marthafer23")
    col2.write("")  # spacer
    col2.write("")
    go = col2.button("🔍 Analizar perfil", type="primary", use_container_width=True)

    st.caption("💰 Cada análisis cuesta ~$0.02-0.04 USD del plan Apify (scrape profile + about + 12 posts).")

    # ============== HISTORIAL GLOBAL DE LOOKUPS ==============
    all_lookups = fetch_df("""
        SELECT lh.id, lh.looked_up_at, lh.handle, lh.full_name, lh.followers,
               lh.engagement_rate, lh.tier, lh.collab_label, lh.collab_type,
               lh.recommended_cash, lh.expected_emv, lh.profile_pic_url
        FROM lookup_history lh
        ORDER BY lh.looked_up_at DESC LIMIT 50
    """)
    if not all_lookups.empty:
        with st.expander(f"📋 Historial de búsquedas ({len(all_lookups)} más recientes)", expanded=False):
            all_lookups["ER %"] = (pd.to_numeric(all_lookups["engagement_rate"], errors="coerce") * 100).round(2)
            all_lookups["Followers"] = all_lookups["followers"].fillna(0).astype(int).map("{:,}".format)
            all_lookups["Cash sug."] = all_lookups["recommended_cash"].fillna(0).astype(int).map("${:,}".format)
            all_lookups["EMV"] = all_lookups["expected_emv"].fillna(0).astype(int).map("${:,}".format)
            all_lookups["Foto"] = all_lookups["profile_pic_url"].apply(_to_image_src)
            display = all_lookups[["Foto", "looked_up_at", "handle", "full_name",
                                    "Followers", "ER %", "tier", "collab_label",
                                    "Cash sug.", "EMV"]]
            display = display.rename(columns={
                "looked_up_at": "Fecha",
                "handle": "Handle",
                "full_name": "Nombre",
                "tier": "Tier",
                "collab_label": "Recomendación",
            })
            st.dataframe(
                display, use_container_width=True, hide_index=True,
                column_config={
                    "Foto": st.column_config.ImageColumn("Foto", width="small"),
                },
            )

    if not go and "last_lookup" not in st.session_state:
        return

    if go and handle_input:
        clean = handle_input.strip().lstrip("@")
        with st.spinner(f"Analizando @{clean}..."):
            result = apify_jobs.lookup_profile(clean)
        if result.get("error"):
            st.error(f"Error: {result['error']}")
            return
        st.session_state.last_lookup = result

        # Persistir snapshot en lookup_history
        cand = result["candidate"]
        pred = result["prediction"]
        try:
            with db.connect() as conn:
                conn.execute("""
                    INSERT INTO lookup_history
                      (handle, full_name, followers, engagement_rate, tier, fit_score,
                       country, gender, account_type, avg_likes, avg_comments,
                       collab_type, collab_label, collab_rationale,
                       expected_emv, recommended_cash, max_cash_investable,
                       profile_pic_url, bio)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    cand.get("handle"), cand.get("full_name"),
                    cand.get("followers"), cand.get("engagement_rate"),
                    cand.get("tier"), cand.get("fit_score"),
                    cand.get("country"), cand.get("gender"),
                    cand.get("account_type"),
                    cand.get("avg_likes"), cand.get("avg_comments"),
                    pred.get("type"), pred.get("label"), pred.get("rationale"),
                    pred.get("expected_emv"), pred.get("recommended_cash"),
                    pred.get("max_cash_investable"),
                    cand.get("profile_pic_url"), cand.get("bio"),
                ))
        except Exception as e:
            st.warning(f"⚠️ No se pudo guardar en historial: {e}")

    result = st.session_state.get("last_lookup")
    if not result:
        return

    cand = result["candidate"]
    pred = result["prediction"]

    st.divider()

    # ===== HERO: foto + identidad =====
    pic_col, info_col = st.columns([1, 3])
    with pic_col:
        pic = _to_image_src(cand.get("profile_pic_url"))
        if pic:
            st.image(pic, width=200)

    with info_col:
        verified = " ✓" if cand.get("is_verified") else ""
        st.markdown(f"### @{cand['handle']}{verified}")
        if cand.get("full_name"):
            st.markdown(f"**{cand['full_name']}**")
        if cand.get("bio"):
            st.markdown(f"_{cand['bio'][:400]}_")
        if cand.get("external_url"):
            st.markdown(f"🔗 [{cand['external_url']}]({cand['external_url']})")
        st.link_button("👁 Abrir IG", ig_url(cand["handle"]))

    st.divider()

    # ===== MÉTRICAS (color-coded vs ideal FelyFit) =====
    st.subheader(":material/analytics: Métricas")

    followers_n = int(cand.get("followers") or 0)
    er = float(cand.get("engagement_rate") or 0)
    tier = cand.get("tier")
    fit = float(cand.get("fit_score") or 0)
    following = int(cand.get("following") or 0)
    country = cand.get("country")
    gender = cand.get("gender")
    acc_type = cand.get("account_type")

    # Tier sublabel: min ER required
    tier_min_er = config.IDEAL_CRITERIA["er_min_by_tier"].get(tier or "micro", 0.025)
    er_sub = f"min para {tier}: {tier_min_er*100:.1f}%"

    m1, m2, m3, m4 = st.columns(4)
    m1.markdown(_colored_metric(
        "Followers", f"{followers_n:,}", _eval_followers(followers_n),
        sublabel="ideal: 10K–100K"
    ), unsafe_allow_html=True)
    m2.markdown(_colored_metric(
        "ER", f"{er*100:.2f}%", _eval_er(er, tier), sublabel=er_sub
    ), unsafe_allow_html=True)
    m3.markdown(_colored_metric(
        "Tier", tier or "?", _eval_tier(tier),
        sublabel="micro/mid = sweet spot"
    ), unsafe_allow_html=True)
    m4.markdown(_colored_metric(
        "Fit Score", f"{fit:.1f}", _eval_fit(fit),
        sublabel="ideal: ≥70"
    ), unsafe_allow_html=True)

    m5, m6, m7, m8 = st.columns(4)
    ff = (followers_n / following) if following > 0 else 0
    country_label = {"MX": "🇲🇽 MX", "US": "🇺🇸 US", "AR": "🇦🇷 AR",
                     "CO": "🇨🇴 CO", "ES": "🇪🇸 ES", "PE": "🇵🇪 PE",
                     "CL": "🇨🇱 CL", "BR": "🇧🇷 BR"}.get(country, "❓")
    gender_label = {"female": "👩 Mujer", "male": "👨 Hombre"}.get(gender, "❓")

    m5.markdown(_colored_metric(
        "Following", f"{following:,}", "neutral"
    ), unsafe_allow_html=True)
    m6.markdown(_colored_metric(
        "F/F ratio", f"{ff:.1f}:1",
        _eval_ff_ratio(followers_n, following),
        sublabel="ideal: ≥10:1"
    ), unsafe_allow_html=True)
    m7.markdown(_colored_metric(
        "País", country_label, _eval_country(country),
        sublabel="ideal: MX"
    ), unsafe_allow_html=True)
    m8.markdown(_colored_metric(
        "Género", gender_label, _eval_gender(gender),
        sublabel="ideal: mujer"
    ), unsafe_allow_html=True)

    m9, m10, m11 = st.columns(3)
    m9.markdown(_colored_metric(
        "Avg Likes", f"{int(cand.get('avg_likes') or 0):,}", "neutral"
    ), unsafe_allow_html=True)
    m10.markdown(_colored_metric(
        "Avg Comments", f"{int(cand.get('avg_comments') or 0):,}", "neutral"
    ), unsafe_allow_html=True)
    m11.markdown(_colored_metric(
        "Tipo cuenta",
        scoring.ACCOUNT_TYPE_LABELS.get(acc_type or "", "?"),
        _eval_account_type(acc_type),
        sublabel="ideal: individual"
    ), unsafe_allow_html=True)
    # spacer
    st.write("")

    if cand.get("inferred_niches"):
        try:
            niches = json.loads(cand["inferred_niches"])
            if niches:
                st.markdown("**Nichos detectados:** " + " · ".join(f"`{n}`" for n in niches))
        except Exception:
            pass

    st.divider()

    # ===== RECOMENDACIÓN INICIAL DEL ALGORITMO =====
    st.subheader(":material/target: Recomendación del algoritmo")
    if pred["type"] in ("no_collab", "skip"):
        st.error(f"### {pred['label']}")
    elif pred["type"] in ("gifted", "intercambio"):
        st.info(f"### {pred['label']}")
    else:
        st.success(f"### {pred['label']}")
    st.markdown(f"**{pred['rationale']}**")
    if pred.get("warnings"):
        for w in pred["warnings"]:
            st.warning(w)

    if pred["type"] == "no_collab":
        return  # no aplica planear escenarios

    st.divider()

    # ===== PLANNER DE ESCENARIO — ajustable manualmente =====
    st.subheader(":material/tune: Planner de escenario")
    st.caption(
        "Ajusta el tipo de collab y qué contenido le pides para ver cómo "
        "cambian EMV y ratios. La recomendación de arriba es solo punto de partida."
    )

    COLLAB_TYPES_USER = ["intercambio", "gifted", "paid_light", "paid_mid",
                          "paid_hero", "monthly_fee"]
    default_collab_idx = (COLLAB_TYPES_USER.index(pred["type"])
                           if pred["type"] in COLLAB_TYPES_USER else 1)

    plan_c1, plan_c2 = st.columns([1, 2])
    with plan_c1:
        chosen_collab_type = st.selectbox(
            "Tipo de colaboración",
            COLLAB_TYPES_USER,
            index=default_collab_idx,
            format_func=lambda t: scoring.COLLAB_TYPE_LABELS[t],
            key=f"plan_collab_{cand['handle']}",
        )

    with plan_c2:
        st.markdown("**Contenido a solicitar** (cantidad de cada tipo)")
        CONTENT_OPTIONS = ["reel", "carousel", "post", "live", "story"]
        cc_cols = st.columns(5)
        content_counts = {}
        for i, ct in enumerate(CONTENT_OPTIONS):
            with cc_cols[i]:
                content_counts[ct] = st.number_input(
                    config.CONTENT_TYPE_LABELS[ct],
                    min_value=0, max_value=20,
                    value=1 if ct == "post" else 0,
                    step=1,
                    key=f"plan_ct_{ct}_{cand['handle']}",
                )

    # Calcular EMV ajustado por contenido
    base_emv = float(pred["expected_emv"] or 0)
    content_multiplier = sum(
        content_counts[ct] * config.CONTENT_TYPE_EMV_MULTIPLIERS[ct]
        for ct in CONTENT_OPTIONS
    )
    adjusted_emv = base_emv * content_multiplier if content_multiplier > 0 else 0

    selected_content_pieces = [
        f"{n}×{config.CONTENT_TYPE_LABELS[ct]}"
        for ct, n in content_counts.items() if n > 0
    ]
    if selected_content_pieces:
        st.caption(
            "📦 Paquete contenido: " + " + ".join(selected_content_pieces) +
            f"  ·  Multiplier total: **{content_multiplier:.2f}×** base EMV"
        )
    else:
        st.warning("Selecciona al menos un tipo de contenido para calcular EMV.")

    st.divider()

    # ===== BREAKDOWN DE COSTO — EDITABLE =====
    st.subheader(":material/receipt_long: Breakdown del paquete (editable)")
    st.caption("Ajusta variables para recalcular ratios según términos finales.")

    if chosen_collab_type == pred["type"]:
        default_cash = float(pred["recommended_cash"] or 0)
    else:
        cash_by_type = {
            "intercambio": 0,
            "gifted": 0,
            "paid_light": 3000,
            "paid_mid": 12000,
            "paid_hero": 40000,
            "monthly_fee": 20000,
        }
        default_cash = float(cash_by_type.get(chosen_collab_type, 0))

    default_cogs = float(config.STANDARD_PR_PACK_COGS_MXN)
    default_shipping = 150.0

    bd_col1, bd_col2 = st.columns(2)
    with bd_col1:
        st.markdown("**Inversión (MXN):**")
        cogs = st.number_input(
            "COGS PR pack", min_value=0.0, value=default_cogs, step=10.0,
            key=f"lookup_cogs_{cand['handle']}",
            help=f"Default: ${default_cogs:.2f} (estándar FelyFit).",
        )
        shipping_est = st.number_input(
            "Shipping estimate", min_value=0.0, value=default_shipping, step=10.0,
            key=f"lookup_ship_{cand['handle']}",
            help="Costo de envío estimado. Ajusta según zona / paquetería.",
        )
        cash = st.number_input(
            "Cash fee", min_value=0.0, value=default_cash, step=100.0,
            key=f"lookup_cash_{cand['handle']}_{chosen_collab_type}",
            help=f"Default sugerido para '{chosen_collab_type}': ${default_cash:,.0f}.",
        )
        total_invest = cogs + shipping_est + cash
        st.markdown(f"**Total inversión: ${total_invest:,.2f} MXN**")

    with bd_col2:
        st.markdown("**Resultados proyectados:**")
        cash_denom = max(cash + shipping_est, 1)
        total_denom = max(cash + shipping_est + cogs, 1)
        cash_ratio = adjusted_emv / cash_denom if cash > 0 else float("inf")
        total_ratio = adjusted_emv / total_denom
        cash_ratio_str = "∞" if cash == 0 else f"{cash_ratio:.2f}:1"

        r1, r2 = st.columns(2)
        emv_delta = (f"vs base ${base_emv:,.0f}"
                      if content_multiplier and content_multiplier != 1 else None)
        r1.metric("EMV ajustado", f"${adjusted_emv:,.0f}",
                  delta=emv_delta,
                  help=f"EMV base × {content_multiplier:.2f} (suma multipliers)")
        r2.metric("Total inversión", f"${total_invest:,.0f}")

        r3, r4 = st.columns(2)
        r3.metric("Cash ratio", cash_ratio_str,
                  help="EMV / (cash + shipping). Ignora COGS.")
        r4.metric("Total ratio", f"{total_ratio:.2f}:1",
                  help="EMV / (cash + shipping + COGS).")

        target = config.EMV_TARGET_RATIO
        if adjusted_emv == 0:
            st.info("Sin contenido seleccionado, no hay EMV proyectado.")
        elif total_ratio >= target:
            st.success(f"✅ Cumple target {target}:1 — escenario rentable.")
        else:
            min_emv_needed = total_denom * target
            max_invest_allowed = adjusted_emv / target
            st.warning(
                f"⚠️ Debajo de target {target}:1. "
                f"Necesitas EMV ≥ ${min_emv_needed:,.0f} "
                f"o bajar inversión a ≤ ${max_invest_allowed:,.0f}."
            )

    # ===== DESCARGAR INFOGRAFÍA DEL ESCENARIO =====
    st.divider()
    st.markdown("**:material/image: Compartir con el equipo**")
    st.caption("Descarga una infografía PNG con el escenario actual — "
               "lista para mandar por Slack/WhatsApp/email.")
    try:
        png_bytes = lookup_infographic.generate(
            cand, pred,
            chosen_collab_type=chosen_collab_type,
            chosen_collab_label=scoring.COLLAB_TYPE_LABELS.get(chosen_collab_type),
            content_counts=content_counts,
            content_multiplier=content_multiplier,
            adjusted_emv=adjusted_emv,
            cogs=cogs, shipping=shipping_est, cash=cash,
            target_ratio=config.EMV_TARGET_RATIO,
            local_pic_path=cand.get("profile_pic_url"),
        )
        st.download_button(
            ":material/download: Descargar infografía PNG",
            data=png_bytes,
            file_name=f"stalker_{cand['handle']}_{datetime.now().strftime('%Y%m%d_%H%M')}.png",
            mime="image/png",
            type="primary",
            use_container_width=True,
        )
    except Exception as e:
        st.error(f"No se pudo generar la imagen: {e}")

    st.divider()

    # ===== HISTORIAL DE LOOKUPS PREVIOS DE ESTE HANDLE =====
    history = fetch_df("""
        SELECT looked_up_at, followers, engagement_rate, tier, fit_score,
               collab_type, collab_label, recommended_cash, expected_emv
        FROM lookup_history WHERE handle=?
        ORDER BY looked_up_at DESC LIMIT 10
    """, (cand["handle"],))
    if len(history) > 1:
        with st.expander(f"📈 Historial de lookups previos de @{cand['handle']} ({len(history)})"):
            for _, row in history.iterrows():
                st.markdown(
                    f"- **{row['looked_up_at']}** · "
                    f"{int(row['followers'] or 0):,} followers · "
                    f"ER {float(row['engagement_rate'] or 0)*100:.1f}% · "
                    f"tier `{row['tier']}` · "
                    f"recomendación: {row['collab_label'] or row['collab_type'] or '?'}"
                )


# ============================================================
# Detalle de un scout run — lista de candidatas + estado actual
# ============================================================
def _render_scout_detail_multi(run_ids: List[int], label: str) -> None:
    """Detalle de uno o varios runs (ej. theme scout = N hashtags agrupados).
    Muestra todas las candidatas en UNA tabla con columna 'Encontrada en'."""
    st.markdown("---")
    cols = st.columns([6, 1])
    cols[0].subheader(f"📋 Detalle: {label}")
    if cols[1].button("✕ Cerrar detalle", key="close_detail"):
        st.session_state.pop("scout_detail_key", None)
        st.session_state.pop("scout_detail_run_ids", None)
        st.session_state.pop("scout_detail_label", None)
        st.rerun()

    if not run_ids:
        st.info("Sin runs.")
        return

    placeholders = ",".join(["?"] * len(run_ids))
    candidates = fetch_df(f"""
        SELECT c.handle, c.full_name, c.profile_pic_url, c.followers, c.engagement_rate,
               c.tier, c.fit_score, c.account_type, c.country, c.gender, c.status,
               c.filter_reason, c.lark_record_id, c.source_detail
        FROM candidates c WHERE c.scout_run_id IN ({placeholders})
          AND c.status != 'auto_rejected'
        ORDER BY
            CASE c.status
                WHEN 'approved' THEN 1
                WHEN 'contacted' THEN 2
                WHEN 'discovered' THEN 3
                WHEN 'paused' THEN 4
                WHEN 'rejected' THEN 5
                ELSE 6 END,
            c.fit_score DESC NULLS LAST
    """, tuple(run_ids))

    auto_rej_count = fetch_df(
        f"SELECT COUNT(*) as n FROM candidates WHERE scout_run_id IN ({placeholders}) "
        f"AND status='auto_rejected'",
        tuple(run_ids)
    ).iloc[0]["n"]

    total_cost = fetch_df(
        f"SELECT SUM(apify_compute_usd) as c FROM scout_runs WHERE id IN ({placeholders})",
        tuple(run_ids)
    ).iloc[0]["c"]
    total_cost = float(total_cost or 0)

    if candidates.empty:
        if auto_rej_count > 0:
            st.info(f"❌ {int(auto_rej_count)} candidatas auto-rechazadas (no cumplen parámetros). "
                    "Ninguna pasó los filtros.")
        else:
            st.info("Sin candidatas.")
        return

    # Resumen
    by_status = candidates["status"].value_counts().to_dict()
    summary_cols = st.columns(5)
    summary_cols[0].metric("✅ APTAS", len(candidates))
    summary_cols[1].metric("📋 Pendientes", by_status.get("discovered", 0))
    summary_cols[2].metric("✅ Aprobadas",
                           by_status.get("approved", 0) + by_status.get("contacted", 0))
    summary_cols[3].metric("🔖 Pausadas", by_status.get("paused", 0))
    summary_cols[4].metric("Costo", f"${total_cost:.4f}")

    if auto_rej_count > 0:
        st.caption(f"ℹ️ Además, {int(auto_rej_count)} candidatas fueron filtradas automáticamente "
                   "(no se muestran).")

    # Tabla con columna 'Encontrada en' (source_detail = hashtag)
    candidates["Foto"] = candidates["profile_pic_url"].apply(_to_image_src)
    candidates["engagement_rate"] = pd.to_numeric(candidates["engagement_rate"], errors="coerce")
    candidates["fit_score"] = pd.to_numeric(candidates["fit_score"], errors="coerce")
    candidates["ER %"] = (candidates["engagement_rate"] * 100).round(2)
    candidates["Followers"] = candidates["followers"].fillna(0).astype(int).map("{:,}".format)
    candidates["Fit"] = candidates["fit_score"].round(1)
    candidates["IG"] = candidates["handle"].apply(ig_url)

    STATUS_LABELS = {
        "discovered":   "📋 Pendiente", "approved": "✅ Aprobada",
        "contacted":    "✅ Contacted", "active": "✅ Active",
        "paused":       "🔖 Pausada", "rejected": "❌ Rechazada",
        "auto_rejected": "❌ Auto-rechazada", "declined": "❌ Declinada",
    }
    candidates["Estado"] = candidates["status"].map(lambda s: STATUS_LABELS.get(s, s))
    candidates["Encontrada en"] = candidates["source_detail"]
    GENDER_EMOJI = {"female": "👩", "male": "👨"}
    candidates["G"] = candidates["gender"].map(lambda g: GENDER_EMOJI.get(g, "❓") if g else "❓")

    display = candidates[["Foto", "handle", "full_name", "G", "Estado", "Followers",
                          "ER %", "tier", "Fit", "country", "Encontrada en", "IG"]]
    st.dataframe(
        display, use_container_width=True, hide_index=True,
        column_config={
            "Foto": st.column_config.ImageColumn("Foto", width="small"),
            "IG": st.column_config.LinkColumn("Perfil IG", display_text="abrir →"),
            "G": st.column_config.TextColumn("👤", width="small", help="Género detectado"),
        },
    )


def _render_scout_detail(run_id: int) -> None:
    st.markdown("---")
    run_info = fetch_df("SELECT * FROM scout_runs WHERE id=?", (run_id,))
    if run_info.empty:
        st.error("Scout run no encontrado.")
        return
    r = run_info.iloc[0]

    cols = st.columns([6, 1])
    cols[0].subheader(f"📋 Detalle: {r['source_detail']} · {r['started_at']}")
    if cols[1].button("✕ Cerrar detalle"):
        del st.session_state["scout_detail_run_id"]
        st.rerun()

    # Aptas = las que pasaron filtros (discovered/paused/approved/contacted/rejected_by_user)
    # Auto_rejected = las que no cumplieron parametros (no las mostramos por default)
    candidates = fetch_df("""
        SELECT handle, full_name, profile_pic_url, followers, engagement_rate,
               tier, fit_score, account_type, country, status, filter_reason,
               lark_record_id
        FROM candidates WHERE scout_run_id=?
          AND status != 'auto_rejected'
        ORDER BY
            CASE status
                WHEN 'approved' THEN 1
                WHEN 'contacted' THEN 2
                WHEN 'discovered' THEN 3
                WHEN 'paused' THEN 4
                WHEN 'rejected' THEN 5
                ELSE 6 END,
            fit_score DESC NULLS LAST
    """, (run_id,))

    auto_rej_count = fetch_df(
        "SELECT COUNT(*) as n FROM candidates WHERE scout_run_id=? AND status='auto_rejected'",
        (int(run_id),)
    ).iloc[0]["n"]

    if candidates.empty:
        deleted_count = int(r["candidates_new"] or 0)
        if deleted_count > 0 and auto_rej_count == 0:
            st.warning(
                f"Este run encontró {deleted_count} candidatas pero no quedan registros. "
                "Probablemente fueron borradas antes de implementar el audit trail."
            )
        elif auto_rej_count > 0:
            st.info(f"❌ {int(auto_rej_count)} candidatas auto-rechazadas (no cumplieron parámetros). "
                    "Ninguna pasó los filtros.")
        else:
            st.info("Sin candidatas en este run.")
        return

    # Resumen — solo las APTAS (las que pediste ver)
    by_status = candidates["status"].value_counts().to_dict()
    summary_cols = st.columns(5)
    summary_cols[0].metric("✅ APTAS", len(candidates),
                           help="Candidatas que pasaron tus filtros y que pediste ver")
    summary_cols[1].metric("📋 Pendientes", by_status.get("discovered", 0))
    summary_cols[2].metric("✅ Aprobadas",
                           by_status.get("approved", 0) + by_status.get("contacted", 0))
    summary_cols[3].metric("🔖 Pausadas", by_status.get("paused", 0))
    summary_cols[4].metric("Costo", f"${float(r['apify_compute_usd'] or 0):.4f}")

    if auto_rej_count > 0:
        st.caption(f"ℹ️ Además, {int(auto_rej_count)} candidatas fueron filtradas automáticamente "
                   "por no cumplir parámetros (no se muestran aquí).")

    # Tabla
    candidates["Foto"] = candidates["profile_pic_url"].apply(_to_image_src)
    candidates["engagement_rate"] = pd.to_numeric(candidates["engagement_rate"], errors="coerce")
    candidates["fit_score"] = pd.to_numeric(candidates["fit_score"], errors="coerce")
    candidates["ER %"] = (candidates["engagement_rate"] * 100).round(2)
    candidates["Followers"] = candidates["followers"].fillna(0).astype(int).map("{:,}".format)
    candidates["Fit"] = candidates["fit_score"].round(1)
    candidates["IG"] = candidates["handle"].apply(ig_url)
    candidates["Razón"] = candidates["filter_reason"].fillna("")

    STATUS_LABELS = {
        "discovered":   "📋 Pendiente",
        "approved":     "✅ Aprobada",
        "contacted":    "✅ Contacted",
        "active":       "✅ Active",
        "paused":       "🔖 Pausada",
        "rejected":     "❌ Rechazada (Lucy)",
        "auto_rejected": "❌ Auto-rechazada",
        "declined":     "❌ Declinada",
    }
    candidates["Estado"] = candidates["status"].map(lambda s: STATUS_LABELS.get(s, s))

    display = candidates[["Foto", "handle", "full_name", "Estado", "Followers",
                          "ER %", "tier", "Fit", "account_type", "country",
                          "Razón", "IG"]]
    st.dataframe(
        display, use_container_width=True, hide_index=True,
        column_config={
            "Foto": st.column_config.ImageColumn("Foto", width="small"),
            "IG": st.column_config.LinkColumn("Perfil IG", display_text="abrir →"),
        },
    )


# ============================================================
# PAGE: Tinder Review — una candidata a la vez
# ============================================================
def page_tinder() -> None:
    st.header(":material/swipe: Felynder")

    # Top razones de descarte (últimos 30 días) — para detectar patrones
    # que valga la pena automatizar en el filtro.
    reasons_df = fetch_df("""
        SELECT
          -- Tomar solo la razón principal (antes del " — ")
          CASE
            WHEN INSTR(rejected_reason, ' — ') > 0
              THEN SUBSTR(rejected_reason, 1, INSTR(rejected_reason, ' — ') - 1)
            ELSE rejected_reason
          END AS razon,
          COUNT(*) AS n
        FROM candidates
        WHERE status='rejected' AND rejected_reason IS NOT NULL
          AND rejected_reason != ''
        GROUP BY razon
        ORDER BY n DESC
    """)
    if not reasons_df.empty:
        total = int(reasons_df["n"].sum())
        with st.expander(f"📊 Razones de descarte ({total} totales) — qué pulir en el filtro", expanded=False):
            for _, r in reasons_df.iterrows():
                pct = (r["n"] / total) * 100
                st.markdown(f"- **{r['razon']}** · {int(r['n'])} ({pct:.0f}%)")
            st.caption("Si una razón pasa del 30% considera automatizarla en el auto_reject.")

    # Contar pendientes y pausadas para los tabs
    n_pending = fetch_df(
        "SELECT COUNT(*) as n FROM candidates WHERE status='discovered' "
        "AND lark_record_id IS NULL AND source != 'lark_import' "
        "AND last_enriched_at IS NOT NULL"
    ).iloc[0]["n"]
    n_paused = fetch_df(
        "SELECT COUNT(*) as n FROM candidates WHERE status='paused' "
        "AND lark_record_id IS NULL AND source != 'lark_import'"
    ).iloc[0]["n"]

    tabs = st.tabs([f"📋 Por revisar ({int(n_pending)})", f"🔖 Pausadas ({int(n_paused)})"])

    with tabs[0]:
        _tinder_queue(default_status="discovered", queue_key="pending")
    with tabs[1]:
        _tinder_queue(default_status="paused", queue_key="paused")


def _tinder_queue(default_status: str, queue_key: str) -> None:
    # Tinder = revision de pendientes nuevas SOLAMENTE.
    # Para ver historial de un scout, usa "📋 Ver candidatas" en la pestaña Scouting.
    scout_run_filter = None

    with st.expander("🔎 Filtros adicionales", expanded=False):
        c2, c3 = st.columns(2)
        f_country = c2.multiselect(
            "Países", ["MX", "US", "AR", "CO", "ES", "PE", "CL", "BR", "UNKNOWN"],
            default=["MX", "UNKNOWN"], key=f"f_country_{queue_key}",
            help="Default MX + UNKNOWN. UNKNOWN = país no detectable.",
        )
        f_tier = c3.multiselect(
            "Tier", ["nano", "micro", "mid", "macro", "mega"],
            default=["nano", "micro", "mid", "macro", "mega"], key=f"f_tier_{queue_key}",
        )
        c4, c5 = st.columns(2)
        f_er_min = c4.slider("ER mínimo (%)", 0.0, 20.0, 0.0, 0.5,
                             key=f"f_er_{queue_key}") / 100
        f_fit_min = c5.slider("Fit Score mínimo", 0.0, 100.0, 0.0, 5.0,
                              key=f"f_fit_{queue_key}")
    f_status = default_status

    # Construir WHERE dinamicamente
    wheres = ["status=?", "lark_record_id IS NULL", "source != 'lark_import'"]
    if default_status == "discovered":
        wheres.append("last_enriched_at IS NOT NULL")
    params = [f_status]
    if f_tier:
        wheres.append("tier IN (" + ",".join("?" * len(f_tier)) + ")")
        params.extend(f_tier)
    if f_er_min > 0:
        wheres.append("engagement_rate >= ?")
        params.append(f_er_min)
    if f_fit_min > 0:
        wheres.append("fit_score >= ?")
        params.append(f_fit_min)
    # Filtro de país: incluir si está en lista, o si está en UNKNOWN y user permite UNKNOWN
    if f_country:
        country_set = [c for c in f_country if c != "UNKNOWN"]
        unknown_allowed = "UNKNOWN" in f_country
        if country_set and unknown_allowed:
            wheres.append(
                f"(country IN ({','.join('?' * len(country_set))}) OR country IS NULL)"
            )
            params.extend(country_set)
        elif country_set:
            wheres.append("country IN (" + ",".join("?" * len(country_set)) + ")")
            params.extend(country_set)
        elif unknown_allowed:
            wheres.append("country IS NULL")

    where_sql = " AND ".join(wheres)

    queue = fetch_df(f"""
        SELECT handle, full_name, bio, followers, following, engagement_rate, tier,
               fit_score, contact_email, profile_pic_url, external_url, estimated_city,
               filter_verdict, filter_reason, source, source_detail, last_post_at,
               avg_likes, avg_comments, inferred_niches, is_verified, account_type,
               country, scout_run_id
        FROM candidates
        WHERE {where_sql}
        ORDER BY fit_score DESC NULLS LAST, followers DESC NULLS LAST
        LIMIT 500
    """, tuple(params))

    if queue.empty:
        st.success("🎉 No hay candidatas que coincidan con estos filtros.")
        return

    st.caption(f"**{len(queue)}** candidatas en cola · {f_status}")

    # Indice persistente en session_state (separado por cola)
    idx_key = f"tinder_idx_{queue_key}"
    if idx_key not in st.session_state:
        st.session_state[idx_key] = 0

    idx = st.session_state[idx_key]
    if idx >= len(queue):
        st.session_state[idx_key] = 0
        idx = 0

    cand = queue.iloc[idx]
    total = len(queue)

    st.progress((idx + 1) / total, text=f"Candidata {idx + 1} de {total}")

    # Layout de la card
    pic_col, info_col = st.columns([1, 2])
    with pic_col:
        if cand.get("profile_pic_url"):
            try:
                st.image(cand["profile_pic_url"], width=280)
            except Exception:
                st.write("(foto expirada — abre el link de IG)")
        else:
            st.write("(sin foto)")

    with info_col:
        verified = "  ✓" if cand.get("is_verified") else ""
        st.markdown(f"### @{cand['handle']}{verified}")
        if cand.get("full_name"):
            st.markdown(f"**{cand['full_name']}**")

        # Tipo de cuenta + Veredicto badges
        atype = cand.get("account_type") or "unknown"
        atype_label = scoring.ACCOUNT_TYPE_LABELS.get(atype, atype)
        v = cand.get("filter_verdict")
        if v == "pass":
            st.success(f"{atype_label}  ·  ✅ Sistema sugiere: APROBAR  ·  {cand.get('filter_reason', '')}")
        elif v == "borderline":
            st.warning(f"{atype_label}  ·  ⚠️ Sistema sugiere: REVISAR  ·  {cand.get('filter_reason', '')}")
        else:
            st.info(f"{atype_label}")

        # Métricas grandes — color-coded vs ideal FelyFit
        followers = int(cand["followers"] or 0)
        er = float(cand["engagement_rate"] or 0)
        tier = cand.get("tier")
        following = int(cand["following"] or 0)
        ff = (followers / following) if following > 0 else 0
        country_label = {"MX": "🇲🇽 MX", "US": "🇺🇸 US", "AR": "🇦🇷 AR",
                         "CO": "🇨🇴 CO", "ES": "🇪🇸 ES", "PE": "🇵🇪 PE",
                         "CL": "🇨🇱 CL", "BR": "🇧🇷 BR"}.get(cand.get("country"), "❓")

        m1, m2, m3, m4 = st.columns(4)
        m1.markdown(_colored_metric(
            "Followers", f"{followers:,}", _eval_followers(followers)
        ), unsafe_allow_html=True)
        m2.markdown(_colored_metric(
            "ER", f"{er*100:.2f}%", _eval_er(er, tier)
        ), unsafe_allow_html=True)
        m3.markdown(_colored_metric(
            "Tier", tier or "?", _eval_tier(tier)
        ), unsafe_allow_html=True)
        m4.markdown(_colored_metric(
            "Fit", f"{float(cand['fit_score'] or 0):.1f}",
            _eval_fit(float(cand["fit_score"] or 0))
        ), unsafe_allow_html=True)

        m5, m6, m7, m8 = st.columns(4)
        m5.markdown(_colored_metric(
            "Following", f"{following:,}", "neutral"
        ), unsafe_allow_html=True)
        m6.markdown(_colored_metric(
            "F/F ratio", f"{ff:.1f}:1",
            _eval_ff_ratio(followers, following)
        ), unsafe_allow_html=True)
        m7.markdown(_colored_metric(
            "País", country_label, _eval_country(cand.get("country"))
        ), unsafe_allow_html=True)
        m8.markdown(_colored_metric(
            "Ciudad", cand.get("estimated_city") or "?", "neutral"
        ), unsafe_allow_html=True)
        st.write("")

    # Bio y nichos
    if cand.get("bio"):
        st.markdown(f"**Bio:** {cand['bio']}")

    if cand.get("inferred_niches"):
        try:
            niches = json.loads(cand["inferred_niches"])
            if niches:
                st.markdown("**Nichos detectados:** " + " · ".join(f"`{n}`" for n in niches))
        except Exception:
            pass

    # Promedios de engagement
    if cand.get("avg_likes") or cand.get("avg_comments"):
        st.caption(
            f"Promedio últimos posts: {int(cand.get('avg_likes') or 0):,} likes · "
            f"{int(cand.get('avg_comments') or 0):,} comments"
        )

    # Source
    st.caption(f"Origen: {cand.get('source')} → {cand.get('source_detail', '')}")

    # Posibles duplicados
    dups = find_possible_dups(cand["handle"], cand.get("full_name"))
    if dups:
        st.warning(f"⚠️ Posible duplicada: " + ", ".join(f"@{d['handle']}" for d in dups[:3]))

    st.divider()

    # Si hay un reject pendiente para ESTA candidata, mostrar form de razón
    # en lugar de los botones normales. El form alimenta al algoritmo:
    # patrones que se repiten nos dicen qué tunear en el filtro.
    reject_flag_key = f"pending_reject_{queue_key}"
    pending_handle = st.session_state.get(reject_flag_key)

    if pending_handle == cand["handle"]:
        st.markdown(f"### ❌ ¿Por qué descartas a @{cand['handle']}?")
        st.caption("Tu respuesta alimenta el algoritmo — los patrones repetidos nos dicen "
                   "qué tunear (niche, country, account_type, etc.).")
        reason = st.selectbox(
            "Razón principal", REJECT_REASONS,
            key=f"reason_select_{queue_key}_{cand['handle']}",
        )
        notes = st.text_input(
            "Notas (opcional)", placeholder="contexto adicional…",
            key=f"reason_notes_{queue_key}_{cand['handle']}",
        )
        c1, c2 = st.columns([2, 1])
        if c1.button("Confirmar descarte", type="primary", use_container_width=True,
                     key=f"confirm_reject_{queue_key}_{cand['handle']}"):
            full_reason = reason + (f" — {notes}" if notes.strip() else "")
            with db.connect() as conn:
                conn.execute(
                    "UPDATE candidates SET status='rejected', rejected_reason=? WHERE handle=?",
                    (full_reason, cand["handle"]),
                )
            st.session_state.pop(reject_flag_key, None)
            st.session_state[idx_key] = idx  # queue se acorta sola
            st.rerun()
        if c2.button("Cancelar", use_container_width=True,
                     key=f"cancel_reject_{queue_key}_{cand['handle']}"):
            st.session_state.pop(reject_flag_key, None)
            st.rerun()
    else:
        # Botones normales (Tinder style)
        b1, b2, b3, b4, b5 = st.columns([1, 1, 1, 1, 1])

        if b1.button("❌ Descartar", use_container_width=True,
                     key=f"reject_{queue_key}_{cand['handle']}"):
            st.session_state[reject_flag_key] = cand["handle"]
            st.rerun()

        if b2.button("🔖 Para después", use_container_width=True,
                     key=f"pause_{queue_key}_{cand['handle']}"):
            with db.connect() as conn:
                conn.execute("UPDATE candidates SET status='paused' WHERE handle=?", (cand["handle"],))
            st.session_state[idx_key] = idx
            st.rerun()

        if b3.button("⏭ Pasar (siguiente)", use_container_width=True,
                     key=f"skip_{queue_key}_{cand['handle']}"):
            st.session_state[idx_key] = idx + 1
            st.rerun()

        if b4.button("✅ Aprobar → Lark", use_container_width=True, type="primary",
                     key=f"approve_{queue_key}_{cand['handle']}"):
            try:
                result = approve_to_lark(cand["handle"])
                st.success(f"Aprobada y pusheada a Lark: {result.get('record_id')}")
                st.session_state[idx_key] = idx
                st.rerun()
            except Exception as e:
                st.error(f"Lark push falló: {e}")

        b5.link_button("👁 Abrir IG", ig_url(cand["handle"]), use_container_width=True)


# ============================================================
# PAGE: Pipeline
# ============================================================
def page_pipeline() -> None:
    st.header(":material/view_kanban: The chosen ones")

    search_q = st.text_input(
        "🔍 Buscar por handle o nombre",
        placeholder="ej. @marianafit o Mariana",
        key="pipeline_search",
    ).strip()

    status_options = ["(todas)", "discovered", "approved", "contacted", "responded",
                      "negotiating", "active", "declined", "rejected", "paused"]
    col_s, col_t, col_e = st.columns(3)
    sel = col_s.selectbox("Status", status_options)
    tier_filter = col_t.selectbox("Tier", ["(todos)", "nano", "micro", "mid", "macro", "mega"])
    enrich_filter = col_e.selectbox("Enriquecidas", ["(todas)", "solo enriquecidas", "solo SIN enriquecer"])

    # auto_rejected siempre fuera de la vista — el sistema las recuerda
    # internamente (en la misma tabla) para no re-mostrarlas en el scout,
    # pero no son contenido relevante para Lucy en el pipeline.
    wheres = ["status != 'auto_rejected'"]
    params = []
    if search_q:
        # Match contra handle O full_name, case-insensitive. Permite "@handle" o "handle".
        q = search_q.lstrip("@").lower()
        wheres.append("(LOWER(handle) LIKE ? OR LOWER(COALESCE(full_name,'')) LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])
    if sel != "(todas)":
        wheres.append("status=?")
        params.append(sel)
    if tier_filter != "(todos)":
        wheres.append("tier=?")
        params.append(tier_filter)
    if enrich_filter == "solo enriquecidas":
        wheres.append("last_enriched_at IS NOT NULL")
    elif enrich_filter == "solo SIN enriquecer":
        wheres.append("last_enriched_at IS NULL")

    where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""
    df = fetch_df(f"""
        SELECT handle, full_name, status, followers, engagement_rate, tier, fit_score,
               contact_email, estimated_city, lark_record_id, source, profile_pic_url,
               last_enriched_at
        FROM candidates {where_sql}
        ORDER BY fit_score DESC NULLS LAST, followers DESC NULLS LAST, discovered_at DESC
        LIMIT 500
    """, tuple(params))

    if df.empty:
        st.info("Sin resultados.")
        return

    df["engagement_rate"] = pd.to_numeric(df["engagement_rate"], errors="coerce")
    df["fit_score"] = pd.to_numeric(df["fit_score"], errors="coerce")
    df["ER %"] = (df["engagement_rate"] * 100).round(2)
    df["Followers"] = df["followers"].fillna(0).astype(int).map("{:,}".format)
    df["En Lark"] = df["lark_record_id"].notna().map({True: "✅", False: ""})
    df["Fit"] = df["fit_score"].round(1)
    df["IG"] = df["handle"].apply(ig_url)

    df["Foto"] = df["profile_pic_url"].apply(_to_image_src)
    display = df[["Foto", "handle", "full_name", "status", "Followers", "ER %", "tier", "Fit",
                  "estimated_city", "En Lark", "IG"]]
    st.dataframe(
        display, use_container_width=True, hide_index=True,
        column_config={
            "Foto": st.column_config.ImageColumn("Foto", width="small"),
            "IG": st.column_config.LinkColumn("Perfil IG", display_text="abrir →"),
        },
    )
    st.caption(f"{len(df)} registros · "
               f"{int(df['last_enriched_at'].notna().sum())} enriquecidas con Apify")
    st.caption(f"{len(df)} registros")


# ============================================================
# PAGE: Collabs
# ============================================================
def page_collabs() -> None:
    st.header(":material/handshake: Collabs")

    with st.expander("➕ Registrar collab nueva", expanded=False):
        eligible = fetch_df(
            "SELECT handle, full_name, followers, tier FROM candidates "
            "WHERE status IN ('approved','responded','negotiating','active') "
            "ORDER BY handle"
        )
        if eligible.empty:
            st.info("No hay candidatas elegibles (aprobadas o en pipeline).")
        else:
            handle_opts = eligible["handle"].tolist()
            handle = st.selectbox("Creadora", handle_opts,
                                  format_func=lambda h: f"@{h}  ({eligible[eligible['handle']==h]['tier'].iloc[0] or '?'})")
            campaign_name = st.text_input("Campaign name")
            campaign_type = st.selectbox("Tipo", ["gifted", "paid_light", "paid_mid", "paid_hero", "hybrid_event"])

            col1, col2, col3 = st.columns(3)
            cogs = col1.number_input("COGS pieces (MXN)", value=config.STANDARD_PR_PACK_COGS_MXN, step=10.0)
            shipping = col2.number_input("Shipping (MXN)", value=0.0, step=10.0)
            cash_fee = col3.number_input("Cash fee (MXN)", value=0.0, step=500.0)

            col4, col5 = st.columns(2)
            usage = col4.number_input("Usage rights (MXN)", value=0.0, step=500.0)
            agency = col5.number_input("Agency fee (MXN)", value=0.0, step=500.0)

            launch = st.date_input("Launch date", value=datetime.now().date())

            if st.button("Registrar collab", type="primary"):
                with db.connect() as conn:
                    conn.execute("""
                        INSERT INTO collabs (handle, campaign_name, campaign_type,
                            cogs_pieces, retail_pieces, shipping_cost, cash_fee,
                            usage_rights_fee, agency_fee, launch_date, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                    """, (handle, campaign_name, campaign_type, cogs, config.STANDARD_PR_PACK_RETAIL_MXN,
                          shipping, cash_fee, usage, agency, launch.isoformat()))
                st.success("Collab registrada. Agrega URLs de posts cuando publique.")
                st.rerun()

    st.subheader("Collabs registradas")
    collabs = fetch_df("""
        SELECT id, handle, campaign_name, campaign_type, launch_date, status,
               cogs_pieces, cash_fee, shipping_cost,
               emv_mxn, emv_cash_ratio, emv_total_ratio, last_recalc_at
        FROM collabs ORDER BY created_at DESC
    """)
    if collabs.empty:
        st.info("Aun no hay collabs registradas.")
        return

    for col in ("emv_cash_ratio", "emv_total_ratio", "emv_mxn"):
        collabs[col] = pd.to_numeric(collabs[col], errors="coerce")
    collabs["Cash Ratio"] = collabs["emv_cash_ratio"].round(2)
    collabs["Total Ratio"] = collabs["emv_total_ratio"].round(2)
    collabs["EMV"] = collabs["emv_mxn"].round(0)
    display = collabs[["id", "handle", "campaign_name", "campaign_type", "launch_date", "status",
                       "EMV", "Cash Ratio", "Total Ratio", "last_recalc_at"]]
    st.dataframe(display, use_container_width=True, hide_index=True)

    st.caption(f"Target Total Ratio: {config.EMV_TARGET_RATIO}:1 · "
               "Las que estén por debajo deberían disparar revisión.")


# ============================================================
# PAGE: Settings
# ============================================================
def page_settings() -> None:
    st.header(":material/settings: The rules")

    # Panel admin para códigos de acceso (solo visible si is_admin)
    if auth.is_admin():
        auth.admin_codes_panel()
        st.divider()

    st.subheader("PR Pack — COGS estándar")
    st.metric("COGS (MXN)", f"${config.STANDARD_PR_PACK_COGS_MXN:.2f}")
    st.caption("Breakdown: empaque $69.80 + legging $150 + legging $200 + 3 calcetas $50")

    st.subheader("EMV — Multiplicadores (MXN por evento)")
    cols = st.columns(3)
    for i, (k, v) in enumerate(config.EMV_MULTIPLIERS.items()):
        cols[i % 3].metric(k, f"${v:.2f}")

    st.subheader("Post value por tier (MXN)")
    cols = st.columns(5)
    for i, (k, v) in enumerate(config.POST_VALUE_BY_TIER_MXN.items()):
        cols[i].metric(k, f"${v:,}")

    st.caption("⚠️ Para editar en vivo: por ahora se cambia en config.py y se reinicia la app. "
               "v2 vamos a hacerlo editable desde aquí con persistencia en tabla `config`.")

    st.subheader("Criterio de candidata ideal (filtros estrictos)")
    c = config.IDEAL_CRITERIA

    st.markdown("**Followers**")
    cols = st.columns(2)
    cols[0].metric("Min", f"{c['followers_min']:,}")
    cols[1].metric("Max", f"{c['followers_max']:,}")

    st.markdown("**Engagement Rate mínimo por tier**")
    er_cols = st.columns(5)
    for i, (tier, er) in enumerate(c["er_min_by_tier"].items()):
        er_cols[i].metric(tier, f"{er*100:.1f}%")
    st.caption(f"ER max universal: {c['er_max']*100:.0f}% (arriba = bot suspect)")

    st.markdown("**Calidad de contenido**")
    cols2 = st.columns(4)
    cols2[0].metric("Niche match min", f"{c['min_niche_match_score']:.2f}")
    cols2[1].metric("Posts mín. recientes", c["min_posts_last_12"])
    cols2[2].metric("Likes/comm max", f"{c['max_likes_to_comments_ratio']}:1")
    cols2[3].metric("Días desde último post", f"≤ {c['max_days_since_last_post']}")

    st.markdown("**Anti audiencia fake**")
    cols3 = st.columns(3)
    cols3[0].metric("Followers/following min", f"{c['min_follower_following_ratio']:.1f}:1")
    cols3[1].metric("Cuentas privadas", "❌ excluidas" if c["exclude_private"] else "ok")
    cols3[2].metric("Business >100K", "❌ excluidas" if c["exclude_business_account_unless_creator"] else "ok")

    st.markdown("**Filtros de palabras clave (handles/nombres a saltar)**")
    st.caption(f"**Handle keywords:** `{', '.join(c['skip_handle_keywords'])}`")
    st.caption(f"**Nombre keywords:** `{', '.join(c['skip_fullname_keywords'])}`")

    st.info("Para editar: cambia los valores en `config.py` y reinicia la app. "
            "Persistencia en DB para edición en vivo viene en v1.2.")

    st.subheader("Hashtags semilla")
    st.write(", ".join(f"#{h}" for h in config.SCOUTING_DEFAULTS["hashtags_seed"]))

    st.subheader("Cuentas referencia (competidoras / aspiracional)")
    st.write(", ".join(f"@{h}" for h in config.SCOUTING_DEFAULTS["competitor_handles_seed"]))


# ============================================================
# PAGE: Stories tracking
# ============================================================
def page_stories_tracking() -> None:
    st.header(":material/auto_stories: Stories tracking")
    st.caption(
        "Captura stories de tus collabs activas, detecta menciones a FelyFit "
        "y descarga el media local. Stories duran 24h en IG."
    )

    # ============== TOP-LINE METRICS ==============
    active_handles_df = fetch_df("""
        SELECT DISTINCT handle FROM candidates
        WHERE status IN ('active', 'contacted', 'negotiating')
          AND followers >= 5000
    """)
    n_active = len(active_handles_df)

    stories_24h = fetch_df("""
        SELECT COUNT(*) n, SUM(is_felyfit_mention) felyfit
        FROM story_snapshots
        WHERE captured_at >= datetime('now', '-24 hours')
    """)
    n_24h = int(stories_24h.iloc[0]["n"] or 0)
    n_felyfit_24h = int(stories_24h.iloc[0]["felyfit"] or 0)

    m1, m2, m3 = st.columns(3)
    m1.metric("Collabs activas trackeables", n_active)
    m2.metric("Stories captured 24h", n_24h)
    m3.metric("Menciones FelyFit 24h", n_felyfit_24h)

    # ============== BOTÓN SCRAPE ==============
    cs1, cs2 = st.columns([2, 1])
    if cs1.button(":material/refresh: Scrape stories de collabs activas ahora",
                  type="primary", use_container_width=True,
                  disabled=(n_active == 0)):
        handles = active_handles_df["handle"].tolist()
        with st.spinner(f"Scrapeando stories de {len(handles)} handles…"):
            result = apify_jobs.scrape_stories_for_handles(handles)
        st.success(
            f"✅ {result['total_stories_returned']} stories returned · "
            f"{result['new_stories']} nuevas · "
            f"{result['felyfit_mentions']} menciones FelyFit · "
            f"costo ${result['compute_usd']:.4f}"
        )
        st.rerun()

    # Scrape de UN solo handle (debugging / on-demand)
    with cs2.popover(":material/search: Scrape uno"):
        single_handle = st.text_input("Handle", placeholder="@maria.fit",
                                       key="single_story_handle")
        if st.button("Scrape", key="single_story_btn"):
            h = single_handle.strip().lstrip("@")
            with st.spinner(f"Scrapeando @{h}…"):
                result = apify_jobs.scrape_stories_for_handles([h])
            st.success(
                f"{result['total_stories_returned']} stories · "
                f"{result['felyfit_mentions']} menciones FelyFit"
            )
            st.rerun()

    st.divider()

    # ============== TABS: FelyFit mentions vs todas ==============
    tabs = st.tabs([
        f"⭐ Menciones FelyFit ({n_felyfit_24h})",
        f"📋 Todas las stories ({n_24h})",
    ])

    with tabs[0]:
        _render_stories_grid(only_felyfit=True)
    with tabs[1]:
        _render_stories_grid(only_felyfit=False)


def _render_stories_grid(*, only_felyfit: bool, days: int = 7) -> None:
    """Grid de stories capturadas (últimos N días)."""
    where = "WHERE captured_at >= datetime('now', ?)"
    params: list = [f"-{days} days"]
    if only_felyfit:
        where += " AND is_felyfit_mention=1"

    df = fetch_df(f"""
        SELECT s.id, s.handle, c.full_name, c.profile_pic_url, c.followers,
               s.posted_at, s.expires_at, s.media_type, s.media_url,
               s.local_media_path, s.caption_text, s.mentions, s.hashtags,
               s.link_url, s.is_felyfit_mention, s.felyfit_detection_notes,
               s.views_count
        FROM story_snapshots s
        LEFT JOIN candidates c ON c.handle = s.handle
        {where}
        ORDER BY s.posted_at DESC
        LIMIT 100
    """, tuple(params))

    if df.empty:
        st.info(
            "No hay stories capturadas todavía. "
            "Dale al botón 'Scrape stories' arriba para empezar."
            if not only_felyfit
            else "Ninguna collab activa nos ha mencionado en stories (últimos 7 días)."
        )
        return

    for _, row in df.iterrows():
        with st.container(border=True):
            cols = st.columns([1, 2, 1])

            # Media preview
            with cols[0]:
                if row["local_media_path"] and os.path.exists(row["local_media_path"]):
                    if row["media_type"] == "video":
                        st.video(row["local_media_path"])
                    else:
                        st.image(row["local_media_path"], width=200)
                else:
                    st.caption("(media no descargada)")

            # Metadata
            with cols[1]:
                badge = "⭐ FelyFit" if row["is_felyfit_mention"] else ""
                st.markdown(f"### @{row['handle']} {badge}")
                if row.get("full_name"):
                    st.caption(row["full_name"])
                st.markdown(
                    f"**Posteada:** {row['posted_at']}  ·  "
                    f"**Expira:** {row['expires_at']}"
                )
                if row.get("caption_text"):
                    st.markdown(f"💬 _{row['caption_text']}_")
                try:
                    mentions = json.loads(row.get("mentions") or "[]")
                    if mentions:
                        st.markdown("**Mentions:** " +
                                     " ".join(f"`@{m}`" for m in mentions[:8]))
                except Exception:
                    pass
                try:
                    hashtags = json.loads(row.get("hashtags") or "[]")
                    if hashtags:
                        st.markdown("**Hashtags:** " +
                                     " ".join(f"`#{h}`" for h in hashtags[:8]))
                except Exception:
                    pass
                if row.get("link_url"):
                    st.markdown(f"🔗 [{row['link_url']}]({row['link_url']})")
                if row.get("felyfit_detection_notes"):
                    st.success(f"Razón detección: {row['felyfit_detection_notes']}")

            # Views / EMV
            with cols[2]:
                if row.get("views_count") is not None:
                    st.metric("Views", f"{int(row['views_count']):,}")
                    emv = int(row["views_count"]) * config.EMV_MULTIPLIERS["view_mxn"]
                    st.metric("EMV (story)", f"${emv:,.0f} MXN")
                else:
                    st.caption("(views no disponibles)")


# ============================================================
# Main
# ============================================================
PAGES = [
    ":material/search: Scouting",
    ":material/person_search: Stalkear",
    ":material/swipe: Felynder",
    ":material/view_kanban: The chosen ones",
    ":material/handshake: Collabs",
    ":material/auto_stories: Stories tracking",
    ":material/settings: The rules",
]


def _logo_html() -> str:
    """Carga logo.png como data URI para embeber en sidebar."""
    logo_path = os.path.join(os.path.dirname(__file__), "assets", "logo.png")
    if not os.path.exists(logo_path):
        return '<div style="font-family:Bowlby One;font-size:2rem;color:#722F37;">f*kol</div>'
    with open(logo_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    # margin-top negativo para ocupar el espacio top del sidebar
    return (
        f'<div style="margin:-4rem -1rem 0.5rem -1rem;text-align:center;">'
        f'<img src="data:image/png;base64,{b64}" '
        f'style="width:100%;height:auto;display:block;" alt="F*KOL"/>'
        f'</div>'
    )

# Y2K-style decorative shapes (SVG inline strings)
_Y2K_STAR = '<svg class="ff-star" viewBox="0 0 24 24" fill="currentColor"><path d="M12 1 L14.2 9.5 L22.5 11.8 L14.2 14.2 L12 23 L9.8 14.2 L1.5 11.8 L9.8 9.5 Z"/></svg>'
_Y2K_BURST = '<svg class="ff-star" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0 L13 8 L21 4 L17 12 L24 14 L16 16 L20 23 L12 18 L4 23 L8 16 L0 14 L7 12 L3 4 L11 8 Z"/></svg>'
_Y2K_FLOWER = '<svg class="ff-star" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2 C 14,2 16,4 16,6 C 18,6 20,8 20,10 C 22,10 22,12 22,14 C 22,16 20,18 18,18 C 18,20 16,22 14,22 C 12,22 10,20 10,18 C 8,18 6,16 6,14 C 4,14 2,12 2,10 C 2,8 4,6 6,6 C 6,4 8,2 10,2 Z"/></svg>'


def main() -> None:
    # Inicializa DB si no existe (caso típico: primer deploy en Streamlit Cloud).
    # Operación idempotente — solo crea tablas si faltan.
    db.init()

    # Auth gate — solo se activa si hay usuarios configurados en
    # .streamlit/secrets.toml. En dev local sin secrets, pasa libre.
    if not auth.gate():
        st.stop()

    st.sidebar.markdown(_logo_html(), unsafe_allow_html=True)

    # Permite navegación programática (set session_state.active_page + rerun)
    if "active_page" not in st.session_state:
        st.session_state.active_page = PAGES[0]
    default_idx = PAGES.index(st.session_state.active_page) if st.session_state.active_page in PAGES else 0
    page = st.sidebar.radio("Página", PAGES, index=default_idx)
    st.session_state.active_page = page

    st.sidebar.divider()
    auth.logout_button()
    st.sidebar.caption(f"Last refresh: {datetime.now().strftime('%H:%M:%S')}")

    render_header()
    st.divider()

    if page.endswith("Scouting"):
        page_scouting()
    elif page.endswith("Stalkear"):
        page_profile_lookup()
    elif page.endswith("Felynder"):
        page_tinder()
    elif page.endswith("The chosen ones"):
        page_pipeline()
    elif page.endswith("Collabs"):
        page_collabs()
    elif page.endswith("Stories tracking"):
        page_stories_tracking()
    elif page.endswith("The rules"):
        page_settings()


if __name__ == "__main__":
    main()
