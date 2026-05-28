"""Auth gate con sesiones persistentes (cookies HMAC-firmadas).

Dos rutas de login:
1. **Admin login** (user + password) — definido en st.secrets[auth.users].
   Los admins pueden generar códigos para dar acceso a otros.
2. **Código de acceso** (6 dígitos) — generado por la admin desde el panel.

La sesión persiste 30 días via cookie firmada. Sobrevive:
- Sleep de Streamlit Cloud (tras 7 días sin actividad la app duerme)
- Cerrar el browser
- Reloads
- Cold starts

Uso en app.py:
    import auth
    if not auth.gate():
        st.stop()
"""
from __future__ import annotations

import hashlib
import hmac
import json
import random
import time
from datetime import datetime, timedelta
from typing import Optional

import streamlit as st

import db
import i18n

t = i18n.t

# ============================================================
# Cookie config
# ============================================================
COOKIE_KEY = "felyfit_kol_session"
SESSION_DAYS = 30  # auth sobrevive 30 días


def _cookie_secret() -> str:
    """Lee el secret para firmar cookies. Usa st.secrets[auth][secret] o
    cae a un default WARNING (solo para dev). En producción configurar."""
    try:
        return str(st.secrets["auth"]["secret"])
    except (KeyError, FileNotFoundError, AttributeError):
        return "felyfit-default-secret-CHANGE-ME-in-secrets-toml"


def _sign(payload: dict) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    sig = hmac.new(_cookie_secret().encode(), body.encode(),
                    hashlib.sha256).hexdigest()
    return f"{body}|{sig}"


def _verify(token: str) -> Optional[dict]:
    if not token or "|" not in token:
        return None
    try:
        body, sig = token.rsplit("|", 1)
        expected = hmac.new(_cookie_secret().encode(), body.encode(),
                             hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(body)
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


# Token persistence via URL query params — 100% deterministic, no external libs.
# Trade-off: el token queda visible en la URL. Lucy puede bookmarkear esa URL
# y entrar desde ese bookmark sin re-loguearse por 30 días.
QUERY_TOKEN_KEY = "s"


def _save_session_token(user: str, name: str, is_admin: bool) -> None:
    payload = {
        "user": user,
        "name": name,
        "is_admin": bool(is_admin),
        "iat": int(time.time()),
        "exp": int(time.time()) + SESSION_DAYS * 86400,
    }
    token = _sign(payload)
    try:
        st.query_params[QUERY_TOKEN_KEY] = token
    except Exception:
        pass


def _clear_session_token() -> None:
    try:
        if QUERY_TOKEN_KEY in st.query_params:
            del st.query_params[QUERY_TOKEN_KEY]
    except Exception:
        pass


def _try_restore_from_url() -> bool:
    """Si hay token válido en la URL (?s=...), restaurar session_state."""
    try:
        token = st.query_params.get(QUERY_TOKEN_KEY)
    except Exception:
        return False
    if not token:
        return False
    payload = _verify(token)
    if not payload:
        # Token corrupto/expirado — limpia el query param para evitar loops
        _clear_session_token()
        return False
    st.session_state._auth_ok = True
    st.session_state._auth_user = payload.get("user")
    st.session_state._auth_name = payload.get("name")
    st.session_state._auth_is_admin = bool(payload.get("is_admin"))
    return True


# ============================================================
# Admin login (user + password desde secrets)
# ============================================================
def _users_from_secrets() -> dict:
    try:
        return dict(st.secrets["auth"]["users"])
    except (KeyError, FileNotFoundError, AttributeError):
        return {}


def _check_admin(username: str, password: str, users: dict) -> Optional[str]:
    if username not in users:
        return None
    expected = str(users[username].get("password", ""))
    if not hmac.compare_digest(expected, password):
        return None
    return users[username].get("name", username)


# ============================================================
# Access codes (DB-backed)
# ============================================================
def generate_access_code(*, generated_by: str, hours_valid: int = 24,
                          note: str = "") -> str:
    for _ in range(20):
        code = "".join(random.choices("0123456789", k=6))
        with db.connect() as conn:
            existing = conn.execute(
                "SELECT 1 FROM access_codes WHERE code=?", (code,)
            ).fetchone()
            if existing:
                continue
            expires = (datetime.now() + timedelta(hours=hours_valid)).isoformat(
                timespec="seconds"
            )
            conn.execute(
                "INSERT INTO access_codes (code, generated_by, expires_at, note) "
                "VALUES (?, ?, ?, ?)",
                (code, generated_by, expires, note),
            )
            return code
    raise RuntimeError("No se pudo generar código único")


def consume_code(code: str, used_by: str) -> bool:
    code = code.strip()
    if not code.isdigit() or len(code) != 6:
        return False
    now_iso = datetime.now().isoformat(timespec="seconds")
    with db.connect() as conn:
        row = conn.execute(
            "SELECT expires_at, used_at FROM access_codes WHERE code=?", (code,)
        ).fetchone()
        if not row or row["used_at"] or row["expires_at"] < now_iso:
            return False
        conn.execute(
            "UPDATE access_codes SET used_at=?, used_by=? WHERE code=?",
            (now_iso, used_by[:60], code),
        )
        return True


def list_active_codes() -> list:
    now_iso = datetime.now().isoformat(timespec="seconds")
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT code, generated_by, generated_at, expires_at, note "
            "FROM access_codes WHERE used_at IS NULL AND expires_at > ? "
            "ORDER BY generated_at DESC",
            (now_iso,),
        ).fetchall()
    return [dict(r) for r in rows]


def list_recent_uses(limit: int = 20) -> list:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT code, used_by, used_at, note FROM access_codes "
            "WHERE used_at IS NOT NULL ORDER BY used_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


# ============================================================
# Gate principal
# ============================================================
def gate() -> bool:
    users = _users_from_secrets()

    # Sin usuarios admin configurados → acceso libre (dev local)
    if not users:
        return True

    # Ya autenticado en esta sesión
    if st.session_state.get("_auth_ok"):
        return True

    # Intentar restaurar de cookie (session sobrevive sleep de Streamlit Cloud)
    if _try_restore_from_url():
        return True

    # Render login
    st.markdown(
        """
        <style>
          .ff-login-wrap {
            max-width: 460px;
            margin: 3rem auto 1.5rem;
            background: #FFFFFFEE;
            padding: 2.5rem 2.5rem 1rem;
            border-radius: 24px;
            border: 1px solid #F0C9CE;
            box-shadow: 0 8px 32px rgba(229, 135, 154, 0.12);
            text-align: center;
          }
          .ff-login-logo {
            font-family: 'Bowlby One', sans-serif;
            font-size: 3rem; color: #722F37;
            text-transform: lowercase;
            line-height: 1; margin-bottom: 0.3rem;
          }
          .ff-login-tag {
            font-family: 'Quicksand', sans-serif;
            font-weight: 600; font-size: 0.7rem;
            color: #E5879A; letter-spacing: 0.28em;
            text-transform: uppercase;
          }
        </style>
        <div class="ff-login-wrap">
          <div class="ff-login-logo">f*kol</div>
          <div class="ff-login-tag">""" + t("auth.brand_team") + """</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Toggle de idioma en el login también (antes de loguear)
    i18n.lang_toggle_sidebar()

    tab_code, tab_admin = st.tabs([
        f":material/key: {t('auth.tab_code')}",
        f":material/admin_panel_settings: {t('auth.tab_admin')}",
    ])

    with tab_code:
        st.markdown(f"**{t('auth.for_team')}**")
        st.caption(t("auth.ask_code"))
        with st.form("code_form"):
            name = st.text_input(t("auth.your_name"),
                                  placeholder=t("auth.your_name_ph"))
            code = st.text_input(t("auth.code_6"), max_chars=6,
                                  placeholder="000000")
            submit = st.form_submit_button(t("auth.enter"), type="primary",
                                            use_container_width=True)
        if submit:
            if not name.strip():
                st.error(t("auth.err_name_required"))
            elif consume_code(code, name.strip()):
                st.session_state._auth_ok = True
                st.session_state._auth_user = name.strip().lower()
                st.session_state._auth_name = name.strip()
                st.session_state._auth_is_admin = False
                _save_session_token(name.strip().lower(), name.strip(), False)
                st.rerun()
            else:
                st.error(t("auth.err_code"))

    with tab_admin:
        st.markdown(f"**{t('auth.for_admin')}**")
        st.caption(t("auth.session_30d"))
        with st.form("admin_form"):
            username = st.text_input(t("auth.admin_user"), placeholder="lucy")
            password = st.text_input(t("auth.password"), type="password")
            submit_a = st.form_submit_button(t("auth.enter_admin"), type="primary",
                                              use_container_width=True)
        if submit_a:
            friendly = _check_admin(username.strip().lower(), password, users)
            if friendly:
                st.session_state._auth_ok = True
                st.session_state._auth_user = username.strip().lower()
                st.session_state._auth_name = friendly
                st.session_state._auth_is_admin = True
                _save_session_token(username.strip().lower(), friendly, True)
                st.rerun()
            else:
                st.error(t("auth.err_credentials"))

    return False


def current_user() -> Optional[str]:
    return st.session_state.get("_auth_name")


def is_admin() -> bool:
    return bool(st.session_state.get("_auth_is_admin"))


def logout_button() -> None:
    name = current_user()
    if not name:
        return
    role = t("nav.session.admin") if is_admin() else t("nav.session.guest")
    st.sidebar.caption(f"{t('nav.session')}: **{name}** · _{role}_")
    if st.sidebar.button(t("nav.logout"), use_container_width=True):
        for k in list(st.session_state.keys()):
            if k.startswith("_auth") or k == "last_lookup":
                del st.session_state[k]
        _clear_session_token()
        st.rerun()


def admin_codes_panel() -> None:
    if not is_admin():
        st.warning("Solo administradoras pueden ver este panel.")
        return

    st.header(":material/key: Códigos de acceso")
    st.caption(
        "Genera un código de 6 dígitos para dar acceso al dashboard. "
        "Comparte por WhatsApp / Slack. Vence en 24h y es de 1 solo uso. "
        "La persona queda logueada 30 días después de entrar."
    )

    with st.container(border=True):
        st.markdown("**Generar nuevo código**")
        c1, c2 = st.columns([2, 1])
        with c1:
            note = st.text_input(
                "Para quién / motivo (opcional)",
                placeholder="ej. Will para revisar pipeline",
                key="new_code_note",
            )
        with c2:
            hours = st.number_input("Válido (horas)", min_value=1, max_value=168,
                                     value=24, step=1, key="new_code_hours")
        if st.button(":material/add_circle: Generar código",
                     type="primary", use_container_width=True):
            code = generate_access_code(
                generated_by=current_user() or "admin",
                hours_valid=int(hours),
                note=note.strip(),
            )
            st.success(f"### Código: `{code}`")
            st.caption(
                f"Cópialo y mándaselo a {note or 'la persona'}. "
                f"Vence en {hours}h. 1 solo uso."
            )

    st.divider()
    st.subheader("Códigos activos")
    active = list_active_codes()
    if not active:
        st.info("No hay códigos activos.")
    else:
        for c in active:
            cols = st.columns([1, 2, 2, 1])
            cols[0].code(c["code"])
            cols[1].markdown(f"_{c['note'] or '(sin nota)'}_")
            cols[2].caption(f"Generado: {c['generated_at']} · Vence: {c['expires_at']}")
            if cols[3].button("Revocar", key=f"rev_{c['code']}"):
                consume_code(c["code"], f"REVOKED_by_{current_user()}")
                st.rerun()

    st.divider()
    st.subheader("Historial de accesos (últimos 20)")
    recent = list_recent_uses(limit=20)
    if not recent:
        st.caption("Aún no hay accesos registrados.")
    else:
        for r in recent:
            st.markdown(
                f"- **{r['used_by']}** · usó `{r['code']}` · "
                f"{r['used_at']} · _{r['note'] or 'sin nota'}_"
            )
