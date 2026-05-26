"""Auth gate con dos rutas:

1. **Admin login** (user + password) — definido en st.secrets[auth.users].
   Los admins pueden generar códigos para dar acceso a otros.

2. **Código de acceso** (6 dígitos) — generado por la admin desde el panel,
   válido N horas, 1 uso. La persona teclea su nombre + código y entra.

Uso en app.py:
    import auth
    if not auth.gate():
        st.stop()
"""
from __future__ import annotations

import hmac
import random
from datetime import datetime, timedelta
from typing import Optional

import streamlit as st

import db


# ============================================================
# Admin login (user + password desde secrets)
# ============================================================
def _users_from_secrets() -> dict:
    """Lee usuarios admin de st.secrets['auth']['users']. {} si no existe."""
    try:
        return dict(st.secrets["auth"]["users"])
    except (KeyError, FileNotFoundError, AttributeError):
        return {}


def _check_admin(username: str, password: str, users: dict) -> Optional[str]:
    """Devuelve nombre amigable si admin credentials matchean."""
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
    """Genera código de 6 dígitos único, lo guarda en DB."""
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
    raise RuntimeError("No se pudo generar código único después de 20 intentos")


def consume_code(code: str, used_by: str) -> bool:
    """Valida + marca como usado. True si pudo consumirse."""
    code = code.strip()
    if not code.isdigit() or len(code) != 6:
        return False
    now_iso = datetime.now().isoformat(timespec="seconds")
    with db.connect() as conn:
        row = conn.execute(
            "SELECT expires_at, used_at FROM access_codes WHERE code=?", (code,)
        ).fetchone()
        if not row:
            return False
        if row["used_at"]:
            return False
        if row["expires_at"] < now_iso:
            return False
        conn.execute(
            "UPDATE access_codes SET used_at=?, used_by=? WHERE code=?",
            (now_iso, used_by[:60], code),
        )
        return True


def list_active_codes() -> list:
    """Códigos válidos no usados (para el panel admin)."""
    now_iso = datetime.now().isoformat(timespec="seconds")
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT code, generated_by, generated_at, expires_at, note "
            "FROM access_codes "
            "WHERE used_at IS NULL AND expires_at > ? "
            "ORDER BY generated_at DESC",
            (now_iso,),
        ).fetchall()
    return [dict(r) for r in rows]


def list_recent_uses(limit: int = 20) -> list:
    """Últimos códigos usados (historial)."""
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
    """Pantalla de login. Devuelve True si autenticado."""
    users = _users_from_secrets()

    # Sin usuarios admin configurados → acceso libre (dev local)
    if not users:
        return True

    if st.session_state.get("_auth_ok"):
        return True

    # Branding
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
            font-size: 3rem;
            color: #722F37;
            text-transform: lowercase;
            line-height: 1;
            margin-bottom: 0.3rem;
          }
          .ff-login-tag {
            font-family: 'Quicksand', sans-serif;
            font-weight: 600;
            font-size: 0.7rem;
            color: #E5879A;
            letter-spacing: 0.28em;
            text-transform: uppercase;
          }
        </style>
        <div class="ff-login-wrap">
          <div class="ff-login-logo">f*kol</div>
          <div class="ff-login-tag">FelyFit Brand Team</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    tab_code, tab_admin = st.tabs([":material/key: Tengo un código",
                                    ":material/admin_panel_settings: Soy admin"])

    with tab_code:
        st.markdown("**Para usuarios del equipo**")
        st.caption("Pide tu código a Lucy. Se vence 24h después de generado.")
        with st.form("code_form", clear_on_submit=False):
            name = st.text_input("Tu nombre", placeholder="ej. Will, Karen…")
            code = st.text_input("Código (6 dígitos)", max_chars=6,
                                  placeholder="000000")
            submit = st.form_submit_button("Entrar", type="primary",
                                            use_container_width=True)
        if submit:
            if not name.strip():
                st.error("Pon tu nombre para el log de accesos.")
            elif consume_code(code, name.strip()):
                st.session_state._auth_ok = True
                st.session_state._auth_user = name.strip().lower()
                st.session_state._auth_name = name.strip()
                st.session_state._auth_is_admin = False
                st.rerun()
            else:
                st.error("Código inválido, expirado o ya usado.")

    with tab_admin:
        st.markdown("**Solo para administradoras**")
        with st.form("admin_form", clear_on_submit=False):
            username = st.text_input("Usuario admin", placeholder="lucy")
            password = st.text_input("Contraseña", type="password")
            submit_a = st.form_submit_button("Entrar como admin", type="primary",
                                              use_container_width=True)
        if submit_a:
            friendly = _check_admin(username.strip().lower(), password, users)
            if friendly:
                st.session_state._auth_ok = True
                st.session_state._auth_user = username.strip().lower()
                st.session_state._auth_name = friendly
                st.session_state._auth_is_admin = True
                st.rerun()
            else:
                st.error("Usuario o contraseña incorrectos.")

    return False


def current_user() -> Optional[str]:
    return st.session_state.get("_auth_name")


def is_admin() -> bool:
    return bool(st.session_state.get("_auth_is_admin"))


def logout_button() -> None:
    name = current_user()
    if not name:
        return
    role = "admin" if is_admin() else "invitada"
    st.sidebar.caption(f"Sesión: **{name}** · _{role}_")
    if st.sidebar.button("Cerrar sesión", use_container_width=True):
        for k in list(st.session_state.keys()):
            if k.startswith("_auth"):
                del st.session_state[k]
        st.rerun()


def admin_codes_panel() -> None:
    """Panel admin para generar + ver códigos. Solo se renderiza si is_admin()."""
    if not is_admin():
        st.warning("Solo administradoras pueden ver este panel.")
        return

    st.header(":material/key: Códigos de acceso")
    st.caption(
        "Genera un código de 6 dígitos para dar acceso al dashboard "
        "a alguien del equipo (Will, Karen, asistente, etc.). "
        "Comparte el código por WhatsApp / Slack. Vence en 24h y es de 1 solo uso."
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
            cols[2].caption(
                f"Generado: {c['generated_at']} · Vence: {c['expires_at']}"
            )
            if cols[3].button("Revocar", key=f"rev_{c['code']}",
                               help="Marca como usado para invalidarlo"):
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
