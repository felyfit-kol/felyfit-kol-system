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


def main() -> int:
    """Devuelve exit code: 0 OK, 1 si todos los posts fallaron (problema
    sistémico tipo Apify bloqueado). 0 si simplemente no hay collabs.
    """
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

    total_snapshots = 0
    total_completed = 0
    total_failures = 0

    if not collabs:
        log("No hay collabs activas en tracking.")
    else:
        log(f"Encontradas {len(collabs)} collab(s) en tracking")

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
                    total_failures += 1
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
                total_failures += 1

    log(f"Collabs done · snapshots: {total_snapshots} · completed: {total_completed} · failures: {total_failures}")

    # ── Refresh de posts de EVENTOS activos ──
    # Los eventos no tienen ventana de tracking cerrada (a diferencia de
    # collabs). Se refrescan mientras estén en status='active'. Cuando el
    # usuario los marca 'completed' manualmente dejan de refrescarse.
    with db.connect() as conn:
        events_active = conn.execute("""
            SELECT id, name FROM events WHERE status = 'active'
        """).fetchall()

    ev_snapshots = 0
    ev_failures = 0
    if events_active:
        log(f"Encontrados {len(events_active)} evento(s) activo(s)")
        for ev in events_active:
            eid = ev["id"]
            log(f"  Evento #{eid} ('{ev['name']}')")
            with db.connect() as conn:
                ep = conn.execute(
                    "SELECT post_url FROM event_posts WHERE event_id=?", (eid,)
                ).fetchall()
            if not ep:
                log(f"    (sin posts vinculados — skip)")
                continue
            for p in ep:
                post_url = p["post_url"]
                try:
                    result = apify_jobs.snapshot_event_post(eid, post_url)
                    if result.get("error"):
                        log(f"    ❌ {post_url}: {result['error']}")
                        ev_failures += 1
                    else:
                        log(f"    ✓ {post_url[:60]}… "
                             f"{result['likes']}L · {result['comments']}C · {result['views']}V")
                        ev_snapshots += 1
                except Exception as e:
                    log(f"    ❌ {post_url}: {type(e).__name__}: {e}")
                    ev_failures += 1
        log(f"Events done · snapshots: {ev_snapshots} · failures: {ev_failures}")
    else:
        log("No hay eventos activos.")

    total_all_snapshots = total_snapshots + ev_snapshots
    total_all_failures = total_failures + ev_failures
    # Exit != 0 si TODO falló (problema sistémico). Si solo algunos posts
    # fallaron pero otros funcionaron, es ruido aceptable.
    return 1 if (total_all_failures > 0 and total_all_snapshots == 0) else 0


if __name__ == "__main__":
    exit_code = 0
    try:
        exit_code = main() or 0
    except Exception as e:
        log(f"Fatal: {type(e).__name__}: {e}")
        exit_code = 1
    finally:
        # Cierra el libsql client para que el proceso pueda salir.
        # Sin esto, threads internos del cliente HTTP mantienen el proceso vivo
        # hasta el timeout (30min en GH Actions = canceled).
        try:
            db.close_libsql()
        except Exception:
            pass
        sys.exit(exit_code)
