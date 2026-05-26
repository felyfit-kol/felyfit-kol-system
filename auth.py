"""Auth gate simple para multi-usuario en Streamlit Cloud.

Usuarios + passwords se definen en `.streamlit/secrets.toml` (subir al UI
de Streamlit Cloud). Si secrets no tiene [auth.users], permite acceso libre
(útil en desarrollo local).

Uso en app.py:
    import auth
    if not auth.gate():
        st.stop()
"""
from __future__ import annotations

import hmac
from typing import Optional

import streamlit as st


def _users_from_secrets() -> dict:
    """Lee usuarios de st.secrets['auth']['users']. Devuelve {} si no existe."""
    try:
        users = dict(st.secrets["auth"]["users"])
    except (KeyError, FileNotFoundError, AttributeError):
        return {}
    # Estructura esperada: {"lucy": {"email": "...", "password": "...", "name": "..."}}
    return users


def _check_credentials(username: str, password: str, users: dict) -> Optional[str]:
    """Devuelve el nombre amigable si las credenciales matchean, None si no."""
    if username not in users:
        return None
    expected = str(users[username].get("password", ""))
    if not hmac.compare_digest(expected, password):
        return None
    return users[username].get("name", username)


def gate() -> bool:
    """Pantalla de login. Devuelve True si el usuario está autenticado.

    Si no hay usuarios configurados en secrets (ej. dev local), permite paso libre.
    """
    users = _users_from_secrets()

    # Sin usuarios configurados → acceso libre (dev local)
    if not users:
        return True

    # Ya autenticado en esta sesión
    if st.session_state.get("_auth_ok"):
        return True

    # Render login screen — branding FelyFit
    st.markdown(
        """
        <style>
          .ff-login-wrap {
            max-width: 420px;
            margin: 4rem auto;
            background: #FFFFFFEE;
            padding: 2.5rem;
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

    with st.form("login_form", clear_on_submit=False):
        st.subheader("Inicia sesión")
        username = st.text_input("Usuario", placeholder="lucy / will / …")
        password = st.text_input("Contraseña", type="password")
        submit = st.form_submit_button("Entrar", type="primary",
                                        use_container_width=True)

    if submit:
        name = _check_credentials(username.strip().lower(), password, users)
        if name:
            st.session_state._auth_ok = True
            st.session_state._auth_user = username.strip().lower()
            st.session_state._auth_name = name
            st.rerun()
        else:
            st.error("Usuario o contraseña incorrectos.")

    return False


def current_user() -> Optional[str]:
    """Devuelve el nombre amigable del usuario logueado, o None."""
    return st.session_state.get("_auth_name")


def logout_button() -> None:
    """Renderiza un botón de cerrar sesión en el sidebar."""
    name = current_user()
    if not name:
        return
    st.sidebar.caption(f"Sesión: **{name}**")
    if st.sidebar.button("Cerrar sesión", use_container_width=True):
        for k in list(st.session_state.keys()):
            if k.startswith("_auth"):
                del st.session_state[k]
        st.rerun()
