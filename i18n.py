"""Internacionalización ligera para FelyFit KOL System.

Uso:
    import i18n
    t = i18n.t  # alias
    st.header(t("collabs.title"))

El idioma actual se guarda en st.session_state.lang ('es' default).
Sidebar tiene toggle ES/EN.

Si una key no existe en el idioma actual, devuelve el valor del español
como fallback (nunca rompe).
"""
from __future__ import annotations

import streamlit as st


# ============================================================
# Diccionarios
# ============================================================
# Estructura: TRANSLATIONS[lang][key] = string
# Si key no existe en `lang`, cae a "es" (default fallback).
TRANSLATIONS: dict[str, dict[str, str]] = {
    "es": {
        # ── Sidebar / nav ──
        "nav.page": "Página",
        "nav.logout": "Cerrar sesión",
        "nav.session": "Sesión",
        "nav.session.admin": "admin",
        "nav.session.guest": "invitada",
        "nav.last_refresh": "Last refresh",
        "nav.lang_label": "Idioma",

        # ── Login ──
        "auth.brand_team": "FelyFit Brand Team",
        "auth.tab_code": "Tengo un código",
        "auth.tab_admin": "Soy admin",
        "auth.for_team": "Para usuarios del equipo",
        "auth.ask_code": "Pide tu código a Lucy. Se vence 24h después de generado. Tu sesión queda activa 30 días.",
        "auth.your_name": "Tu nombre",
        "auth.your_name_ph": "ej. Will, Karen…",
        "auth.code_6": "Código (6 dígitos)",
        "auth.enter": "Entrar",
        "auth.for_admin": "Solo para administradoras",
        "auth.session_30d": "Tu sesión queda activa 30 días — no tendrás que loggearte de nuevo.",
        "auth.admin_user": "Usuario admin",
        "auth.password": "Contraseña",
        "auth.enter_admin": "Entrar como admin",
        "auth.err_credentials": "Usuario o contraseña incorrectos.",
        "auth.err_code": "Código inválido, expirado o ya usado.",
        "auth.err_name_required": "Pon tu nombre para el log de accesos.",

        # ── Collabs ──
        "collabs.title": "Collabs",
        "collabs.pending": "Pendiente",
        "collabs.shipped": "Enviadas",
        "collabs.tracking": "Tracking",
        "collabs.done": "Done",
        "collabs.ratio_global": "Ratio global",
        "collabs.tab_active": "Activas",
        "collabs.tab_dashboard": "Dashboard",
        "collabs.tab_completed": "Completadas",
        "collabs.tab_campaign": "Por campaña",
        "collabs.tab_new": "Crear nueva",
        "collabs.filter_by_status": "Filtrando Activas por",
        "collabs.filter_toggle": "click la card de nuevo para quitar el filtro",

        # ── Pages ──
        "page.stalker.title": "Stalkear perfil",
        "page.stalker.caption": "Búsqueda directa: pega un handle de IG, te devuelve toda la info del perfil + una recomendación de tipo de colaboración basada en sus métricas.",
        "page.stalker.handle_label": "Handle de Instagram (con o sin @)",
        "page.stalker.analyze": "Analizar perfil",
        "page.scouting.title": "Scouting",
        "page.felynder.title": "Felynder",
        "page.chosen.title": "The chosen ones",
        "page.chosen.search": "Buscar por handle o nombre",
        "page.rules.title": "The rules",

        # ── Common ──
        "common.save": "Guardar",
        "common.cancel": "Cancelar",
        "common.delete": "Eliminar",
        "common.edit": "Editar",
        "common.back": "Volver",
        "common.next": "Siguiente",
        "common.confirm": "Confirmar",
        "common.loading": "Cargando…",
        "common.error": "Error",
        "common.success": "Listo",
        "common.handle": "Handle",
        "common.full_name": "Nombre completo",
        "common.followers": "Followers",
        "common.engagement": "ER",
        "common.tier": "Tier",
        "common.country": "País",
        "common.status": "Estado",
    },
    "en": {
        # ── Sidebar / nav ──
        "nav.page": "Page",
        "nav.logout": "Log out",
        "nav.session": "Session",
        "nav.session.admin": "admin",
        "nav.session.guest": "guest",
        "nav.last_refresh": "Last refresh",
        "nav.lang_label": "Language",

        # ── Login ──
        "auth.brand_team": "FelyFit Brand Team",
        "auth.tab_code": "I have a code",
        "auth.tab_admin": "I'm admin",
        "auth.for_team": "For team members",
        "auth.ask_code": "Ask Lucy for your code. Expires 24h after generated. Your session stays active 30 days.",
        "auth.your_name": "Your name",
        "auth.your_name_ph": "e.g. Will, Karen…",
        "auth.code_6": "Code (6 digits)",
        "auth.enter": "Enter",
        "auth.for_admin": "Admins only",
        "auth.session_30d": "Your session stays active 30 days — no need to log in again.",
        "auth.admin_user": "Admin username",
        "auth.password": "Password",
        "auth.enter_admin": "Log in as admin",
        "auth.err_credentials": "Wrong username or password.",
        "auth.err_code": "Invalid, expired or already used code.",
        "auth.err_name_required": "Add your name for the access log.",

        # ── Collabs ──
        "collabs.title": "Collabs",
        "collabs.pending": "Pending",
        "collabs.shipped": "Shipped",
        "collabs.tracking": "Tracking",
        "collabs.done": "Done",
        "collabs.ratio_global": "Global ratio",
        "collabs.tab_active": "Active",
        "collabs.tab_dashboard": "Dashboard",
        "collabs.tab_completed": "Completed",
        "collabs.tab_campaign": "By campaign",
        "collabs.tab_new": "Create new",
        "collabs.filter_by_status": "Filtering Active by",
        "collabs.filter_toggle": "click the card again to remove the filter",

        # ── Pages ──
        "page.stalker.title": "Stalk profile",
        "page.stalker.caption": "Direct lookup: paste an IG handle, get the full profile info + a collab type recommendation based on metrics.",
        "page.stalker.handle_label": "Instagram handle (with or without @)",
        "page.stalker.analyze": "Analyze profile",
        "page.scouting.title": "Scouting",
        "page.felynder.title": "Felynder",
        "page.chosen.title": "The chosen ones",
        "page.chosen.search": "Search by handle or name",
        "page.rules.title": "The rules",

        # ── Common ──
        "common.save": "Save",
        "common.cancel": "Cancel",
        "common.delete": "Delete",
        "common.edit": "Edit",
        "common.back": "Back",
        "common.next": "Next",
        "common.confirm": "Confirm",
        "common.loading": "Loading…",
        "common.error": "Error",
        "common.success": "Done",
        "common.handle": "Handle",
        "common.full_name": "Full name",
        "common.followers": "Followers",
        "common.engagement": "ER",
        "common.tier": "Tier",
        "common.country": "Country",
        "common.status": "Status",
    },
}

DEFAULT_LANG = "es"


def get_lang() -> str:
    """Idioma actual del usuario. Default 'es'."""
    try:
        return st.session_state.get("lang", DEFAULT_LANG)
    except Exception:
        return DEFAULT_LANG


def set_lang(lang: str) -> None:
    """Cambia idioma actual."""
    if lang in TRANSLATIONS:
        st.session_state.lang = lang


def t(key: str, **kwargs) -> str:
    """Traduce key al idioma actual. Fallback a ES si falta, después a key literal.

    Soporta interpolación: t("foo", name="Lucy") → reemplaza {name} en el string.
    """
    lang = get_lang()
    table = TRANSLATIONS.get(lang, {})
    fallback = TRANSLATIONS.get(DEFAULT_LANG, {})
    s = table.get(key) or fallback.get(key) or key
    if kwargs:
        try:
            s = s.format(**kwargs)
        except (KeyError, IndexError):
            pass
    return s


def lang_toggle_sidebar() -> None:
    """Renderiza el toggle ES/EN en el sidebar."""
    current = get_lang()
    new = st.sidebar.radio(
        t("nav.lang_label"),
        options=["es", "en"],
        index=0 if current == "es" else 1,
        format_func=lambda x: "🇲🇽 Español" if x == "es" else "🇺🇸 English",
        horizontal=True,
        key="_lang_radio",
    )
    if new != current:
        set_lang(new)
        st.rerun()
