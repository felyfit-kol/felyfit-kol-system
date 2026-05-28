"""Snapshot semanal de cuentas trackeadas (empezando por @felyfit_mx).

Por ahora trackea SOLO felyfit_mx. Cuando agreguemos más cuentas (competidores,
campañas, etc.) se extiende la lista TRACKED_ACCOUNTS o se lee de DB.

Uso:
    .venv/bin/python scheduled_weekly_snapshot.py

Programar con GitHub Actions: cada lunes 11 AM CDMX (17:00 UTC).
"""
import sys
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

import db
import apify_jobs

LOG_FILE = PROJECT_DIR / "data" / "weekly_snapshot.log"

# Cuentas a trackear semanalmente. Extender aquí cuando haya más.
TRACKED_ACCOUNTS = ["felyfit_mx"]


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def main() -> None:
    db.init()
    log("=" * 60)
    log("Weekly account snapshot iniciado")

    for handle in TRACKED_ACCOUNTS:
        log(f"Snapshotting @{handle}…")
        try:
            res = apify_jobs.snapshot_account(handle)
            if res.get("error"):
                log(f"  ❌ {res['error']}")
            else:
                log(
                    f"  ✓ {res['followers']:,} followers · "
                    f"{res['posts_count']:,} posts · "
                    f"ER {res['engagement_rate']*100:.2f}%"
                )
        except Exception as e:
            log(f"  ❌ Exception: {type(e).__name__}: {e}")

    log("Done.")


if __name__ == "__main__":
    try:
        main()
    finally:
        try:
            db.close_libsql()
        except Exception:
            pass
        sys.exit(0)
