"""SQLite/Turso connection + schema. Source of truth del sistema KOL.

Backend dual:
- Si TURSO_DATABASE_URL está set en env → conecta a Turso (cloud, persistente).
- Si no → SQLite local en data/felyfit_kol.db (dev local fallback).

La API que expone es compatible con sqlite3 (connect → execute → fetchall/fetchone),
así que el resto del código no cambia.

Reglas:
- Solo este archivo conoce SQL. Otros modulos llaman funciones aqui.
- Cada candidata es unica por handle de IG (PRIMARY KEY).
- candidates.status es el state machine. Lark se actualiza en transiciones clave.
"""

import os
import sqlite3
from pathlib import Path
from typing import Any, Iterator, List, Optional, Sequence

DB_PATH = Path(__file__).parent / "data" / "felyfit_kol.db"

# Streamlit Cloud: secrets están en st.secrets pero también se exportan como
# env vars cuando son root-level. Aquí leemos de env directo + fallback a st.secrets.
def _get_turso_url() -> Optional[str]:
    url = os.environ.get("TURSO_DATABASE_URL")
    if url:
        return url
    try:
        import streamlit as st
        return st.secrets.get("TURSO_DATABASE_URL")
    except Exception:
        return None


def _get_turso_token() -> Optional[str]:
    tok = os.environ.get("TURSO_AUTH_TOKEN")
    if tok:
        return tok
    try:
        import streamlit as st
        return st.secrets.get("TURSO_AUTH_TOKEN")
    except Exception:
        return None


def _use_turso() -> bool:
    return bool(_get_turso_url() and _get_turso_token())

SCHEMA = """
-- Candidatas descubiertas o cargadas (cualquier status)
CREATE TABLE IF NOT EXISTS candidates (
    handle              TEXT PRIMARY KEY,
    full_name           TEXT,
    bio                 TEXT,
    followers           INTEGER,
    following           INTEGER,
    posts_count         INTEGER,
    is_verified         INTEGER DEFAULT 0,
    is_private          INTEGER DEFAULT 0,
    profile_pic_url     TEXT,
    external_url        TEXT,
    contact_email       TEXT,

    -- Metricas calculadas con enriquecimiento (ultimos 12 posts)
    avg_likes           REAL,
    avg_comments        REAL,
    avg_views           REAL,
    engagement_rate     REAL,
    posting_freq_week   REAL,
    last_post_at        TIMESTAMP,

    -- Inferido del bio / posts
    estimated_city      TEXT,
    inferred_niches     TEXT,    -- JSON array
    tier                TEXT,    -- nano/micro/mid/macro/mega

    -- Scoring
    fit_score           REAL,
    fit_score_breakdown TEXT,    -- JSON
    fit_score_at        TIMESTAMP,

    -- Clasificación demográfica + tipo
    country             TEXT,    -- ISO code (MX, US, AR, etc) o NULL si no detectable
    gender              TEXT,    -- 'female' / 'male' / NULL
    account_type        TEXT,    -- individual / studio / brand / nonprofit / collective / unknown

    -- Origen
    source              TEXT,    -- hashtag / competitor_mention / manual_list / seeds_relatedProfiles
    source_detail       TEXT,    -- ej. "#activewearmx" o handle competidor
    scout_run_id        INTEGER, -- FK a scout_runs.id (puede ser NULL para imports)
    discovered_at       TIMESTAMP DEFAULT (datetime('now')),
    last_enriched_at    TIMESTAMP,

    -- Workflow
    status              TEXT DEFAULT 'discovered',
        -- discovered  : recien encontrada, sin revisar
        -- approved    : aprobada por Lucy, pendiente outreach
        -- rejected    : descartada por Lucy
        -- contacted   : outreach enviado
        -- responded   : contestaron
        -- negotiating : negociando terminos
        -- active      : collab en curso (tiene fila en collabs)
        -- declined    : ellas dijeron que no
        -- paused      : pausada (revisar despues)
    rejected_reason     TEXT,
    notes               TEXT,

    -- Veredicto del filtro automatico (informativo, no bloquea):
    --   pass        = pasa todos los criterios
    --   borderline  = tiene algun strike pero no es basura
    filter_verdict      TEXT,
    filter_reason       TEXT,

    -- Sync con Lark Creadoras IG
    lark_record_id      TEXT,
    lark_synced_at      TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_candidates_status ON candidates(status);
CREATE INDEX IF NOT EXISTS idx_candidates_fit_score ON candidates(fit_score DESC);


-- Posts de candidatas (organicos, usados para calcular ER + EMV esperado)
CREATE TABLE IF NOT EXISTS candidate_posts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    handle          TEXT NOT NULL REFERENCES candidates(handle),
    post_url        TEXT UNIQUE,
    shortcode       TEXT,
    post_type       TEXT,         -- image / video / carousel / reel
    posted_at       TIMESTAMP,
    likes           INTEGER,
    comments        INTEGER,
    views           INTEGER,
    caption         TEXT,
    hashtags        TEXT,         -- JSON array
    mentions        TEXT,         -- JSON array
    captured_at     TIMESTAMP DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_candidate_posts_handle ON candidate_posts(handle);


-- Collabs ejecutadas o en curso
CREATE TABLE IF NOT EXISTS collabs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    handle              TEXT NOT NULL REFERENCES candidates(handle),
    campaign_name       TEXT,
    campaign_type       TEXT,     -- gifted / paid_light / paid_mid / paid_hero / hybrid_event

    -- Inversion desglosada (MXN)
    cogs_pieces         REAL DEFAULT 0,
    retail_pieces       REAL DEFAULT 0,
    shipping_cost       REAL DEFAULT 0,
    cash_fee            REAL DEFAULT 0,
    usage_rights_fee    REAL DEFAULT 0,
    agency_fee          REAL DEFAULT 0,

    -- Ventana de tracking
    launch_date         DATE,
    track_days          INTEGER DEFAULT 14,
    tracking_started_at TIMESTAMP,
    tracking_ended_at   TIMESTAMP,

    -- Followers attribution
    felyfit_followers_before INTEGER,
    felyfit_followers_after  INTEGER,
    attributed_followers     INTEGER,  -- calculado

    -- EMV (recalculado en cada refresh)
    total_likes         INTEGER DEFAULT 0,
    total_comments      INTEGER DEFAULT 0,
    total_saves         INTEGER DEFAULT 0,
    total_shares        INTEGER DEFAULT 0,
    total_views         INTEGER DEFAULT 0,
    emv_mxn             REAL,
    emv_cash_ratio      REAL,
    emv_total_ratio     REAL,
    last_recalc_at      TIMESTAMP,

    -- Estado
    status              TEXT DEFAULT 'pending',
        -- pending / active_tracking / completed / cancelled
    notes               TEXT,

    -- Sync
    lark_synced_at      TIMESTAMP,

    created_at          TIMESTAMP DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_collabs_handle ON collabs(handle);
CREATE INDEX IF NOT EXISTS idx_collabs_status ON collabs(status);


-- Posts asociados a una collab. Una collab puede tener N posts/reels/carousels.
-- Cada uno se trackea independientemente (snapshot diario via collab_post_snapshots).
CREATE TABLE IF NOT EXISTS collab_posts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    collab_id       INTEGER NOT NULL REFERENCES collabs(id),
    post_url        TEXT NOT NULL,
    post_type       TEXT,         -- reel / post / carousel / live
    posted_at       TIMESTAMP,    -- fecha real de publicación
    added_at        TIMESTAMP DEFAULT (datetime('now')),
    last_scraped_at TIMESTAMP,
    UNIQUE(collab_id, post_url)
);

CREATE INDEX IF NOT EXISTS idx_collab_posts_collab ON collab_posts(collab_id);


-- Snapshots diarios de cada post de collab (para tracking time-series)
CREATE TABLE IF NOT EXISTS collab_post_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    collab_id       INTEGER NOT NULL REFERENCES collabs(id),
    post_url        TEXT NOT NULL,
    captured_at     TIMESTAMP DEFAULT (datetime('now')),
    likes           INTEGER,
    comments        INTEGER,
    saves           INTEGER,
    shares          INTEGER,
    views           INTEGER,
    UNIQUE(collab_id, post_url, captured_at)
);


-- Runs de scouting (auditoria + costo Apify)
CREATE TABLE IF NOT EXISTS scout_runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at          TIMESTAMP DEFAULT (datetime('now')),
    finished_at         TIMESTAMP,
    source              TEXT,         -- hashtag / competitor_mentions / manual_list / seeds_relatedProfiles
    source_detail       TEXT,
    apify_actor         TEXT,
    apify_run_id        TEXT,
    apify_compute_usd   REAL,
    candidates_seen     INTEGER DEFAULT 0,
    candidates_new      INTEGER DEFAULT 0,
    status              TEXT DEFAULT 'running',  -- running / done / error
    error               TEXT,

    -- Sessions: cuando un theme scout cascade por N hashtags, todos
    -- los runs comparten session_id + session_label para agruparlos.
    session_id          TEXT,
    session_label       TEXT
);


-- Outreach log (cada mensaje enviado a una candidata)
CREATE TABLE IF NOT EXISTS outreach_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    handle          TEXT NOT NULL REFERENCES candidates(handle),
    channel         TEXT,         -- dm_ig / dm_tiktok / email / whatsapp
    sent_at         TIMESTAMP DEFAULT (datetime('now')),
    message         TEXT,
    responded_at    TIMESTAMP,
    response_summary TEXT
);

CREATE INDEX IF NOT EXISTS idx_outreach_handle ON outreach_log(handle);


-- Config key-value (multiplicadores EMV editables, etc)
CREATE TABLE IF NOT EXISTS config (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TIMESTAMP DEFAULT (datetime('now'))
);


-- Related profiles edges — el algoritmo de IG nos da "perfiles similares"
-- en el campo relatedProfiles del scraper. Cada fila = "seed_handle sugiere
-- related_handle". Cuando un mismo related_handle aparece en muchas seeds,
-- es señal fuerte de que es relevante para la red FelyFit.
CREATE TABLE IF NOT EXISTS related_profiles_edges (
    seed_handle      TEXT NOT NULL,
    related_handle   TEXT NOT NULL,
    related_full_name TEXT,
    related_is_verified INTEGER DEFAULT 0,
    related_pic_url  TEXT,
    captured_at      TIMESTAMP DEFAULT (datetime('now')),
    PRIMARY KEY (seed_handle, related_handle)
);

CREATE INDEX IF NOT EXISTS idx_rpe_seed ON related_profiles_edges(seed_handle);
CREATE INDEX IF NOT EXISTS idx_rpe_related ON related_profiles_edges(related_handle);


-- Story snapshots — cada story capturada de una collab activa.
-- Stories duran 24h en IG, así que esto es time-series: scrape diario.
CREATE TABLE IF NOT EXISTS story_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    handle          TEXT NOT NULL REFERENCES candidates(handle),
    story_id        TEXT,                  -- ID único en IG (dedup)
    posted_at       TIMESTAMP,             -- timestamp original de IG
    expires_at      TIMESTAMP,             -- posted_at + 24h
    captured_at     TIMESTAMP DEFAULT (datetime('now')),

    -- Media
    media_type      TEXT,                  -- image / video
    media_url       TEXT,                  -- URL CDN (expira)
    local_media_path TEXT,                 -- path local (data/stories/<handle>/<story_id>.jpg|mp4)
    video_duration_s REAL,

    -- Contenido
    caption_text    TEXT,                  -- OCR/AI caption si está habilitado
    mentions        TEXT,                  -- JSON array de @handles
    hashtags        TEXT,                  -- JSON array
    link_url        TEXT,                  -- swipe-up / sticker link
    sticker_types   TEXT,                  -- JSON: poll, question, music, etc.

    -- Detección FelyFit
    is_felyfit_mention INTEGER DEFAULT 0,  -- 1 si menciona @felyfit_mx o #felyfit
    felyfit_detection_notes TEXT,          -- por qué se marcó

    -- Métricas
    views_count     INTEGER,               -- a veces null (cuentas grandes no exponen)

    -- Apify audit
    apify_run_id    TEXT,

    UNIQUE(handle, story_id)
);

CREATE INDEX IF NOT EXISTS idx_stories_handle ON story_snapshots(handle);
CREATE INDEX IF NOT EXISTS idx_stories_felyfit ON story_snapshots(is_felyfit_mention);
CREATE INDEX IF NOT EXISTS idx_stories_captured ON story_snapshots(captured_at DESC);


-- Access codes — códigos temporales que la admin genera para dar acceso
-- al dashboard sin compartir password fija.
CREATE TABLE IF NOT EXISTS access_codes (
    code         TEXT PRIMARY KEY,    -- 6 dígitos numéricos
    generated_by TEXT NOT NULL,       -- admin username
    generated_at TIMESTAMP DEFAULT (datetime('now')),
    expires_at   TIMESTAMP NOT NULL,
    used_at      TIMESTAMP,           -- NULL = no usado aún
    used_by      TEXT,                -- nombre que tecleó al entrar
    note         TEXT                 -- "Will para revisar pipeline"
);

CREATE INDEX IF NOT EXISTS idx_access_codes_expires ON access_codes(expires_at);


-- Lookup history — cada vez que Lucy hace un lookup en Stalkear se guarda
-- snapshot de métricas + recomendación de collab. Para retornar a comparar
-- decisiones pasadas / ver cómo evolucionó la creadora.
CREATE TABLE IF NOT EXISTS lookup_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    handle          TEXT NOT NULL,
    full_name       TEXT,
    looked_up_at    TIMESTAMP DEFAULT (datetime('now')),
    followers       INTEGER,
    engagement_rate REAL,
    tier            TEXT,
    fit_score       REAL,
    country         TEXT,
    gender          TEXT,
    account_type    TEXT,
    avg_likes       REAL,
    avg_comments    REAL,
    collab_type     TEXT,      -- recomendación: pr_pack/paid_*/intercambio/monthly_fee/skip/no_collab
    collab_label    TEXT,      -- label friendly
    collab_rationale TEXT,
    expected_emv    REAL,
    recommended_cash REAL,
    max_cash_investable REAL,
    profile_pic_url TEXT,
    bio             TEXT
);

CREATE INDEX IF NOT EXISTS idx_lookup_handle ON lookup_history(handle);
CREATE INDEX IF NOT EXISTS idx_lookup_at ON lookup_history(looked_up_at DESC);
"""


# ============================================================
# Libsql wrapper — emula la API de sqlite3 sobre HTTP a Turso.
# Acá vive toda la magia de "drop-in replacement". El código del proyecto
# no sabe si está hablando con SQLite local o Turso remoto.
# ============================================================
class _LibsqlRow:
    """Drop-in para sqlite3.Row — soporta row[0], row['col'], dict(row), .keys()."""
    __slots__ = ("_cols", "_vals", "_idx")

    def __init__(self, columns: Sequence[str], values: Sequence):
        self._cols = tuple(columns)
        self._vals = tuple(values)
        self._idx = {c: i for i, c in enumerate(columns)}

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._vals[key]
        if isinstance(key, slice):
            return self._vals[key]
        return self._vals[self._idx[key]]

    def __iter__(self):
        return iter(self._vals)

    def __len__(self):
        return len(self._vals)

    def keys(self) -> List[str]:
        return list(self._cols)

    def get(self, key, default=None):
        if isinstance(key, int):
            try:
                return self._vals[key]
            except IndexError:
                return default
        i = self._idx.get(key)
        return self._vals[i] if i is not None else default

    def __repr__(self):
        return f"Row({dict(zip(self._cols, self._vals))})"


class _LibsqlCursor:
    """Cursor compatible con sqlite3.Cursor + DB-API 2.0 (que es lo que pandas usa)."""
    def __init__(self, client=None, row_factory=None, result=None):
        # Puede ser construido vacío (vía conn.cursor()) y después .execute(),
        # o ya con un result (para conveniencia de conn.execute()).
        self._client = client
        self._row_factory = row_factory
        self._columns: List[str] = []
        self._rows: List = []
        self._iter = iter([])
        self.lastrowid = None
        self.rowcount = -1
        if result is not None:
            self._consume(result)

    def _consume(self, result) -> None:
        self._columns = list(result.columns) if result.columns else []
        self._rows = list(result.rows)
        self._iter = iter(self._rows)
        self.lastrowid = getattr(result, "last_insert_rowid", None)
        self.rowcount = getattr(result, "rows_affected", -1)

    @property
    def description(self):
        """DB-API 2.0: lista de 7-tuples (name, ...) por columna.
        Pandas read_sql_query usa esto para obtener nombres de columnas."""
        if not self._columns:
            return None
        return [(c, None, None, None, None, None, None) for c in self._columns]

    def execute(self, sql: str, params: Optional[Sequence] = None) -> "_LibsqlCursor":
        """Ejecutar y guardar resultados internamente. Retorna self (DB-API 2.0)."""
        if self._client is None:
            raise RuntimeError("Cursor sin cliente — usa conn.cursor() primero.")
        if params is None or len(params) == 0:
            result = self._client.execute(sql)
        else:
            result = self._client.execute(sql, list(params))
        self._consume(result)
        return self

    def executemany(self, sql: str, params_list) -> "_LibsqlCursor":
        for params in params_list:
            self.execute(sql, params)
        return self

    def _wrap(self, row):
        if self._row_factory is sqlite3.Row or self._row_factory is _LibsqlRow:
            return _LibsqlRow(self._columns, row)
        return tuple(row)

    def fetchall(self) -> List:
        return [self._wrap(r) for r in self._iter]

    def fetchone(self):
        try:
            r = next(self._iter)
        except StopIteration:
            return None
        return self._wrap(r)

    def fetchmany(self, size=None):
        out = []
        for _ in range(size or 1):
            try:
                out.append(self._wrap(next(self._iter)))
            except StopIteration:
                break
        return out

    def __iter__(self) -> Iterator:
        for r in self._iter:
            yield self._wrap(r)

    def close(self):
        pass


class _LibsqlConnection:
    """Connection compatible con sqlite3.Connection sobre HTTP libsql."""
    def __init__(self, client):
        self._client = client
        self.row_factory = None
        self._closed = False

    def execute(self, sql: str, params: Optional[Sequence] = None) -> _LibsqlCursor:
        cursor = _LibsqlCursor(client=self._client, row_factory=self.row_factory)
        cursor.execute(sql, params)
        return cursor

    def executemany(self, sql: str, params_list) -> _LibsqlCursor:
        cursor = _LibsqlCursor(client=self._client, row_factory=self.row_factory)
        cursor.executemany(sql, params_list)
        return cursor

    def executescript(self, script: str) -> None:
        """Ejecuta múltiples sentencias separadas por ;
        Usa batch() para enviar todo en 1 round-trip HTTP (vs N round-trips)."""
        import libsql_client
        statements = [s.strip() for s in _split_sql_statements(script) if s.strip()]
        if not statements:
            return
        # batch acepta lista de strings o Statement objects
        batched = [libsql_client.Statement(s) for s in statements]
        self._client.batch(batched)

    def commit(self) -> None:
        # libsql está en autocommit por default — no-op
        pass

    def rollback(self) -> None:
        # libsql no soporta rollback en autocommit
        pass

    def close(self) -> None:
        if not self._closed:
            try:
                self._client.close()
            except Exception:
                pass
            self._closed = True

    def cursor(self) -> _LibsqlCursor:
        """Retorna un cursor vacío. DB-API 2.0 (pandas read_sql lo usa)."""
        return _LibsqlCursor(client=self._client, row_factory=self.row_factory)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # No cerrar — el cliente se mantiene en cache global para reutilizar.
        # sqlite3's with block hace commit/rollback; aquí autocommit, no-op.
        pass


def _split_sql_statements(script: str) -> List[str]:
    """Separa SQL multi-statement por ';' fuera de strings/triggers.
    Versión simple — el schema actual no tiene triggers ni strings con ';'."""
    out = []
    current = []
    in_string = False
    string_char = None
    for char in script:
        if in_string:
            current.append(char)
            if char == string_char:
                in_string = False
        elif char in ('"', "'"):
            in_string = True
            string_char = char
            current.append(char)
        elif char == ';':
            out.append("".join(current))
            current = []
        else:
            current.append(char)
    if current and "".join(current).strip():
        out.append("".join(current))
    return out


# Cache global del libsql client — abrir/cerrar HTTP por cada query es caro
_libsql_client_cache = {"client": None}


def _get_libsql_client():
    """Returns a libsql_client.Client sync. Cached para reutilizar conexión HTTP."""
    if _libsql_client_cache["client"] is not None:
        return _libsql_client_cache["client"]
    import libsql_client
    url = _get_turso_url()
    if url.startswith("libsql://"):
        # libsql_client.create_client_sync usa https:// para HTTP API
        url = url.replace("libsql://", "https://", 1)
    client = libsql_client.create_client_sync(
        url=url,
        auth_token=_get_turso_token(),
    )
    _libsql_client_cache["client"] = client
    return client


def connect():
    """Get a connection with sane defaults.

    Returns Turso connection if TURSO_* env vars set, else local SQLite.
    En ambos casos, row_factory pre-seteado a sqlite3.Row (acceso por nombre).
    """
    if _use_turso():
        conn = _LibsqlConnection(_get_libsql_client())
        conn.row_factory = sqlite3.Row
        return conn

    # Fallback: SQLite local
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _ensure_column(conn, table: str, column: str, ddl: str) -> None:
    """Agrega columna a tabla existente si no la tiene. SQLite no tiene
    ADD COLUMN IF NOT EXISTS, así que checamos con PRAGMA primero."""
    cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def init():
    """Crear todas las tablas si no existen + migrar columnas faltantes.
    Idempotente — seguro de correr en cada startup."""
    with connect() as conn:
        conn.executescript(SCHEMA)

        # Migraciones: columnas añadidas al schema después de la creación inicial.
        # Para DBs viejas que aún no las tienen.
        _ensure_column(conn, "candidates", "country", "TEXT")
        _ensure_column(conn, "candidates", "gender", "TEXT")
        _ensure_column(conn, "candidates", "account_type", "TEXT")
        _ensure_column(conn, "candidates", "scout_run_id", "INTEGER")
        _ensure_column(conn, "scout_runs", "session_id", "TEXT")
        _ensure_column(conn, "scout_runs", "session_label", "TEXT")
        # Contenido pedido (JSON) + EMV proyectado al crear collab
        _ensure_column(conn, "collabs", "expected_content", "TEXT")
        _ensure_column(conn, "collabs", "expected_emv", "REAL")

    print(f"DB ready at {DB_PATH}")


if __name__ == "__main__":
    init()
