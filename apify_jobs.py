"""Apify jobs: scouting por hashtag + enriquecimiento de perfiles + tracking de posts.

Diseno:
- Cada funcion encapsula UNA llamada a Apify y persiste resultado a SQLite.
- Devuelve resumen (dict) para el caller / UI.
- Cuesta dinero: la UI debe pedir confirmacion antes de correr esto.
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx
from apify_client import ApifyClient
from dotenv import load_dotenv

import config
import db
import scoring

load_dotenv()

PROFILE_PIC_DIR = Path(__file__).parent / "data" / "profile_pics"
PROFILE_PIC_DIR.mkdir(parents=True, exist_ok=True)


def download_profile_pic(handle: str, url: str) -> Optional[str]:
    """Descarga la foto de perfil a disco local. Devuelve path absoluto o None."""
    if not url:
        return None
    safe = handle.replace("/", "_").replace(" ", "_")
    local = PROFILE_PIC_DIR / f"{safe}.jpg"
    try:
        r = httpx.get(url, timeout=15, follow_redirects=True)
        r.raise_for_status()
        local.write_bytes(r.content)
        return str(local)
    except Exception as e:
        print(f"  ⚠ photo download fail {handle}: {e}")
        return None

_client: Optional[ApifyClient] = None


def client() -> ApifyClient:
    global _client
    if _client is None:
        token = os.environ["APIFY_TOKEN"]
        _client = ApifyClient(token)
    return _client


# ============================================================
# Helpers de DB
# ============================================================
def _start_scout_run(source: str, source_detail: str, actor: str,
                     session_id: Optional[str] = None,
                     session_label: Optional[str] = None) -> int:
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO scout_runs (source, source_detail, apify_actor, status, "
            "                        session_id, session_label) "
            "VALUES (?, ?, ?, 'running', ?, ?)",
            (source, source_detail, actor, session_id, session_label),
        )
        return cur.lastrowid


def _finish_scout_run(run_id: int, *, status: str, apify_run_id: Optional[str] = None,
                     candidates_seen: int = 0, candidates_new: int = 0,
                     compute_usd: float = 0.0, error: Optional[str] = None) -> None:
    with db.connect() as conn:
        conn.execute(
            "UPDATE scout_runs SET finished_at=datetime('now'), status=?, "
            "apify_run_id=?, candidates_seen=?, candidates_new=?, "
            "apify_compute_usd=?, error=? WHERE id=?",
            (status, apify_run_id, candidates_seen, candidates_new, compute_usd, error, run_id),
        )


def _upsert_candidate(handle: str, **fields) -> bool:
    """Insert if new, update otherwise. Returns True if it was newly created."""
    if not handle:
        return False
    handle = handle.lower().lstrip("@")
    with db.connect() as conn:
        existing = conn.execute(
            "SELECT handle FROM candidates WHERE handle=?", (handle,)
        ).fetchone()
        if existing:
            if not fields:
                return False
            cols = ", ".join(f"{k}=?" for k in fields)
            conn.execute(
                f"UPDATE candidates SET {cols} WHERE handle=?",
                (*fields.values(), handle),
            )
            return False
        else:
            cols = ["handle"] + list(fields.keys())
            placeholders = ", ".join("?" * len(cols))
            conn.execute(
                f"INSERT INTO candidates ({', '.join(cols)}) VALUES ({placeholders})",
                (handle, *fields.values()),
            )
            return True


# ============================================================
# SCOUTING — Hashtag
# ============================================================
def scout_hashtag(hashtag: str, *, results_limit: int = 50,
                  session_id: Optional[str] = None,
                  session_label: Optional[str] = None) -> Dict:
    """Scrape posts del hashtag, extrae authors, persiste como candidates 'discovered'.

    No enriquece todavia (no llama profile scraper, eso es paso 2).
    """
    hashtag = hashtag.lstrip("#").lower()
    actor = config.APIFY_ACTORS["instagram_hashtag"]
    run_id = _start_scout_run("hashtag", f"#{hashtag}", actor, session_id, session_label)

    try:
        run_input = {
            "hashtags": [hashtag],
            "resultsLimit": results_limit,
        }
        run = client().actor(actor).call(run_input=run_input)
        apify_run_id = run["id"]
        compute_usd = (run.get("stats", {}).get("computeUnits") or 0) * 0.2  # FREE rate

        seen = 0
        new = 0
        skipped_brand = 0
        for item in client().dataset(run["defaultDatasetId"]).iterate_items():
            seen += 1
            author = item.get("ownerUsername") or (item.get("owner") or {}).get("username")
            if not author:
                continue
            # Pre-filter: descarta marcas/tiendas obvias por keyword en el handle
            handle_lower = author.lower()
            if any(kw in handle_lower for kw in config.IDEAL_CRITERIA["skip_handle_keywords"]):
                skipped_brand += 1
                continue
            was_new = _upsert_candidate(
                handle=author,
                source="hashtag",
                source_detail=f"#{hashtag}",
                scout_run_id=run_id,
            )
            if was_new:
                new += 1
        print(f"  skipped {skipped_brand} probable brand/store handles")

        _finish_scout_run(run_id, status="done", apify_run_id=apify_run_id,
                          candidates_seen=seen, candidates_new=new, compute_usd=compute_usd)
        return {"run_id": run_id, "apify_run_id": apify_run_id, "seen": seen, "new": new,
                "compute_usd": compute_usd}

    except Exception as e:
        _finish_scout_run(run_id, status="error", error=str(e))
        raise


def scout_hashtags_batch(hashtags: List[str], *, results_limit: int = 50) -> Dict:
    """Corre scouting para una lista de hashtags. Retorna agregado."""
    totals = {"runs": 0, "seen": 0, "new": 0, "compute_usd": 0.0, "details": []}
    for h in hashtags:
        try:
            res = scout_hashtag(h, results_limit=results_limit)
            totals["runs"] += 1
            totals["seen"] += res["seen"]
            totals["new"] += res["new"]
            totals["compute_usd"] += res["compute_usd"]
            totals["details"].append({"hashtag": h, **res})
        except Exception as e:
            totals["details"].append({"hashtag": h, "error": str(e)})
    return totals


# ============================================================
# SCOUTING — Por menciones de competidora (mas targeted que hashtag)
# Scrape los posts donde una marca/cuenta es taggeada, extrae los autores.
# ============================================================
def scout_competitor_mentions(competitor_handle: str, *, results_limit: int = 50,
                              session_id: Optional[str] = None,
                              session_label: Optional[str] = None) -> Dict:
    """Scrape posts en el feed 'tagged' del competidor (creadoras que lo etiquetan).
    Esto es 10x mas targeted que hashtag porque solo trae cuentas que YA
    interactuan con marcas similares.
    """
    competitor_handle = competitor_handle.lstrip("@").lower()
    actor = config.APIFY_ACTORS["instagram_scraper"]
    run_id = _start_scout_run("competitor_mention", f"@{competitor_handle}", actor,
                              session_id, session_label)

    try:
        run_input = {
            "directUrls": [f"https://www.instagram.com/{competitor_handle}/tagged/"],
            "resultsType": "posts",
            "resultsLimit": results_limit,
        }
        run = client().actor(actor).call(run_input=run_input)
        apify_run_id = run["id"]
        compute_usd = (run.get("stats", {}).get("computeUnits") or 0) * 0.2

        seen = 0
        new = 0
        skipped_brand = 0
        for item in client().dataset(run["defaultDatasetId"]).iterate_items():
            seen += 1
            author = item.get("ownerUsername") or (item.get("owner") or {}).get("username")
            if not author:
                continue
            handle_lower = author.lower()
            if handle_lower == competitor_handle:
                continue  # ignorar reposts del competidor
            if any(kw in handle_lower for kw in config.IDEAL_CRITERIA["skip_handle_keywords"]):
                skipped_brand += 1
                continue
            was_new = _upsert_candidate(
                handle=author,
                source="competitor_mention",
                source_detail=f"@{competitor_handle}",
                scout_run_id=run_id,
            )
            if was_new:
                new += 1
        print(f"  skipped {skipped_brand} probable brand/store handles")

        _finish_scout_run(run_id, status="done", apify_run_id=apify_run_id,
                          candidates_seen=seen, candidates_new=new, compute_usd=compute_usd)
        return {"run_id": run_id, "apify_run_id": apify_run_id, "seen": seen, "new": new,
                "compute_usd": compute_usd}

    except Exception as e:
        _finish_scout_run(run_id, status="error", error=str(e))
        raise


# ============================================================
# ENRIQUECIMIENTO — Profile + ultimos 12 posts
# ============================================================
def enrich_profile(handle: str, *, posts_limit: int = 12,
                   allowed_account_types: Optional[List[str]] = None,
                   followers_min_override: Optional[int] = None,
                   followers_max_override: Optional[int] = None,
                   allowed_countries: Optional[List[str]] = None,
                   allowed_genders: Optional[List[str]] = None) -> Dict:
    """Llama instagram-profile-scraper para una candidata, calcula ER + Fit Score, guarda."""
    handle = handle.lower().lstrip("@")
    actor = config.APIFY_ACTORS["instagram_profile"]

    run_input = {
        "usernames": [handle],
        "resultsLimit": posts_limit,
        # Activa la sección "About this account" — incluye país autoritativo de IG.
        # Requiere plan de pago (Starter+) que ya tenemos.
        "includeAboutSection": True,
    }
    run = client().actor(actor).call(run_input=run_input)

    profile_data = None
    posts_data: List[dict] = []
    for item in client().dataset(run["defaultDatasetId"]).iterate_items():
        # item es el perfil completo con latestPosts dentro
        profile_data = item
        posts_data = item.get("latestPosts", [])[:posts_limit]
        break

    if not profile_data:
        return {"handle": handle, "error": "no profile data returned"}

    followers = profile_data.get("followersCount") or 0
    following = profile_data.get("followsCount") or 0
    bio = profile_data.get("biography") or ""
    full_name = profile_data.get("fullName") or ""
    is_verified = 1 if profile_data.get("verified") else 0
    is_private = 1 if profile_data.get("private") else 0
    is_business = bool(profile_data.get("isBusinessAccount"))
    profile_pic_url_raw = profile_data.get("profilePicUrl")
    # Descarga local para que no expire
    profile_pic_local = download_profile_pic(handle, profile_pic_url_raw) if profile_pic_url_raw else None
    profile_pic_url = profile_pic_local or profile_pic_url_raw  # fallback al URL si la descarga falla
    external_url = profile_data.get("externalUrl")
    contact_email = profile_data.get("businessEmail") or profile_data.get("publicEmail")
    posts_count = profile_data.get("postsCount") or 0

    # Metricas agregadas de posts
    total_likes = 0
    total_comments = 0
    total_views = 0
    hashtags_seen = set()
    mentions_seen = set()
    for p in posts_data:
        total_likes += p.get("likesCount") or 0
        total_comments += p.get("commentsCount") or 0
        total_views += p.get("videoViewCount") or p.get("videoPlayCount") or 0
        for h in p.get("hashtags", []) or []:
            hashtags_seen.add(h.lower())
        for m in p.get("mentions", []) or []:
            mentions_seen.add(m.lower())

    n = max(1, len(posts_data))
    avg_likes = total_likes / n
    avg_comments = total_comments / n
    avg_views = total_views / n
    er = (avg_likes + avg_comments) / followers if followers else 0

    tier = scoring.tier_from_followers(followers)

    # Fit Score
    fit_score, breakdown = scoring.compute_fit_score(
        engagement_rate=er,
        bio=bio,
        hashtags=list(hashtags_seen),
        mentions=list(mentions_seen),
        followers=followers,
        estimated_city=None,  # podemos extraer del bio mas adelante
        avg_likes=avg_likes,
        avg_comments=avg_comments,
    )

    # Recency: dias desde el ultimo post
    days_since_last_post = None
    last_post_at_iso = None
    if posts_data:
        # Apify devuelve "timestamp" o "takenAtTimestamp" en distintos formatos
        latest_ts = None
        for p in posts_data:
            ts = p.get("timestamp")
            if isinstance(ts, str):
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if latest_ts is None or dt > latest_ts:
                        latest_ts = dt
                except Exception:
                    pass
        if latest_ts:
            last_post_at_iso = latest_ts.isoformat()
            # Comparar como naive UTC
            now = datetime.now(latest_ts.tzinfo) if latest_ts.tzinfo else datetime.now()
            days_since_last_post = (now - latest_ts).days

    # Filtro de candidata ideal
    is_ideal, ideal_reason = scoring.evaluate_ideal_candidate(
        followers=followers,
        following=following,
        engagement_rate=er,
        is_private=bool(is_private),
        is_business=is_business,
        bio=bio,
        full_name=full_name,
        hashtags=list(hashtags_seen),
        mentions=list(mentions_seen),
        posts_count_recent=len(posts_data),
        avg_likes=avg_likes,
        avg_comments=avg_comments,
        handle=handle,
        days_since_last_post=days_since_last_post,
    )

    # Clasificacion de tipo de cuenta + pais + genero
    account_type = scoring.classify_account_type(bio, full_name, handle)
    # País AUTORITATIVO desde IG "About this account" (con fallback a bio detection)
    about = profile_data.get("about") or {}
    country = scoring.country_from_about(about.get("country")) or scoring.detect_country(bio)
    gender = scoring.detect_gender(full_name, handle)

    # Politica nueva: solo se borra HARD JUNK + tipos no permitidos.
    # Las "borderline" se mantienen para revision humana via Tinder UI.
    hard_junk, junk_reason = scoring.is_hard_junk(
        followers=followers,
        is_private=bool(is_private),
        handle=handle,
        full_name=full_name,
        posts_count_recent=len(posts_data),
    )

    # Filtro por tipo de cuenta (segun parametros del scout)
    if not hard_junk and allowed_account_types is not None:
        if account_type not in allowed_account_types:
            hard_junk = True
            junk_reason = f"tipo de cuenta '{account_type}' no permitido por scout"

    # Filtro por pais
    if not hard_junk and allowed_countries:
        if country is None and "UNKNOWN" not in allowed_countries:
            hard_junk = True
            junk_reason = f"país no detectable (allowed: {allowed_countries})"
        elif country and country not in allowed_countries:
            hard_junk = True
            junk_reason = f"país {country} no permitido (allowed: {allowed_countries})"

    # Filtro por género
    if not hard_junk and allowed_genders:
        if gender is None and "unknown" not in allowed_genders:
            hard_junk = True
            junk_reason = f"género no detectable (allowed: {allowed_genders})"
        elif gender and gender not in allowed_genders:
            hard_junk = True
            junk_reason = f"género {gender} no permitido"

    # Overrides de followers (parametros del scout)
    if not hard_junk and followers_min_override is not None and followers < followers_min_override:
        hard_junk = True
        junk_reason = f"followers {followers:,} < min override {followers_min_override:,}"
    if not hard_junk and followers_max_override is not None and followers > followers_max_override:
        hard_junk = True
        junk_reason = f"followers {followers:,} > max override {followers_max_override:,}"

    if hard_junk:
        with db.connect() as conn:
            cur = conn.execute(
                "SELECT lark_record_id FROM candidates WHERE handle=?", (handle,)
            ).fetchone()
            if cur and not cur["lark_record_id"]:
                # Audit trail: mantener fila con status='auto_rejected'.
                conn.execute(
                    "UPDATE candidates SET status='auto_rejected', "
                    "  filter_verdict='auto_rejected', filter_reason=?, "
                    "  followers=?, following=?, engagement_rate=?, tier=?, "
                    "  account_type=?, country=?, gender=?, full_name=?, bio=?, "
                    "  last_enriched_at=? WHERE handle=?",
                    (junk_reason, followers, following, er, tier,
                     account_type, country, gender, full_name, bio,
                     datetime.now().isoformat(timespec="seconds"), handle)
                )
                return {
                    "handle": handle, "followers": followers, "er": er,
                    "tier": tier, "fit_score": fit_score,
                    "is_ideal": False, "reason": junk_reason, "auto_rejected": True,
                    "account_type": account_type, "gender": gender,
                }

    # Veredicto del filtro (solo informativo, no bloquea)
    filter_verdict = "pass" if is_ideal else "borderline"
    filter_reason_text = ideal_reason

    # Persistir todo (incluyendo veredicto)
    _upsert_candidate(
        handle=handle,
        full_name=full_name,
        bio=bio,
        followers=followers,
        following=following,
        posts_count=posts_count,
        is_verified=is_verified,
        is_private=is_private,
        profile_pic_url=profile_pic_url,
        external_url=external_url,
        contact_email=contact_email,
        avg_likes=avg_likes,
        avg_comments=avg_comments,
        avg_views=avg_views,
        engagement_rate=er,
        tier=tier,
        inferred_niches=json.dumps(sorted(hashtags_seen & config.RELEVANT_NICHES)),
        fit_score=fit_score,
        fit_score_breakdown=json.dumps(breakdown),
        fit_score_at=datetime.now().isoformat(timespec="seconds"),
        last_enriched_at=datetime.now().isoformat(timespec="seconds"),
        last_post_at=last_post_at_iso,
        filter_verdict=filter_verdict,
        filter_reason=filter_reason_text,
        account_type=account_type,
        country=country,
        gender=gender,
    )

    # Capturar relatedProfiles (perfiles similares según el algoritmo de IG)
    # Es info que viene gratis en el response y se usa para "Scout from seeds".
    related_profiles = profile_data.get("relatedProfiles") or []
    if related_profiles:
        with db.connect() as conn:
            for rp in related_profiles:
                rp_handle = (rp.get("username") or "").lower().strip()
                if not rp_handle or rp_handle == handle:
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO related_profiles_edges "
                    "(seed_handle, related_handle, related_full_name, "
                    " related_is_verified, related_pic_url, captured_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        handle,
                        rp_handle,
                        rp.get("full_name") or rp.get("fullName"),
                        1 if rp.get("is_verified") or rp.get("isVerified") else 0,
                        rp.get("profile_pic_url") or rp.get("profilePicUrl"),
                        datetime.now().isoformat(timespec="seconds"),
                    ),
                )

    # Si la candidata ya esta en Lark, pushear enriquecimiento de vuelta al CRM
    with db.connect() as conn:
        cur = conn.execute(
            "SELECT lark_record_id FROM candidates WHERE handle=?", (handle,)
        ).fetchone()
        if cur and cur["lark_record_id"]:
            try:
                import lark_sync
                lark_sync.push_enrichment_to_lark(handle)
            except Exception as e:
                print(f"  ⚠ lark push fail for {handle}: {e}")

    # Persist posts
    with db.connect() as conn:
        for p in posts_data:
            url = p.get("url") or f"https://instagram.com/p/{p.get('shortCode', '')}"
            conn.execute(
                "INSERT OR IGNORE INTO candidate_posts "
                "(handle, post_url, shortcode, post_type, posted_at, likes, comments, views, caption, hashtags, mentions) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    handle,
                    url,
                    p.get("shortCode"),
                    p.get("type"),
                    p.get("timestamp"),
                    p.get("likesCount"),
                    p.get("commentsCount"),
                    p.get("videoViewCount") or p.get("videoPlayCount"),
                    (p.get("caption") or "")[:500],
                    json.dumps(p.get("hashtags") or []),
                    json.dumps(p.get("mentions") or []),
                ),
            )

    return {
        "handle": handle,
        "followers": followers,
        "er": er,
        "tier": tier,
        "fit_score": fit_score,
        "is_ideal": is_ideal,
        "reason": ideal_reason,
        "account_type": account_type,
    }


def enrich_pending(limit: int = 8,
                   allowed_account_types: Optional[List[str]] = None,
                   followers_min_override: Optional[int] = None,
                   followers_max_override: Optional[int] = None,
                   allowed_countries: Optional[List[str]] = None,
                   allowed_genders: Optional[List[str]] = None) -> List[Dict]:
    """Enriquece las candidatas con status='discovered' que no tienen ER calculado.
    Procesa hasta `limit` para no quemar creditos.

    Si `allowed_account_types` se pasa, las que no caigan en esos tipos se borran.
    """
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT handle FROM candidates "
            "WHERE status='discovered' AND last_enriched_at IS NULL "
            "ORDER BY discovered_at ASC LIMIT ?",
            (limit,),
        ).fetchall()
    results = []
    for r in rows:
        try:
            results.append(enrich_profile(
                r["handle"],
                allowed_account_types=allowed_account_types,
                followers_min_override=followers_min_override,
                followers_max_override=followers_max_override,
                allowed_countries=allowed_countries,
            ))
        except Exception as e:
            results.append({"handle": r["handle"], "error": str(e)})
    return results


def scout_until_target(
    scout_type: str,  # "hashtag" o "competitor_mention"
    source: str,
    *,
    target_passing: int,
    allowed_account_types: Optional[List[str]] = None,
    allowed_countries: Optional[List[str]] = None,
    allowed_genders: Optional[List[str]] = None,
    followers_min_override: Optional[int] = None,
    followers_max_override: Optional[int] = None,
    max_scrape_attempts: int = 3,
    session_id: Optional[str] = None,
    session_label: Optional[str] = None,
) -> Dict:
    """Scrapea + enriquece hasta tener `target_passing` candidatas aptas (pasan filtros).

    Sobre-scrape conservador (target * 5) en cada attempt. Si despues de N intentos
    no hay suficientes aptas, retorna lo que tenga.
    """
    total_passing = 0
    total_auto_rej = 0
    total_errors = 0
    total_scraped = 0
    total_cost = 0.0
    run_ids = []
    attempts = 0

    while total_passing < target_passing and attempts < max_scrape_attempts:
        attempts += 1
        # Scrapeo agresivo: piso 80, escala 20x por aptas faltantes.
        # IG hashtag scraper retorna mismas top-posts si pides poco — más profundo = más diverso.
        scrape_limit = min(max(80, (target_passing - total_passing) * 20), 200)

        # Scrape — pasar session_id/label si vienen (para agrupar theme scouts)
        if scout_type == "hashtag":
            res = scout_hashtag(source, results_limit=scrape_limit,
                                session_id=session_id, session_label=session_label)
        else:
            res = scout_competitor_mentions(source, results_limit=scrape_limit,
                                            session_id=session_id, session_label=session_label)

        run_id = res["run_id"]
        run_ids.append(run_id)
        total_scraped += res["seen"]
        total_cost += res["compute_usd"]

        # Si no encontró nuevos handles, break (probablemente saturó el hashtag)
        if res["new"] == 0:
            break

        # Enriquecer los handles nuevos de este run hasta target
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT handle FROM candidates "
                "WHERE scout_run_id=? AND last_enriched_at IS NULL "
                "ORDER BY discovered_at ASC",
                (run_id,),
            ).fetchall()

        for r in rows:
            if total_passing >= target_passing:
                break
            try:
                result = enrich_profile(
                    r["handle"],
                    allowed_account_types=allowed_account_types,
                    allowed_countries=allowed_countries,
                    allowed_genders=allowed_genders,
                    followers_min_override=followers_min_override,
                    followers_max_override=followers_max_override,
                )
            except Exception as e:
                print(f"  err {r['handle']}: {e}")
                total_errors += 1
                continue

            if result.get("auto_rejected"):
                total_auto_rej += 1
            elif result.get("error"):
                total_errors += 1
            else:
                # Pasa los filtros HARD (country, type, rango followers, etc).
                # Cuenta como APTA aunque ER esté bajo (borderline) — la usuaria
                # decide en Tinder. ER es subjetivo, no un filtro duro.
                total_passing += 1

    return {
        "run_ids": run_ids,
        "primary_run_id": run_ids[0] if run_ids else None,
        "target": target_passing,
        "passing": total_passing,
        "auto_rejected": total_auto_rej,
        "errors": total_errors,
        "scraped": total_scraped,
        "compute_usd": total_cost,
        "attempts": attempts,
        "reached_target": total_passing >= target_passing,
    }


def scout_theme_until_target(
    theme: str,
    *,
    target_passing: int,
    allowed_account_types: Optional[List[str]] = None,
    allowed_countries: Optional[List[str]] = None,
    allowed_genders: Optional[List[str]] = None,
    followers_min_override: Optional[int] = None,
    followers_max_override: Optional[int] = None,
    progress_callback=None,
) -> Dict:
    """Itera por una lista curada de hashtags del tema hasta acumular `target_passing` aptas.

    El usuario pide N, el sistema insiste con multiples hashtags MX hasta cumplir.
    """
    import uuid
    hashtags = config.HASHTAG_THEMES.get(theme, [])
    if not hashtags:
        return {"error": f"tema '{theme}' no existe", "passing": 0,
                "auto_rejected": 0, "scraped": 0, "compute_usd": 0.0, "run_ids": []}

    # Session ID compartido para que el UI agrupe los sub-runs como UN solo theme scout
    session_id = uuid.uuid4().hex[:12]
    session_label = f"Theme: {theme}"

    total = {
        "passing": 0,
        "auto_rejected": 0,
        "scraped": 0,
        "compute_usd": 0.0,
        "run_ids": [],
        "hashtags_tried": [],
        "target": target_passing,
        "session_id": session_id,
        "session_label": session_label,
    }

    for hashtag in hashtags:
        if total["passing"] >= target_passing:
            break
        remaining = target_passing - total["passing"]
        if progress_callback:
            progress_callback(f"Buscando en #{hashtag} (faltan {remaining})...")

        try:
            res = scout_until_target(
                "hashtag",
                hashtag,
                target_passing=remaining,
                allowed_account_types=allowed_account_types,
                allowed_countries=allowed_countries,
                allowed_genders=allowed_genders,
                followers_min_override=followers_min_override,
                followers_max_override=followers_max_override,
                max_scrape_attempts=1,
                session_id=session_id,
                session_label=session_label,
            )
        except Exception as e:
            print(f"  err in #{hashtag}: {e}")
            continue

        total["passing"] += res["passing"]
        total["auto_rejected"] += res["auto_rejected"]
        total["scraped"] += res["scraped"]
        total["compute_usd"] += res["compute_usd"]
        total["run_ids"].extend(res["run_ids"])
        total["hashtags_tried"].append({"hashtag": hashtag, "passing": res["passing"]})

    total["reached_target"] = total["passing"] >= target_passing
    return total


def lookup_profile(handle: str) -> Dict:
    """Búsqueda directa de un perfil específico. NO aplica filtros (siempre guarda).
    Útil cuando ya tienes a alguien en mente y quieres ver toda su data + recomendación.

    Devuelve el dict completo de la candidata + predicción de collab type.
    """
    handle = handle.lower().lstrip("@").strip()
    if not handle:
        return {"error": "handle vacío"}

    # Asegurar que existe la fila base (sin filtros)
    with db.connect() as conn:
        existing = conn.execute(
            "SELECT handle FROM candidates WHERE handle=?", (handle,)
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO candidates (handle, source, source_detail, status) "
                "VALUES (?, 'manual_lookup', 'direct', 'discovered')",
                (handle,)
            )

    # Force re-enrichment: limpiar last_enriched_at para que se re-llame Apify
    with db.connect() as conn:
        conn.execute("UPDATE candidates SET last_enriched_at=NULL WHERE handle=?", (handle,))

    # Enriquece SIN filtros (allowed_* en None) → siempre guarda full data
    try:
        result = enrich_profile(handle)
    except Exception as e:
        return {"error": str(e), "handle": handle}

    # Cargar fila completa para predicción
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM candidates WHERE handle=?", (handle,)
        ).fetchone()

    if not row:
        return {"error": "no se pudo guardar", "handle": handle}

    cand = dict(row)

    # Predicción de collab type
    prediction = scoring.predict_collab_type(
        followers=cand.get("followers"),
        engagement_rate=cand.get("engagement_rate"),
        tier=cand.get("tier"),
        account_type=cand.get("account_type"),
        country=cand.get("country"),
        gender=cand.get("gender"),
        avg_likes=cand.get("avg_likes"),
        avg_comments=cand.get("avg_comments"),
        num_posts_in_collab=1,
    )

    return {"candidate": cand, "prediction": prediction}


def enrich_lark_imports(limit: int = 20) -> List[Dict]:
    """Enriquece candidatas importadas de Lark que no tienen ER/profile pic.
    Las imports tienen lark_record_id; nunca se borran aunque no pasen filtro.
    """
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT handle FROM candidates "
            "WHERE lark_record_id IS NOT NULL "
            "  AND last_enriched_at IS NULL "
            "  AND handle NOT LIKE '% %' "  # skip handles con espacios (no son IG reales)
            "ORDER BY followers DESC LIMIT ?",
            (limit,),
        ).fetchall()
    results = []
    for r in rows:
        try:
            results.append(enrich_profile(r["handle"]))
        except Exception as e:
            results.append({"handle": r["handle"], "error": str(e)})
    return results


# ============================================================
# TRACKING — snapshot diario de un post de collab
# ============================================================
def snapshot_collab_post(collab_id: int, post_url: str) -> Dict:
    """Saca metricas actuales del post, guarda snapshot, recalcula EMV de la collab.
    Usa apify/instagram-scraper (general) que acepta directUrls sin necesidad de
    username (a diferencia de instagram-post-scraper que cambió su API)."""
    actor = config.APIFY_ACTORS["instagram_scraper"]
    run = client().actor(actor).call(run_input={
        "directUrls": [post_url],
        "resultsType": "posts",
        "resultsLimit": 1,
        "addParentData": False,
    })

    metrics = None
    for item in client().dataset(run["defaultDatasetId"]).iterate_items():
        metrics = item
        break

    if not metrics:
        return {"error": "Apify devolvió 0 items para este post URL"}

    likes = metrics.get("likesCount") or 0
    comments = metrics.get("commentsCount") or 0
    views = (metrics.get("videoViewCount") or metrics.get("videoPlayCount")
              or metrics.get("viewCount") or 0)

    with db.connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO collab_post_snapshots "
            "(collab_id, post_url, likes, comments, views) VALUES (?, ?, ?, ?, ?)",
            (collab_id, post_url, likes, comments, views),
        )

    # Recalc collab totals (suma del snapshot MAS RECIENTE de cada post)
    _recalc_collab_emv(collab_id)
    return {"likes": likes, "comments": comments, "views": views}


def _recalc_collab_emv(collab_id: int) -> None:
    """Recalcula totales y EMV de una collab basado en sus snapshots mas recientes."""
    with db.connect() as conn:
        # Por cada post_url, agarrar la fila mas reciente
        rows = conn.execute("""
            SELECT post_url, likes, comments, saves, shares, views
            FROM collab_post_snapshots
            WHERE collab_id=? AND captured_at = (
                SELECT MAX(captured_at) FROM collab_post_snapshots
                WHERE collab_id=? AND post_url=collab_post_snapshots.post_url
            )
        """, (collab_id, collab_id)).fetchall()

        tot_likes = sum(r["likes"] or 0 for r in rows)
        tot_comments = sum(r["comments"] or 0 for r in rows)
        tot_saves = sum(r["saves"] or 0 for r in rows)
        tot_shares = sum(r["shares"] or 0 for r in rows)
        tot_views = sum(r["views"] or 0 for r in rows)
        num_posts = len(rows)

        collab = conn.execute(
            "SELECT c.*, cd.tier FROM collabs c "
            "LEFT JOIN candidates cd ON cd.handle=c.handle WHERE c.id=?",
            (collab_id,),
        ).fetchone()
        if not collab:
            return

        tier = collab["tier"] or "nano"
        emv = scoring.compute_emv(
            tier=tier,
            num_posts=num_posts,
            likes=tot_likes, comments=tot_comments,
            saves=tot_saves, shares=tot_shares, views=tot_views,
            attributed_followers=collab["attributed_followers"] or 0,
        )
        cash_ratio, total_ratio = scoring.compute_ratios(
            emv,
            cash_fee=collab["cash_fee"],
            usage_rights_fee=collab["usage_rights_fee"],
            agency_fee=collab["agency_fee"],
            shipping_cost=collab["shipping_cost"],
            cogs_pieces=collab["cogs_pieces"],
        )

        conn.execute("""
            UPDATE collabs SET
                total_likes=?, total_comments=?, total_saves=?, total_shares=?, total_views=?,
                emv_mxn=?, emv_cash_ratio=?, emv_total_ratio=?,
                last_recalc_at=datetime('now')
            WHERE id=?
        """, (tot_likes, tot_comments, tot_saves, tot_shares, tot_views,
              emv, cash_ratio, total_ratio, collab_id))


# ============================================================
# Scout from seeds — discovery por red usando relatedProfiles de IG
# ============================================================
def get_seed_handles() -> List[str]:
    """Devuelve handles de candidatas confirmadas como seeds. Una seed = candidata
    que ya pasó tu juicio (approved/contacted/active/negotiating)."""
    with db.connect() as conn:
        rows = conn.execute("""
            SELECT handle FROM candidates
            WHERE status IN ('approved', 'contacted', 'active', 'negotiating')
              AND followers >= 5000
            ORDER BY followers DESC
        """).fetchall()
    return [r["handle"] for r in rows]


def refresh_seed_related_profiles(
    *, max_seeds: Optional[int] = None,
    progress_callback=None,
) -> Dict:
    """Re-enrich cada seed para capturar relatedProfiles fresco.
    Solo re-enrich seeds que tienen 0 edges o son antiguas (>30 días)."""
    seeds = get_seed_handles()
    if max_seeds:
        seeds = seeds[:max_seeds]

    refreshed = 0
    skipped = 0
    errors = 0

    for i, seed in enumerate(seeds, 1):
        # Check si ya tenemos relatedProfiles para esta seed y es reciente
        with db.connect() as conn:
            cur = conn.execute("""
                SELECT COUNT(*) AS n, MAX(captured_at) AS latest
                FROM related_profiles_edges WHERE seed_handle=?
            """, (seed,)).fetchone()

        if cur and cur["n"] > 0 and cur["latest"]:
            try:
                latest_dt = datetime.fromisoformat(cur["latest"])
                age_days = (datetime.now() - latest_dt).days
                if age_days < 30:
                    skipped += 1
                    if progress_callback:
                        progress_callback(f"[{i}/{len(seeds)}] @{seed} — skip (fresh, {age_days}d)")
                    continue
            except Exception:
                pass

        if progress_callback:
            progress_callback(f"[{i}/{len(seeds)}] Re-enriching @{seed} para relatedProfiles…")
        try:
            enrich_profile(seed)
            refreshed += 1
        except Exception as e:
            errors += 1
            print(f"  ⚠ enrich fail for @{seed}: {e}")

    return {"seeds_total": len(seeds), "refreshed": refreshed,
            "skipped": skipped, "errors": errors}


def scout_from_seeds(
    *,
    target_passing: int = 8,
    min_overlap: int = 1,
    max_candidates_to_enrich: int = 30,
    allowed_account_types: Optional[List[str]] = None,
    allowed_countries: Optional[List[str]] = None,
    allowed_genders: Optional[List[str]] = None,
    progress_callback=None,
) -> Dict:
    """Discovery por red: usa relatedProfiles de tus seeds (aptas confirmadas)
    para encontrar candidates similares. El ranking es por overlap — handles
    que aparecen en relatedProfiles de MUCHAS seeds tienen score alto.

    Flujo:
      1. Refresh relatedProfiles de las seeds (re-enrich solo si stale).
      2. Agrega todos los related handles, dedup por count.
      3. Filtra los que YA están en candidates (no re-procesar).
      4. Enriquece top N por overlap, aplicando filtros normales.
    """
    import uuid
    session_id = uuid.uuid4().hex[:12]
    session_label = "Scout from seeds (network discovery)"

    if progress_callback:
        progress_callback("Paso 1/3: Refrescando relatedProfiles de tus seeds…")
    refresh_result = refresh_seed_related_profiles(progress_callback=progress_callback)

    # Top related handles por overlap (cuántas seeds los recomiendan)
    if progress_callback:
        progress_callback("Paso 2/3: Rankeando candidates por overlap…")
    with db.connect() as conn:
        rows = conn.execute("""
            SELECT rpe.related_handle, COUNT(DISTINCT rpe.seed_handle) AS overlap,
                   GROUP_CONCAT(rpe.seed_handle, ', ') AS seeds_recommending
            FROM related_profiles_edges rpe
            WHERE rpe.related_handle NOT IN (SELECT handle FROM candidates)
              AND rpe.related_handle != ''
            GROUP BY rpe.related_handle
            HAVING overlap >= ?
            ORDER BY overlap DESC, rpe.related_handle ASC
            LIMIT ?
        """, (min_overlap, max_candidates_to_enrich)).fetchall()

    new_candidates = [dict(r) for r in rows]
    if not new_candidates:
        return {
            "refresh_result": refresh_result,
            "ranked_candidates": 0,
            "enriched": 0, "passing": 0, "auto_rejected": 0,
            "compute_usd": 0.0, "target": target_passing,
            "session_id": session_id, "session_label": session_label,
            "message": "No hay candidates nuevos en relatedProfiles. "
                       "Aprueba más seeds en Felynder para que la red crezca.",
        }

    # Step 3: enriquecer los top candidates con filtros normales
    if progress_callback:
        progress_callback(f"Paso 3/3: Enriqueciendo top {len(new_candidates)} candidates…")

    passing = 0
    auto_rejected = 0
    enriched = 0

    # Crear scout_run para auditoria
    with db.connect() as conn:
        cur = conn.execute("""
            INSERT INTO scout_runs
              (started_at, source, source_detail, apify_actor,
               session_id, session_label, status)
            VALUES (datetime('now'), 'seeds_relatedProfiles',
                    'network_discovery', ?, ?, ?, 'running')
        """, (config.APIFY_ACTORS["instagram_profile"], session_id, session_label))
        scout_run_id = cur.lastrowid

    for i, c in enumerate(new_candidates, 1):
        handle = c["related_handle"]
        if progress_callback:
            progress_callback(f"  [{i}/{len(new_candidates)}] @{handle} (overlap={c['overlap']})")
        try:
            # Pre-insertar para que el scout_run_id quede ligado
            with db.connect() as conn:
                conn.execute("""
                    INSERT OR IGNORE INTO candidates
                    (handle, source, source_detail, scout_run_id, status)
                    VALUES (?, 'seeds_relatedProfiles', ?, ?, 'discovered')
                """, (handle, f"overlap={c['overlap']} from seeds: {c['seeds_recommending'][:80]}",
                      scout_run_id))

            res = enrich_profile(
                handle,
                allowed_account_types=allowed_account_types,
                allowed_countries=allowed_countries,
                allowed_genders=allowed_genders,
            )
            enriched += 1
            if res.get("auto_rejected"):
                auto_rejected += 1
            elif not res.get("error"):
                passing += 1
                if passing >= target_passing:
                    break
        except Exception as e:
            print(f"  ⚠ enrich fail for @{handle}: {e}")

    with db.connect() as conn:
        conn.execute("""
            UPDATE scout_runs SET finished_at=datetime('now'),
                   candidates_seen=?, candidates_new=?, status='done'
            WHERE id=?
        """, (len(new_candidates), enriched, scout_run_id))

    return {
        "refresh_result": refresh_result,
        "ranked_candidates": len(new_candidates),
        "enriched": enriched,
        "passing": passing,
        "auto_rejected": auto_rejected,
        "target": target_passing,
        "session_id": session_id,
        "session_label": session_label,
    }


# ============================================================
# Story tracking — scrape stories de collabs activas
# ============================================================
import urllib.request

STORIES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "stories")


def _download_story_media(handle: str, story_id: str, media_url: str,
                          media_type: str) -> Optional[str]:
    """Descarga story media (image/video) a data/stories/<handle>/<story_id>.<ext>.
    Devuelve path local o None si falla."""
    if not media_url:
        return None
    ext = "mp4" if media_type == "video" else "jpg"
    handle_dir = os.path.join(STORIES_DIR, handle)
    os.makedirs(handle_dir, exist_ok=True)
    local_path = os.path.join(handle_dir, f"{story_id}.{ext}")
    if os.path.exists(local_path):
        return local_path
    try:
        req = urllib.request.Request(
            media_url, headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            with open(local_path, "wb") as f:
                f.write(resp.read())
        return local_path
    except Exception as e:
        print(f"  ⚠ story media download fail for @{handle}/{story_id}: {e}")
        return None


def _detect_felyfit_mention(mentions: List[str], hashtags: List[str],
                            caption_text: Optional[str]) -> Tuple[int, str]:
    """Detecta si la story menciona a FelyFit. Devuelve (flag, reason)."""
    mentions_lower = [m.lower().lstrip("@") for m in (mentions or [])]
    hashtags_lower = [h.lower().lstrip("#") for h in (hashtags or [])]
    caption = (caption_text or "").lower()

    for h in config.FELYFIT_HANDLES:
        if h.lower() in mentions_lower:
            return 1, f"menciona @{h}"
    for t in config.FELYFIT_HASHTAGS:
        if t.lower() in hashtags_lower:
            return 1, f"hashtag #{t}"
    for kw in config.FELYFIT_KEYWORDS_IN_CAPTION:
        if kw.lower() in caption:
            return 1, f"caption contiene '{kw}'"
    return 0, ""


def scrape_stories_for_handles(handles: List[str],
                                extract_caption_text: bool = True) -> Dict:
    """Llama el actor de stories para los handles. Guarda cada story en DB
    y descarga media local. Devuelve summary."""
    if not handles:
        return {"scraped": 0, "new_stories": 0, "felyfit_mentions": 0, "compute_usd": 0.0}

    actor = config.APIFY_ACTORS["instagram_stories"]
    run_input = {
        "usernames": handles,
        "extractCaptionText": extract_caption_text,
    }
    run = client().actor(actor).call(run_input=run_input)
    run_id = run.get("id")
    compute_usd = (run.get("usage") or {}).get("ACTOR_COMPUTE_UNITS_USD", 0.0)

    new_stories = 0
    felyfit_mentions = 0
    total = 0
    for item in client().dataset(run["defaultDatasetId"]).iterate_items():
        total += 1
        # Schema del actor varía — extraemos defensivamente
        owner_handle = (item.get("user_username") or item.get("ownerUsername")
                        or item.get("username") or "").lower().lstrip("@")
        story_id = str(item.get("story_id") or item.get("id") or item.get("pk") or "")
        if not owner_handle or not story_id:
            continue

        # Posted at
        posted_at = item.get("taken_at") or item.get("timestamp") or item.get("taken_at_timestamp")
        if isinstance(posted_at, (int, float)):
            posted_at_iso = datetime.fromtimestamp(posted_at).isoformat(timespec="seconds")
        elif isinstance(posted_at, str):
            posted_at_iso = posted_at
        else:
            posted_at_iso = datetime.now().isoformat(timespec="seconds")

        # Media
        is_video = bool(item.get("is_video") or item.get("video_url"))
        media_type = "video" if is_video else "image"
        media_url = (item.get("video_url") or item.get("display_url")
                     or item.get("image_url") or item.get("media_url"))
        video_duration_s = item.get("video_duration") or item.get("duration")

        # Contenido
        caption_text = (item.get("caption_text") or item.get("captionText")
                         or item.get("accessibility_caption"))
        # reel_mentions = list of {user: {username}}; normalizamos a list[str]
        reel_mentions = item.get("reel_mentions") or item.get("mentions") or []
        mentions: List[str] = []
        for m in reel_mentions:
            if isinstance(m, dict):
                u = (m.get("user") or {}).get("username") or m.get("username")
                if u: mentions.append(u)
            elif isinstance(m, str):
                mentions.append(m)
        hashtags = item.get("hashtags") or []
        link_url = item.get("link_url") or item.get("swipeup_url")
        sticker_types_raw = item.get("story_feed_media") or item.get("stickers") or []
        sticker_types = [s.get("type") if isinstance(s, dict) else str(s)
                          for s in sticker_types_raw if s]

        # Detección FelyFit
        is_fm, fm_reason = _detect_felyfit_mention(mentions, hashtags, caption_text)
        if is_fm:
            felyfit_mentions += 1

        # Download media local
        local_path = _download_story_media(owner_handle, story_id, media_url, media_type)

        # Views
        views = item.get("view_count") or item.get("viewers_count")

        with db.connect() as conn:
            cur = conn.execute(
                "SELECT id FROM story_snapshots WHERE handle=? AND story_id=?",
                (owner_handle, story_id),
            ).fetchone()
            if cur:
                continue  # dedup
            conn.execute(
                """INSERT INTO story_snapshots
                   (handle, story_id, posted_at, expires_at, media_type, media_url,
                    local_media_path, video_duration_s, caption_text, mentions,
                    hashtags, link_url, sticker_types, is_felyfit_mention,
                    felyfit_detection_notes, views_count, apify_run_id)
                   VALUES (?,?,?,datetime(?,'+24 hours'),?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (owner_handle, story_id, posted_at_iso, posted_at_iso,
                 media_type, media_url, local_path, video_duration_s,
                 caption_text, json.dumps(mentions), json.dumps(hashtags),
                 link_url, json.dumps(sticker_types),
                 is_fm, fm_reason, views, run_id),
            )
            new_stories += 1

    return {
        "handles_scraped": len(handles),
        "total_stories_returned": total,
        "new_stories": new_stories,
        "felyfit_mentions": felyfit_mentions,
        "compute_usd": compute_usd,
        "apify_run_id": run_id,
    }


def scrape_stories_for_active_collabs() -> Dict:
    """Helper para cron: scrape stories de todas las collabs activas."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT handle FROM candidates WHERE status IN "
            "('active', 'contacted', 'negotiating') AND followers >= 5000"
        ).fetchall()
    handles = [r["handle"] for r in rows]
    return scrape_stories_for_handles(handles)
