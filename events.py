"""Módulo de eventos — CRUD y helpers.

Un evento agrupa múltiples posts (de múltiples creadoras) alrededor de
una experiencia física (match day, activación, evento). Se calcula ROI
comparando EMV agregado contra la inversión desglosada del evento.

Design:
    - `events` guarda inversión (venue/producción/kits/logística/otros)
      y EMV agregado (recalc en cada refresh).
    - `event_posts` = URLs de IG vinculadas al evento.
    - `event_post_snapshots` = time-series de likes/views por post.
    - Un post puede estar en un evento Y en una collab a la vez
      (double-count intencional con flag visible en UI).
"""
from datetime import date
from typing import Optional

import db


def create_event(
    name: str,
    event_type: str = "match_day",
    event_date: Optional[date] = None,
    venue_cost: float = 0.0,
    production_cost: float = 0.0,
    gift_cost: float = 0.0,
    logistics_cost: float = 0.0,
    other_cost: float = 0.0,
    notes: Optional[str] = None,
) -> int:
    """Crea un evento nuevo. Devuelve su id."""
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO events "
            "(name, event_type, event_date, venue_cost, production_cost, "
            " gift_cost, logistics_cost, other_cost, status, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)",
            (name.strip(), event_type,
              event_date.isoformat() if event_date else None,
              venue_cost, production_cost, gift_cost, logistics_cost,
              other_cost, notes),
        )
        # libsql client soporta cur.lastrowid via wrapper _LibsqlCursor
        row = conn.execute(
            "SELECT id FROM events WHERE name=? ORDER BY id DESC LIMIT 1",
            (name.strip(),),
        ).fetchone()
        return int(row["id"]) if row else 0


def add_post_to_event(event_id: int, post_url: str,
                       handle: Optional[str] = None,
                       post_type: Optional[str] = None) -> bool:
    """Vincula un post URL a un evento. Devuelve False si ya existía.
    handle/post_type son opcionales — el scrape los llenará después."""
    post_url = post_url.strip()
    if not post_url:
        return False
    with db.connect() as conn:
        existing = conn.execute(
            "SELECT id FROM event_posts WHERE event_id=? AND post_url=?",
            (event_id, post_url),
        ).fetchone()
        if existing:
            return False
        conn.execute(
            "INSERT INTO event_posts (event_id, post_url, handle, post_type) "
            "VALUES (?, ?, ?, ?)",
            (event_id, post_url,
              (handle or "").lower().lstrip("@") or None,
              post_type),
        )
    return True


def remove_post_from_event(event_id: int, post_url: str) -> None:
    """Quita un post del evento. Los snapshots históricos se conservan."""
    with db.connect() as conn:
        conn.execute(
            "DELETE FROM event_posts WHERE event_id=? AND post_url=?",
            (event_id, post_url),
        )


def list_events(status: Optional[str] = None) -> list:
    """Lista eventos con inversión total pre-computada."""
    where = ""
    params: tuple = ()
    if status:
        where = "WHERE status = ?"
        params = (status,)
    with db.connect() as conn:
        rows = conn.execute(f"""
            SELECT id, name, event_type, event_date, status, notes,
                   venue_cost, production_cost, gift_cost,
                   logistics_cost, other_cost,
                   COALESCE(venue_cost, 0) + COALESCE(production_cost, 0) +
                   COALESCE(gift_cost, 0) + COALESCE(logistics_cost, 0) +
                   COALESCE(other_cost, 0) AS total_investment,
                   total_likes, total_comments, total_views,
                   emv_mxn, emv_roi_ratio, last_recalc_at, created_at
            FROM events {where}
            ORDER BY COALESCE(event_date, created_at) DESC
        """, params).fetchall()
    return [dict(r) for r in rows]


def get_event(event_id: int) -> Optional[dict]:
    events = list_events()
    for e in events:
        if e["id"] == event_id:
            return e
    return None


def get_event_posts(event_id: int) -> list:
    """Posts del evento + flag de double-count (si el URL también está en
    collab_posts). Ordenados por posted_at desc."""
    with db.connect() as conn:
        rows = conn.execute("""
            SELECT ep.id, ep.post_url, ep.handle, ep.post_type,
                   ep.posted_at, ep.added_at, ep.last_scraped_at,
                   CASE WHEN cp.id IS NOT NULL THEN 1 ELSE 0 END AS in_collab,
                   cp.collab_id AS collab_id
            FROM event_posts ep
            LEFT JOIN collab_posts cp ON cp.post_url = ep.post_url
            WHERE ep.event_id = ?
            ORDER BY COALESCE(ep.posted_at, ep.added_at) DESC
        """, (event_id,)).fetchall()
    return [dict(r) for r in rows]


def update_event(event_id: int, **fields) -> None:
    """Update parcial. Solo pasa los campos que quieras cambiar."""
    allowed = {"name", "event_type", "event_date", "status", "notes",
                "venue_cost", "production_cost", "gift_cost",
                "logistics_cost", "other_cost"}
    clean = {k: v for k, v in fields.items() if k in allowed}
    if not clean:
        return
    cols = ", ".join(f"{k}=?" for k in clean)
    values = list(clean.values()) + [event_id]
    with db.connect() as conn:
        conn.execute(f"UPDATE events SET {cols} WHERE id=?", tuple(values))


def delete_event(event_id: int) -> None:
    """Borra evento + todos sus posts vinculados + snapshots.
    Solo permitido si status != 'completed' (data histórica).
    """
    with db.connect() as conn:
        conn.execute("DELETE FROM event_post_snapshots WHERE event_id=?",
                      (event_id,))
        conn.execute("DELETE FROM event_posts WHERE event_id=?", (event_id,))
        conn.execute("DELETE FROM events WHERE id=?", (event_id,))
