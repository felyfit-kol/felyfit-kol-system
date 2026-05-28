"""Migra TODA la data del SQLite local a Turso.

Lee data/felyfit_kol.db (sqlite3) → escribe a Turso (libsql_client).
Idempotente: usa INSERT OR REPLACE para que se pueda re-ejecutar sin
duplicar.

Uso:
    .venv/bin/python migrate_to_turso.py

Requiere TURSO_DATABASE_URL + TURSO_AUTH_TOKEN en .env.
"""
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, List

from dotenv import load_dotenv

load_dotenv()

import libsql_client

LOCAL_DB = Path(__file__).parent / "data" / "felyfit_kol.db"

TABLES_TO_MIGRATE = [
    "candidates",
    "candidate_posts",
    "collabs",
    "collab_posts",
    "collab_post_snapshots",
    "scout_runs",
    "outreach_log",
    "config",
    "related_profiles_edges",
    "lookup_history",
    "access_codes",
]


def _normalize_url(url: str) -> str:
    """libsql:// → https:// para HTTP API."""
    return url.replace("libsql://", "https://", 1) if url.startswith("libsql://") else url


def _table_exists_in_local(local: sqlite3.Connection, table: str) -> bool:
    row = local.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _get_columns(local: sqlite3.Connection, table: str) -> List[str]:
    return [r["name"] for r in local.execute(f"PRAGMA table_info({table})").fetchall()]


def migrate_table(local: sqlite3.Connection, remote, table: str) -> dict:
    """Copia table local → remote. Returns dict con stats."""
    if not _table_exists_in_local(local, table):
        return {"table": table, "skipped": True, "reason": "no existe en local"}

    cols = _get_columns(local, table)
    if not cols:
        return {"table": table, "skipped": True, "reason": "sin columnas"}

    # Tabla tiene columnas en local que pueden no existir en Turso (si schema cambió).
    # Filtramos a las que SI existen en Turso.
    remote_cols_result = remote.execute(f"PRAGMA table_info({table})")
    remote_cols = {r[1] for r in remote_cols_result.rows}
    if not remote_cols:
        return {"table": table, "skipped": True, "reason": "no existe en Turso (corre db.init primero)"}

    common_cols = [c for c in cols if c in remote_cols]
    if not common_cols:
        return {"table": table, "skipped": True, "reason": "sin columnas en común"}

    rows = local.execute(
        f"SELECT {','.join(common_cols)} FROM {table}"
    ).fetchall()

    if not rows:
        return {"table": table, "inserted": 0, "columns": common_cols}

    # INSERT OR REPLACE para idempotencia
    placeholders = ",".join("?" * len(common_cols))
    sql = (
        f"INSERT OR REPLACE INTO {table} ({','.join(common_cols)}) "
        f"VALUES ({placeholders})"
    )

    # libsql_client.batch() acepta múltiples statements
    statements = []
    for row in rows:
        values = [row[c] for c in common_cols]
        statements.append(libsql_client.Statement(sql, values))

    # batch en chunks de 100 para no exceder limits
    BATCH = 100
    inserted = 0
    for i in range(0, len(statements), BATCH):
        chunk = statements[i:i + BATCH]
        remote.batch(chunk)
        inserted += len(chunk)
        print(f"    chunk {i // BATCH + 1}/{(len(statements) + BATCH - 1) // BATCH}: {inserted} filas", flush=True)

    return {"table": table, "inserted": inserted, "columns": len(common_cols)}


def main() -> None:
    if not LOCAL_DB.exists():
        print(f"❌ No existe DB local en {LOCAL_DB}")
        sys.exit(1)

    url = os.environ.get("TURSO_DATABASE_URL")
    token = os.environ.get("TURSO_AUTH_TOKEN")
    if not url or not token:
        print("❌ Falta TURSO_DATABASE_URL o TURSO_AUTH_TOKEN en .env")
        sys.exit(1)

    print(f"🚀 Migrando {LOCAL_DB} → {url}")

    local = sqlite3.connect(str(LOCAL_DB))
    local.row_factory = sqlite3.Row

    remote = libsql_client.create_client_sync(
        url=_normalize_url(url), auth_token=token
    )

    try:
        for table in TABLES_TO_MIGRATE:
            print(f"\n📦 {table}")
            try:
                stats = migrate_table(local, remote, table)
                if stats.get("skipped"):
                    print(f"  ⏭  skip: {stats.get('reason')}")
                else:
                    print(f"  ✅ {stats['inserted']:,} filas insertadas")
            except Exception as e:
                print(f"  ❌ Error: {type(e).__name__}: {e}")

        # Verificación final: contar en remote
        print("\n📊 Conteos en Turso (verificación):")
        for table in TABLES_TO_MIGRATE:
            try:
                n = remote.execute(f"SELECT COUNT(*) FROM {table}").rows[0][0]
                print(f"  {table}: {n:,}")
            except Exception:
                print(f"  {table}: (no existe)")

    finally:
        remote.close()
        local.close()

    print("\n✅ Migración completa")


if __name__ == "__main__":
    main()
