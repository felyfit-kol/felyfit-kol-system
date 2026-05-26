"""Sync selectivo a Lark. SOLO escribe cuando hay transicion clave de estado.

Triggers:
- Candidate aprobada (discovered -> approved): crea fila en Creadoras IG con status 'Prospecting'
- Status change posterior: actualiza fila existente
- Collab cerrada: actualiza Ultima colaboracion + EMV Ratio ultimo
"""

import os
from datetime import datetime
from typing import Dict, Optional

import httpx
from dotenv import load_dotenv

import config
import db

load_dotenv()

APP_ID = os.environ["LARK_APP_ID"]
APP_SECRET = os.environ["LARK_APP_SECRET"]
BASE_TOKEN = os.environ["LARK_BASE_APP_TOKEN"]
DOMAIN = os.environ["LARK_DOMAIN"]
TABLE_ID = config.LARK_CREADORAS_TABLE_ID

_token_cache = {"token": None, "expires_at": 0}


def _get_token() -> str:
    """Cachea tenant_access_token. Lark default TTL ~2h."""
    now = datetime.now().timestamp()
    if _token_cache["token"] and _token_cache["expires_at"] > now + 60:
        return _token_cache["token"]
    r = httpx.post(
        f"{DOMAIN}/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": APP_ID, "app_secret": APP_SECRET},
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    _token_cache["token"] = data["tenant_access_token"]
    _token_cache["expires_at"] = now + data.get("expire", 7000)
    return _token_cache["token"]


def _api(method: str, path: str, json_body: Optional[dict] = None) -> dict:
    r = httpx.request(
        method,
        f"{DOMAIN}/open-apis{path}",
        headers={"Authorization": f"Bearer {_get_token()}",
                 "Content-Type": "application/json"},
        json=json_body,
        timeout=15,
    )
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"Lark API error {data.get('code')}: {data.get('msg')} (path={path})")
    return data


def _candidate_to_lark_fields(cand: dict, include_status: bool = True) -> dict:
    """Mapea fila de candidates -> campos de Lark Creadoras IG."""
    fields = {
        "Username": cand["handle"],
        "Plataforma Principal": "Instagram",
    }
    if include_status:
        fields["Status actual"] = config.LARK_STATUS_ON_APPROVE
    if cand.get("full_name"):
        fields["Nombre Real"] = cand["full_name"]
    if cand.get("followers") is not None:
        fields["Followers (K)"] = round(cand["followers"] / 1000, 1)
    if cand.get("engagement_rate") is not None:
        fields["ER"] = round(cand["engagement_rate"], 4)
    if cand.get("contact_email"):
        fields["Contact"] = cand["contact_email"]
    if cand.get("notes"):
        fields["Notas"] = cand["notes"]
    if cand.get("tier"):
        fields["Tier"] = cand["tier"]
    if cand.get("fit_score") is not None:
        fields["Fit Score"] = round(float(cand["fit_score"]), 1)
    if cand.get("account_type"):
        fields["Account Type"] = cand["account_type"]
    if cand.get("country"):
        fields["Country"] = cand["country"]
    if cand.get("bio"):
        fields["Bio"] = cand["bio"][:500]  # Lark text limit
    return fields


def push_enrichment_to_lark(handle: str) -> Dict:
    """Update enriched data on existing Lark row. NO toca status — solo metricas."""
    with db.connect() as conn:
        cand = conn.execute("SELECT * FROM candidates WHERE handle=?", (handle,)).fetchone()
        if not cand or not cand["lark_record_id"]:
            return {"handle": handle, "skipped": "not synced to Lark"}
        fields = _candidate_to_lark_fields(dict(cand), include_status=False)
        # No queremos pisar status existente — quitar Username/Plataforma que ya estan
        fields.pop("Username", None)
        fields.pop("Plataforma Principal", None)
        _api("PUT",
             f"/bitable/v1/apps/{BASE_TOKEN}/tables/{TABLE_ID}/records/{cand['lark_record_id']}",
             {"fields": fields})
        return {"handle": handle, "updated": list(fields.keys())}


# ============================================================
# Schema setup — crea campos faltantes en Lark Creadoras IG
# ============================================================
def create_missing_fields() -> Dict:
    """Crea en Lark los campos que necesitamos: Tier, Fit Score, Account Type, Country, Bio.
    Idempotente — si ya existen, no hace nada."""
    # Listar campos actuales
    existing = _api("GET", f"/bitable/v1/apps/{BASE_TOKEN}/tables/{TABLE_ID}/fields?page_size=100")
    have = {f["field_name"] for f in existing["data"]["items"]}

    to_create = []

    if "Tier" not in have:
        to_create.append({
            "field_name": "Tier",
            "type": 3,
            "property": {"options": [
                {"name": "nano"}, {"name": "micro"}, {"name": "mid"},
                {"name": "macro"}, {"name": "mega"},
            ]},
        })
    if "Fit Score" not in have:
        to_create.append({
            "field_name": "Fit Score",
            "type": 2,
            "property": {"formatter": "0.0"},
        })
    if "Account Type" not in have:
        to_create.append({
            "field_name": "Account Type",
            "type": 3,
            "property": {"options": [
                {"name": "individual"}, {"name": "studio"}, {"name": "brand"},
                {"name": "nonprofit"}, {"name": "collective"}, {"name": "unknown"},
            ]},
        })
    if "Country" not in have:
        to_create.append({
            "field_name": "Country",
            "type": 3,
            "property": {"options": [
                {"name": "MX"}, {"name": "US"}, {"name": "AR"}, {"name": "CO"},
                {"name": "ES"}, {"name": "PE"}, {"name": "CL"}, {"name": "BR"},
            ]},
        })
    if "Bio" not in have:
        to_create.append({"field_name": "Bio", "type": 1})

    created = []
    for field_spec in to_create:
        try:
            _api("POST", f"/bitable/v1/apps/{BASE_TOKEN}/tables/{TABLE_ID}/fields", field_spec)
            created.append(field_spec["field_name"])
        except Exception as e:
            print(f"  ⚠ field {field_spec['field_name']} fail: {e}")
    return {"already_existed": list(have & {"Tier", "Fit Score", "Account Type", "Country", "Bio"}),
            "created": created}


def push_candidate_to_lark(handle: str) -> Dict:
    """Crea fila en Creadoras IG y guarda lark_record_id en local."""
    handle = handle.lower().lstrip("@")
    with db.connect() as conn:
        cand = conn.execute("SELECT * FROM candidates WHERE handle=?", (handle,)).fetchone()
        if not cand:
            raise ValueError(f"candidate {handle} not found in local DB")
        if cand["lark_record_id"]:
            return {"handle": handle, "already_synced": True, "record_id": cand["lark_record_id"]}

        fields = _candidate_to_lark_fields(dict(cand))
        result = _api(
            "POST",
            f"/bitable/v1/apps/{BASE_TOKEN}/tables/{TABLE_ID}/records",
            {"fields": fields},
        )
        record_id = result["data"]["record"]["record_id"]

        conn.execute(
            "UPDATE candidates SET lark_record_id=?, lark_synced_at=datetime('now') "
            "WHERE handle=?",
            (record_id, handle),
        )

    return {"handle": handle, "record_id": record_id, "fields": fields}


def update_candidate_status_in_lark(handle: str, new_status: str,
                                    extra_fields: Optional[dict] = None) -> Dict:
    """Actualiza Status actual (y opcionalmente otros campos) en Lark."""
    with db.connect() as conn:
        cand = conn.execute(
            "SELECT lark_record_id FROM candidates WHERE handle=?", (handle,),
        ).fetchone()
    if not cand or not cand["lark_record_id"]:
        return {"handle": handle, "error": "not synced to Lark yet"}

    fields = {"Status actual": new_status}
    if extra_fields:
        fields.update(extra_fields)

    _api(
        "PUT",
        f"/bitable/v1/apps/{BASE_TOKEN}/tables/{TABLE_ID}/records/{cand['lark_record_id']}",
        {"fields": fields},
    )
    return {"handle": handle, "updated": fields}


def push_collab_close_to_lark(collab_id: int) -> Dict:
    """Cuando una collab se cierra, actualiza la fila de la creadora con:
    - Ultima colaboracion (fecha launch)
    - Status actual = 'Posted'
    """
    with db.connect() as conn:
        collab = conn.execute(
            "SELECT c.*, cd.lark_record_id FROM collabs c "
            "LEFT JOIN candidates cd ON cd.handle=c.handle WHERE c.id=?",
            (collab_id,),
        ).fetchone()
    if not collab or not collab["lark_record_id"]:
        return {"collab_id": collab_id, "error": "candidate not synced"}

    fields = {
        "Status actual": "Posted",
    }
    if collab["launch_date"]:
        # Lark espera milisegundos desde epoch
        dt = datetime.fromisoformat(collab["launch_date"])
        fields["Última colaboración"] = int(dt.timestamp() * 1000)

    _api(
        "PUT",
        f"/bitable/v1/apps/{BASE_TOKEN}/tables/{TABLE_ID}/records/{collab['lark_record_id']}",
        {"fields": fields},
    )

    with db.connect() as conn:
        conn.execute("UPDATE collabs SET lark_synced_at=datetime('now') WHERE id=?", (collab_id,))

    return {"collab_id": collab_id, "synced": fields}


def import_existing_creadoras_from_lark() -> Dict:
    """Trae las 133 fichas existentes de Lark al local. Las marca con status apropiado."""
    page_token = None
    pulled = 0
    new_in_local = 0

    while True:
        params = "?page_size=100"
        if page_token:
            params += f"&page_token={page_token}"
        result = _api("GET", f"/bitable/v1/apps/{BASE_TOKEN}/tables/{TABLE_ID}/records{params}")
        items = result["data"].get("items", [])

        for rec in items:
            fields = rec["fields"]
            handle = (fields.get("Username") or "").strip().lower().lstrip("@")
            if not handle:
                continue

            def _num(v):
                if v is None or v == "":
                    return None
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None

            followers_k = _num(fields.get("Followers (K)"))
            er_val = _num(fields.get("ER"))

            payload = {
                "full_name": (fields.get("Nombre Real") or "").strip() or None,
                "followers": int(followers_k * 1000) if followers_k else None,
                "engagement_rate": er_val,
                "contact_email": (fields.get("Contact") or "").strip() or None,
                "estimated_city": fields.get("Ciudad"),
                "source": "lark_import",
                "source_detail": "initial_seed",
                "status": _map_lark_status_to_local(fields.get("Status actual")),
                "lark_record_id": rec["record_id"],
                "lark_synced_at": datetime.now().isoformat(timespec="seconds"),
            }
            # Quita los None para no pisar
            payload = {k: v for k, v in payload.items() if v is not None}

            with db.connect() as conn:
                existing = conn.execute(
                    "SELECT handle FROM candidates WHERE handle=?", (handle,),
                ).fetchone()
                if existing:
                    cols = ", ".join(f"{k}=?" for k in payload)
                    conn.execute(
                        f"UPDATE candidates SET {cols} WHERE handle=?",
                        (*payload.values(), handle),
                    )
                else:
                    cols = ["handle"] + list(payload.keys())
                    placeholders = ", ".join("?" * len(cols))
                    conn.execute(
                        f"INSERT INTO candidates ({', '.join(cols)}) VALUES ({placeholders})",
                        (handle, *payload.values()),
                    )
                    new_in_local += 1

            pulled += 1

        page_token = result["data"].get("page_token")
        if not page_token or not result["data"].get("has_more"):
            break

    return {"pulled": pulled, "new_in_local": new_in_local}


def _map_lark_status_to_local(lark_status: Optional[str]) -> str:
    """Mapeo: Status actual en Lark -> status interno."""
    if not lark_status:
        return "discovered"
    m = {
        "Prospecting": "approved",
        "Outreach Sent": "contacted",
        "Replied": "responded",
        "Negotiating": "negotiating",
        "PR Approved": "negotiating",
        "Awaiting Address": "active",
        "Delivered": "active",
        "Posted": "active",
        "Unaviable": "declined",
        "Unavailable": "declined",
    }
    return m.get(lark_status, "discovered")
