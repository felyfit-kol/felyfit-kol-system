"""SQLite connection + schema. Source of truth del sistema KOL.

Reglas:
- Solo este archivo conoce SQL. Otros modulos llaman funciones aqui.
- Cada candidata es unica por handle de IG (PRIMARY KEY).
- candidates.status es el state machine. Lark se actualiza en transiciones clave.
"""

import os
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "felyfit_kol.db"

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


def connect():
    """Get a connection with sane defaults."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # No detect_types: timestamps stay as strings (avoids ISO 'T' separator issues).
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

    print(f"DB ready at {DB_PATH}")


if __name__ == "__main__":
    init()
