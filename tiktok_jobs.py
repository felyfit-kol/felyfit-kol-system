"""TikTok scraping via Apify (clockworks/tiktok-scraper).

Diseño paralelo a apify_jobs.py pero para el universo TT:
- enrich_tiktok_profile(handle): scrape perfil + últimos N videos, guardar
  en tiktok_candidates + tiktok_videos, calcular avg_L/C/V/S/save/ER.
- snapshot_tiktok_account(handle): snapshot semanal para tabla
  tiktok_account_snapshots (equivalente a snapshot_account de IG).
- lookup_tiktok_profile(handle): variante para "Stalkear" — no persiste
  en tiktok_candidates ni tiktok_videos (solo scrape + guarda snapshot en
  tiktok_lookup_history).

Cost: clockworks/tiktok-scraper ~$0.30 por 1000 results. Un enrich típico
(1 profile + 30 videos) cuesta ~$0.009 USD.
"""
import os
from datetime import datetime
from typing import Dict, List, Optional

from dotenv import load_dotenv

import config
import db

load_dotenv()

# Reutilizamos el cliente Apify de apify_jobs (mismo token, mismo ApifyClient)
import apify_jobs


def _extract_profile_dict(item: Dict) -> Dict:
    """De un item devuelto por clockworks/tiktok-scraper, extrae los campos
    del perfil desde `authorMeta`. Devuelve dict con keys normalizadas
    para la tabla tiktok_candidates."""
    am = item.get("authorMeta") or {}
    ci = am.get("commerceUserInfo") or {}
    create_ts = am.get("createTime")
    created_iso = None
    if isinstance(create_ts, (int, float)) and create_ts > 0:
        try:
            created_iso = datetime.fromtimestamp(create_ts).isoformat(timespec="seconds")
        except Exception:
            pass
    return {
        "handle": (am.get("name") or "").lower().lstrip("@"),
        "tiktok_id": str(am.get("id") or "") or None,
        "nickname": am.get("nickName") or None,
        "bio": am.get("signature") or None,
        "bio_link": am.get("bioLink") or None,
        "followers": int(am.get("fans") or 0),
        "following": int(am.get("following") or 0),
        "friends": int(am.get("friends") or 0),
        "total_hearts": int(am.get("heart") or 0),
        "likes_given": int(am.get("digg") or 0),
        "video_count": int(am.get("video") or 0),
        "is_verified": 1 if am.get("verified") else 0,
        "is_private": 1 if am.get("privateAccount") else 0,
        "is_commerce_user": 1 if ci.get("commerceUser") else 0,
        "is_tt_seller": 1 if am.get("ttSeller") else 0,
        "has_active_story": 1 if am.get("hasActiveStory") else 0,
        "profile_pic_url": am.get("originalAvatarUrl") or am.get("avatar") or None,
        "account_created_at": created_iso,
    }


def _extract_video_dict(item: Dict) -> Dict:
    """Extrae métricas de un video (item top-level) para tiktok_videos."""
    vm = item.get("videoMeta") or {}
    create_ts = item.get("createTime")
    posted_iso = item.get("createTimeISO")
    if not posted_iso and isinstance(create_ts, (int, float)) and create_ts > 0:
        try:
            posted_iso = datetime.fromtimestamp(create_ts).isoformat(timespec="seconds")
        except Exception:
            pass
    return {
        "video_id": str(item.get("id") or "") or None,
        "video_url": item.get("webVideoUrl") or None,
        "posted_at": posted_iso,
        "likes": int(item.get("diggCount") or 0),
        "comments": int(item.get("commentCount") or 0),
        "views": int(item.get("playCount") or 0),
        "shares": int(item.get("shareCount") or 0),
        "saves": int(item.get("collectCount") or 0),
        "duration_s": int(vm.get("duration") or 0) or None,
        "caption": item.get("text") or None,
        "cover_url": vm.get("coverUrl") or None,
    }


def _run_actor(profiles: List[str], results_per_page: int = 30) -> List[Dict]:
    """Corre el actor y devuelve todos los items del dataset."""
    actor = config.APIFY_ACTORS["tiktok_scraper"]
    run = apify_jobs.client().actor(actor).call(run_input={
        "profiles": profiles,
        "resultsPerPage": results_per_page,
        "shouldDownloadCovers": False,
        "shouldDownloadVideos": False,
    })
    items: List[Dict] = []
    for item in apify_jobs.client().dataset(run["defaultDatasetId"]).iterate_items():
        items.append(item)
    return items


def _compute_metrics(videos: List[Dict]) -> Dict:
    """Calcula avg_likes/comments/views/shares/saves + ER a partir de una
    lista de dicts de video (ya extraídos por _extract_video_dict)."""
    if not videos:
        return dict(avg_likes=None, avg_comments=None, avg_views=None,
                    avg_shares=None, avg_saves=None,
                    last_post_at=None)
    n = len(videos)
    tot_L = sum(v.get("likes") or 0 for v in videos)
    tot_C = sum(v.get("comments") or 0 for v in videos)
    tot_V = sum(v.get("views") or 0 for v in videos)
    tot_S = sum(v.get("shares") or 0 for v in videos)
    tot_sv = sum(v.get("saves") or 0 for v in videos)
    # Último post publicado (más reciente)
    posted = [v.get("posted_at") for v in videos if v.get("posted_at")]
    last_post = max(posted) if posted else None
    return dict(
        avg_likes=tot_L / n,
        avg_comments=tot_C / n,
        avg_views=tot_V / n,
        avg_shares=tot_S / n,
        avg_saves=tot_sv / n,
        last_post_at=last_post,
    )


def enrich_tiktok_profile(handle: str, results_per_page: int = 30) -> Dict:
    """Scrape perfil + hasta N videos, upsert en tiktok_candidates,
    inserta videos en tiktok_videos, recalcula métricas.
    """
    handle = handle.lower().lstrip("@").strip()
    if not handle:
        return {"error": "handle vacío"}

    items = _run_actor([handle], results_per_page=results_per_page)
    if not items:
        return {"error": f"Apify devolvió 0 items para @{handle}", "handle": handle}

    # El actor a veces devuelve UN item de perfil sin videos (perfil vacío)
    # y otras veces devuelve N items de video, cada uno con authorMeta idéntico.
    # Tomamos el authorMeta del primer item que lo tenga.
    profile_item = next((it for it in items if it.get("authorMeta")), None)
    if not profile_item:
        # Puede ser {'error': ..., 'errorCode': ...} → perfil no existe
        err = items[0].get("error") or "sin datos de perfil"
        return {"error": err, "handle": handle}

    profile = _extract_profile_dict(profile_item)
    if not profile["handle"]:
        return {"error": "handle vacío en respuesta", "handle": handle}

    # Videos = items que tienen id (i.e. no son solo profile-info-empty)
    video_dicts: List[Dict] = []
    for it in items:
        if not it.get("id"):
            continue
        vd = _extract_video_dict(it)
        if vd["video_id"]:
            video_dicts.append(vd)

    metrics = _compute_metrics(video_dicts)
    er = None
    followers = profile.get("followers") or 0
    if followers > 0 and metrics.get("avg_likes") is not None:
        er = ((metrics["avg_likes"] or 0) + (metrics["avg_comments"] or 0)) / followers

    with db.connect() as conn:
        existing = conn.execute(
            "SELECT handle FROM tiktok_candidates WHERE handle=?", (profile["handle"],)
        ).fetchone()

        cols_to_update = {
            **profile,
            **metrics,
            "engagement_rate": er,
            "last_enriched_at": datetime.now().isoformat(timespec="seconds"),
        }
        if existing:
            sets = ", ".join(f"{k}=?" for k in cols_to_update if k != "handle")
            vals = [v for k, v in cols_to_update.items() if k != "handle"]
            vals.append(profile["handle"])
            conn.execute(f"UPDATE tiktok_candidates SET {sets} WHERE handle=?",
                          tuple(vals))
        else:
            cols_to_update["discovered_at"] = datetime.now().isoformat(timespec="seconds")
            cols_to_update.setdefault("status", "discovered")
            keys = list(cols_to_update.keys())
            placeholders = ", ".join(["?"] * len(keys))
            conn.execute(
                f"INSERT INTO tiktok_candidates ({', '.join(keys)}) "
                f"VALUES ({placeholders})",
                tuple(cols_to_update[k] for k in keys),
            )

        # Insertar videos (INSERT OR IGNORE — dedup por video_id UNIQUE)
        for vd in video_dicts:
            conn.execute(
                "INSERT OR IGNORE INTO tiktok_videos "
                "(handle, video_id, video_url, posted_at, likes, comments, "
                " views, shares, saves, duration_s, caption, cover_url) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (profile["handle"], vd["video_id"], vd["video_url"],
                  vd["posted_at"], vd["likes"], vd["comments"], vd["views"],
                  vd["shares"], vd["saves"], vd["duration_s"], vd["caption"],
                  vd["cover_url"]),
            )

    return {
        "handle": profile["handle"],
        "followers": followers,
        "total_hearts": profile.get("total_hearts") or 0,
        "video_count": profile.get("video_count") or 0,
        "videos_scraped": len(video_dicts),
        "engagement_rate": er,
        **metrics,
    }


def snapshot_tiktok_account(handle: str) -> Dict:
    """Snapshot semanal de una cuenta TT (para tracking en Dashboard).
    Guarda en tiktok_account_snapshots. NO toca tiktok_candidates."""
    handle = handle.lower().lstrip("@").strip()
    if not handle:
        return {"error": "handle vacío"}

    items = _run_actor([handle], results_per_page=12)
    if not items:
        return {"error": f"Apify devolvió 0 items para @{handle}", "handle": handle}

    profile_item = next((it for it in items if it.get("authorMeta")), None)
    if not profile_item:
        return {"error": "sin datos de perfil", "handle": handle}
    profile = _extract_profile_dict(profile_item)

    video_dicts = [_extract_video_dict(it) for it in items if it.get("id")]

    # Guard: si el perfil dice hay videos pero el actor no trajo ninguno,
    # es falla transient — NO guardamos snapshot (mismo pattern que IG).
    video_count = profile.get("video_count") or 0
    if video_count > 0 and not video_dicts:
        return {
            "error": (f"Apify devolvió perfil pero sin videos (video_count={video_count}, "
                       "items=0). Falla transient. No guardo snapshot."),
            "handle": handle,
            "followers": profile.get("followers") or 0,
        }

    metrics = _compute_metrics(video_dicts)
    er = None
    followers = profile.get("followers") or 0
    if followers > 0 and metrics.get("avg_likes") is not None:
        er = ((metrics["avg_likes"] or 0) + (metrics["avg_comments"] or 0)) / followers

    with db.connect() as conn:
        conn.execute(
            "INSERT INTO tiktok_account_snapshots "
            "(handle, followers, following, total_hearts, video_count, "
            " avg_likes, avg_comments, avg_views, avg_shares, avg_saves, "
            " engagement_rate, bio, nickname, is_verified) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (handle, followers, profile.get("following") or 0,
              profile.get("total_hearts") or 0, video_count,
              metrics.get("avg_likes"), metrics.get("avg_comments"),
              metrics.get("avg_views"), metrics.get("avg_shares"),
              metrics.get("avg_saves"), er, profile.get("bio"),
              profile.get("nickname"), profile.get("is_verified") or 0),
        )
    return {
        "handle": handle,
        "followers": followers,
        "video_count": video_count,
        "engagement_rate": er,
        **metrics,
    }


def lookup_tiktok_profile(handle: str) -> Dict:
    """Variant para Stalkear TT: scrape + guarda snapshot en
    tiktok_lookup_history (NO en tiktok_candidates). Ideal para revisar
    perfiles casuales sin comprometerse a pipeline."""
    handle = handle.lower().lstrip("@").strip()
    if not handle:
        return {"error": "handle vacío"}

    items = _run_actor([handle], results_per_page=12)
    if not items:
        return {"error": f"Apify devolvió 0 items", "handle": handle}
    profile_item = next((it for it in items if it.get("authorMeta")), None)
    if not profile_item:
        err = items[0].get("error") or "sin datos"
        return {"error": err, "handle": handle}

    profile = _extract_profile_dict(profile_item)
    video_dicts = [_extract_video_dict(it) for it in items if it.get("id")]
    metrics = _compute_metrics(video_dicts)

    followers = profile.get("followers") or 0
    er = None
    if followers > 0 and metrics.get("avg_likes") is not None:
        er = ((metrics["avg_likes"] or 0) + (metrics["avg_comments"] or 0)) / followers

    with db.connect() as conn:
        conn.execute(
            "INSERT INTO tiktok_lookup_history "
            "(handle, nickname, followers, total_hearts, video_count, "
            " engagement_rate, avg_likes, avg_comments, avg_views, "
            " profile_pic_url, bio) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (profile["handle"], profile.get("nickname"), followers,
              profile.get("total_hearts") or 0, profile.get("video_count") or 0,
              er, metrics.get("avg_likes"), metrics.get("avg_comments"),
              metrics.get("avg_views"), profile.get("profile_pic_url"),
              profile.get("bio")),
        )

    return {
        "handle": profile["handle"],
        "nickname": profile.get("nickname"),
        "followers": followers,
        "total_hearts": profile.get("total_hearts") or 0,
        "video_count": profile.get("video_count") or 0,
        "is_verified": bool(profile.get("is_verified")),
        "is_private": bool(profile.get("is_private")),
        "bio": profile.get("bio"),
        "bio_link": profile.get("bio_link"),
        "profile_pic_url": profile.get("profile_pic_url"),
        "account_created_at": profile.get("account_created_at"),
        "videos_scraped": len(video_dicts),
        "engagement_rate": er,
        **metrics,
        # Muestra top 3 videos por views para preview en Stalkear
        "top_videos": sorted(video_dicts,
                              key=lambda v: v.get("views") or 0,
                              reverse=True)[:3],
    }
