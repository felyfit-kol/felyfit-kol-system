"""Refresh diario de métricas para collabs activas.

Para cada collab con status='posted' y dentro de su ventana de tracking
(track_days desde tracking_started_at), scrapea cada post vinculado y guarda
un snapshot. Al final, auto-marca como 'completed' si excede track_days.

Uso:
    .venv/bin/python scheduled_metrics_refresh.py

Programar con launchd: com.felyfit.collab-metrics.plist (1×/día 9 AM).
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

import db
import apify_jobs

LOG_FILE = PROJECT_DIR / "data" / "collab_metrics.log"


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def _days_since(iso_str: str) -> int:
    if not iso_str:
        return 0
    try:
        dt = datetime.fromisoformat(iso_str)
        return (datetime.now() - dt).days
    except Exception:
        return 0


def main() -> None:
    db.init()
    log("=" * 60)
    log("Daily collab metrics refresh iniciado")

    with db.connect() as conn:
        collabs = conn.execute("""
            SELECT id, handle, campaign_name, status,
                   tracking_started_at, track_days
            FROM collabs
            WHERE status = 'posted'
        """).fetchall()

    if not collabs:
        log("No hay collabs activas en tracking. Done.")
        return

    log(f"Encontradas {len(collabs)} collab(s) en tracking")

    total_snapshots = 0
    total_completed = 0

    for c in collabs:
        cid = c["id"]
        handle = c["handle"]
        track_days = c["track_days"] or 14
        days = _days_since(c["tracking_started_at"])
        log(f"  Collab #{cid} (@{handle}, '{c['campaign_name']}') · día {days}/{track_days}")

        # Si excedió ventana, marcar como completed
        if days >= track_days:
            with db.connect() as conn:
                conn.execute(
                    "UPDATE collabs SET status='completed', tracking_ended_at=? WHERE id=?",
                    (datetime.now().isoformat(timespec="seconds"), cid),
                )
            log(f"    ✓ Auto-marcada como completed ({days}d >= {track_days}d)")
            total_completed += 1
            continue

        # Scrape cada post vinculado
        with db.connect() as conn:
            posts = conn.execute(
                "SELECT post_url FROM collab_posts WHERE collab_id=?", (cid,)
            ).fetchall()
        if not posts:
            log(f"    (sin posts vinculados — skip)")
            continue

        for p in posts:
            post_url = p["post_url"]
            try:
                result = apify_jobs.snapshot_collab_post(cid, post_url)
                if result.get("error"):
                    log(f"    ❌ {post_url}: {result['error']}")
                else:
                    log(f"    ✓ {post_url[:60]}… "
                         f"{result['likes']}L · {result['comments']}C · {result['views']}V")
                    with db.connect() as conn:
                        conn.execute(
                            "UPDATE collab_posts SET last_scraped_at=? "
                            "WHERE collab_id=? AND post_url=?",
                            (datetime.now().isoformat(timespec="seconds"), cid, post_url)
                        )
                    total_snapshots += 1
            except Exception as e:
                log(f"    ❌ {post_url}: {type(e).__name__}: {e}")

    log(f"Done · snapshots: {total_snapshots} · completed: {total_completed}")


if __name__ == "__main__":
    try:
        main()
    finally:
        # Cierra el libsql client para que el proceso pueda salir.
        # Sin esto, threads internos del cliente HTTP mantienen el proceso vivo
        # hasta el timeout (30min en GH Actions = canceled).
        try:
            db.close_libsql()
        except Exception:
            pass
        sys.exit(0)
