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
import tiktok_jobs

LOG_FILE = PROJECT_DIR / "data" / "weekly_snapshot.log"

# Cuentas a trackear semanalmente en cada plataforma.
TRACKED_ACCOUNTS = ["felyfit_mx"]        # Instagram
TRACKED_TT_ACCOUNTS = ["felyfit_mx"]     # TikTok (@felyfit_mx TT existe pero
                                          # aún sin videos — el snapshot va a
                                          # capturar followers=0 hasta que suba
                                          # su primer video)


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def main() -> int:
    """Devuelve 0 si todos los handles snapshot OK, 1 si alguno falló.
    Así GitHub Actions marca el workflow como failure cuando Apify
    rechaza requests (invoice impaga, rate limit, etc.) y te notifica.
    """
    db.init()
    log("=" * 60)
    log("Weekly account snapshot iniciado")

    failed = 0
    for handle in TRACKED_ACCOUNTS:
        log(f"[IG] Snapshotting @{handle}…")
        try:
            res = apify_jobs.snapshot_account(handle)
            if res.get("error"):
                log(f"  ❌ {res['error']}")
                failed += 1
            else:
                log(
                    f"  ✓ {res['followers']:,} followers · "
                    f"{res['posts_count']:,} posts · "
                    f"ER {res['engagement_rate']*100:.2f}%"
                )
        except Exception as e:
            log(f"  ❌ Exception: {type(e).__name__}: {e}")
            failed += 1

    # TikTok snapshots
    for handle in TRACKED_TT_ACCOUNTS:
        log(f"[TT] Snapshotting @{handle}…")
        try:
            res = tiktok_jobs.snapshot_tiktok_account(handle)
            if res.get("error"):
                log(f"  ❌ {res['error']}")
                # Perfil TT sin videos NO es error crítico (@felyfit_mx no
                # ha subido nada). Solo contamos como failed si el mensaje
                # sugiere problema sistémico (Apify bloqueado, network, etc.).
                if "transient" not in res["error"].lower() and \
                    "sin datos" not in res["error"].lower():
                    failed += 1
            else:
                er = res.get("engagement_rate") or 0
                log(
                    f"  ✓ {res['followers']:,} fans · "
                    f"{res.get('video_count') or 0:,} videos · "
                    f"ER {er*100:.2f}%"
                )
        except Exception as e:
            log(f"  ❌ Exception: {type(e).__name__}: {e}")
            failed += 1

    total = len(TRACKED_ACCOUNTS) + len(TRACKED_TT_ACCOUNTS)
    if failed:
        log(f"Done con errores: {failed}/{total} handle(s) fallaron.")
        return 1
    log("Done OK.")
    return 0


if __name__ == "__main__":
    exit_code = 0
    try:
        exit_code = main()
    except Exception as e:
        log(f"Fatal: {type(e).__name__}: {e}")
        exit_code = 1
    finally:
        try:
            db.close_libsql()
        except Exception:
            pass
        sys.exit(exit_code)
