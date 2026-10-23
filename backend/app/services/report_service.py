"""Firestore-backed report persistence, audit history and analytics.

All privileged mutations validate allowed status transitions on the server and
write an immutable reportHistory audit record. Reads enforce ownership so a
user can never retrieve another user's private reports.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from fastapi import HTTPException, status

from .. import firebase_client
from ..schemas import ALLOWED_TRANSITIONS, ReportCreate
from ..services import email_service, storage_service

REPORTS = "reports"
HISTORY = "reportHistory"
TEAMS = "maintenanceTeams"
NOTIFS = "notificationLogs"


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _db():
    return firebase_client.db()


# ---- Serialization ----

def _geo(loc: Any) -> Optional[dict]:
    if not loc:
        return None
    if isinstance(loc, dict):
        return {"latitude": loc.get("latitude"), "longitude": loc.get("longitude")}
    return {"latitude": getattr(loc, "latitude", None), "longitude": getattr(loc, "longitude", None)}


def _to_read(doc_id: str, d: dict, include_media: bool = True) -> dict:
    loc = _geo(d.get("location"))
    out = {
        "id": doc_id,
        "reporter_uid": d.get("reporter_uid", ""),
        "media_type": d.get("media_type", "image"),
        "pothole_count": d.get("pothole_count", 0),
        "max_confidence": d.get("max_confidence"),
        "status": d.get("status", "submitted"),
        "priority": d.get("priority"),
        "location": loc,
        "address": d.get("address"),
        "description": d.get("description"),
        "category": d.get("category"),
        "assigned_team_id": d.get("assigned_team_id"),
        "assigned_team_name": d.get("assigned_team_name"),
        "created_at": d.get("created_at"),
        "updated_at": d.get("updated_at"),
    }
    if include_media:
        out["original_url"] = storage_service.signed_url(d.get("original_object"))
        out["annotated_url"] = storage_service.signed_url(d.get("annotated_object"))
        out["repair_evidence_url"] = storage_service.signed_url(d.get("repair_evidence_object"))
    return out


# ---- History / audit ----

def _add_history(report_id: str, event: str, actor_uid: str,
                 prev: Any = None, new: Any = None, reason: Optional[str] = None) -> None:
    _db().collection(HISTORY).add({
        "report_id": report_id,
        "event": event,
        "previous": prev,
        "new": new,
        "actor_uid": actor_uid,
        "reason": reason,
        "created_at": _now_iso(),
    })


def get_history(report_id: str) -> list[dict]:
    # Filter by equality only, then sort in Python. This avoids needing a
    # composite (report_id, created_at) Firestore index, which a fresh database
    # does not have provisioned.
    docs = (
        _db().collection(HISTORY)
        .where("report_id", "==", report_id)
        .stream()
    )
    items = [{"id": d.id, **d.to_dict()} for d in docs]
    items.sort(key=lambda x: x.get("created_at") or "")
    return items


# ---- Validation ----

def _validate_transition(current: str, target: str) -> None:
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Invalid status transition: '{current}' -> '{target}'.",
        )


def _get_or_404(report_id: str) -> dict:
    snap = _db().collection(REPORTS).document(report_id).get()
    if not snap.exists:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Report not found.")
    data = snap.to_dict() or {}
    data["id"] = snap.id
    return data


# ---- Create ----

def create_report(payload: ReportCreate, user_uid: str, user_email: Optional[str]) -> str:
    ref = _db().collection(REPORTS).document()
    now = _now_iso()
    doc = {
        "reporter_uid": user_uid,
        "reporter_email": user_email,
        "media_type": payload.media_type,
        "pothole_count": payload.pothole_count,
        "max_confidence": payload.max_confidence,
        "detections": [d.model_dump() for d in payload.detections],
        "location": {
            "latitude": payload.location.latitude,
            "longitude": payload.location.longitude,
        },
        "address": payload.address,
        "description": payload.description,
        "category": payload.category,
        "original_object": payload.original_object,
        "annotated_object": payload.annotated_object,
        "status": "submitted",
        "priority": None,
        "assigned_team_id": None,
        "assigned_team_name": None,
        "verified_by": None,
        "verified_at": None,
        "completed_at": None,
        "repair_evidence_object": None,
        "created_at": now,
        "updated_at": now,
    }
    ref.set(doc)
    _add_history(ref.id, "submitted", user_uid, new="submitted")
    email_service.notify_status_change(
        "submitted", ref.id, user_email,
        payload.address or "coords stored",
        on_result=lambda ok: _log_notification(ref.id, "submitted", user_email, ok),
    )
    return ref.id


def _log_notification(report_id: str, event: str, to: Optional[str], delivered: bool) -> None:
    try:
        _db().collection(NOTIFS).add({
            "report_id": report_id,
            "event": event,
            "recipient": to,
            "delivered": delivered,
            "created_at": _now_iso(),
        })
    except Exception:
        pass


# ---- Reads ----

def list_my_reports(user_uid: str) -> list[dict]:
    docs = (
        _db().collection(REPORTS)
        .where("reporter_uid", "==", user_uid)
        .stream()
    )
    items = [_to_read(d.id, d.to_dict(), include_media=False) for d in docs]
    items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return items[:200]


def get_report_for_user(report_id: str, user_uid: str, is_authority: bool) -> dict:
    data = _get_or_404(report_id)
    if not is_authority and data["reporter_uid"] != user_uid:
        # Prevent IDOR: a user may only read their own report.
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not authorized for this report.")
    return _to_read(report_id, data, include_media=True)


def list_all_reports(filters: dict, limit: int = 200) -> list[dict]:
    q = _db().collection(REPORTS)
    if filters.get("status"):
        q = q.where("status", "==", filters["status"])
    if filters.get("priority"):
        q = q.where("priority", "==", filters["priority"])
    docs = q.stream()
    items = [_to_read(d.id, d.to_dict(), include_media=False) for d in docs]
    items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return items[:limit]


def list_nearby(max_distance_km: Optional[float] = None,
                center: Optional[dict] = None, limit: int = 100) -> list[dict]:
    """Return reports with valid coordinates for map display.

    Firestore has no native geo-radius query without a geo-point index, so we
    fetch recent reports and, if a center is supplied, optionally filter by
    great-circle distance. Only non-sensitive fields are exposed publicly.
    """
    docs = (
        _db().collection(REPORTS)
        .order_by("created_at", descending=True)
        .limit(500)
        .stream()
    )
    out = []
    for d in docs:
        data = d.to_dict() or {}
        loc = _geo(data.get("location"))
        if not loc or loc.get("latitude") is None:
            continue
        item = {
            "id": d.id,
            "location": loc,
            "status": data.get("status"),
            "priority": data.get("priority"),
            "pothole_count": data.get("pothole_count", 0),
            "address": data.get("address"),
            "category": data.get("category"),
        }
        if center and max_distance_km is not None:
            dist = _haversine_km(center["latitude"], center["longitude"],
                                 loc["latitude"], loc["longitude"])
            if dist > max_distance_km:
                continue
            item["distance_km"] = round(dist, 2)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    import math
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ---- Authority mutations ----

def _update(report_id: str, fields: dict) -> None:
    fields = {**fields, "updated_at": _now_iso()}
    _db().collection(REPORTS).document(report_id).update(fields)


def verify_report(report_id: str, decision: str, note: Optional[str], actor: str,
                  actor_email: Optional[str]) -> dict:
    data = _get_or_404(report_id)
    _validate_transition(data["status"], decision)
    now = _now_iso()
    _update(report_id, {
        "status": decision,
        "verified_by": actor,
        "verified_at": now,
        "review_note": note,
    })
    _add_history(report_id, decision, actor, prev=data["status"], new=decision, reason=note)
    email_service.notify_status_change(
        decision, report_id, data.get("reporter_email"), data.get("address"))
    return get_report_for_user(report_id, actor, is_authority=True)


def reject_report(report_id: str, reason: str, actor: str) -> dict:
    data = _get_or_404(report_id)
    _validate_transition(data["status"], "rejected")
    _update(report_id, {"status": "rejected", "rejection_reason": reason})
    _add_history(report_id, "rejected", actor, prev=data["status"], new="rejected", reason=reason)
    email_service.notify_status_change(
        "rejected", report_id, data.get("reporter_email"), data.get("address"))
    return get_report_for_user(report_id, actor, is_authority=True)


def set_priority(report_id: str, priority: str, reason: Optional[str], actor: str) -> dict:
    data = _get_or_404(report_id)
    _update(report_id, {"priority": priority})
    _add_history(report_id, "priority_changed", actor,
                 prev=data.get("priority"), new=priority, reason=reason)
    return get_report_for_user(report_id, actor, is_authority=True)


def assign_team(report_id: str, team_id: str, target_date: Optional[str],
                notes: Optional[str], actor: str) -> dict:
    data = _get_or_404(report_id)
    _validate_transition(data["status"], "assigned")
    team = _db().collection(TEAMS).document(team_id).get()
    if not team.exists:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Maintenance team not found.")
    team_name = (team.to_dict() or {}).get("name")
    _update(report_id, {
        "status": "assigned",
        "assigned_team_id": team_id,
        "assigned_team_name": team_name,
        "target_repair_date": target_date,
        "assignment_notes": notes,
        "assigned_at": _now_iso(),
    })
    _add_history(report_id, "assigned", actor, prev=data["status"], new="assigned", reason=notes)
    email_service.notify_status_change(
        "assigned", report_id, data.get("reporter_email"), data.get("address"))
    return get_report_for_user(report_id, actor, is_authority=True)


def update_status(report_id: str, target: str, note: Optional[str],
                  evidence_object: Optional[str], actor: str) -> dict:
    data = _get_or_404(report_id)
    _validate_transition(data["status"], target)

    if target == "resolved":
        if not evidence_object and not data.get("repair_evidence_object"):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="Repair evidence is required before resolving a report.",
            )
        fields = {"status": "resolved", "completed_at": _now_iso()}
        if evidence_object:
            fields["repair_evidence_object"] = evidence_object
        _update(report_id, fields)
    else:
        _update(report_id, {"status": target})

    _add_history(report_id, f"status_{target}", actor, prev=data["status"], new=target, reason=note)
    email_service.notify_status_change(
        target, report_id, data.get("reporter_email"), data.get("address"))
    return get_report_for_user(report_id, actor, is_authority=True)


# ---- Analytics ----

def analytics() -> dict:
    docs = _db().collection(REPORTS).stream()
    by_status: dict[str, int] = {}
    by_priority: dict[str, int] = {}
    by_area: dict[str, int] = {}
    total = 0
    submit_to_verify_ms = []
    assign_to_complete_ms = []

    def parse(ts):
        try:
            return dt.datetime.fromisoformat(ts)
        except Exception:
            return None

    for d in docs:
        data = d.to_dict() or {}
        total += 1
        s = data.get("status", "submitted")
        by_status[s] = by_status.get(s, 0) + 1
        p = data.get("priority") or "unset"
        by_priority[p] = by_priority.get(p, 0) + 1
        area = (data.get("address") or "Unknown").split(",")[0].strip() or "Unknown"
        by_area[area] = by_area.get(area, 0) + 1

        created, verified = parse(data.get("created_at")), parse(data.get("verified_at"))
        if created and verified:
            submit_to_verify_ms.append((verified - created).total_seconds())
        assigned, completed = parse(data.get("assigned_at")), parse(data.get("completed_at"))
        if assigned and completed:
            assign_to_complete_ms.append((completed - assigned).total_seconds())

    def avg_hours(values):
        return round(sum(values) / len(values) / 3600, 2) if values else None

    return {
        "total_reports": total,
        "by_status": by_status,
        "by_priority": by_priority,
        "by_area": dict(sorted(by_area.items(), key=lambda x: -x[1])[:15]),
        "new_reports": by_status.get("submitted", 0),
        "pending_verification": by_status.get("submitted", 0) + by_status.get("under_review", 0),
        "verified": by_status.get("verified", 0),
        "high_priority": by_priority.get("high", 0) + by_priority.get("critical", 0),
        "awaiting_assignment": by_status.get("verified", 0),
        "active_repairs": by_status.get("assigned", 0) + by_status.get("in_progress", 0),
        "completed_repairs": by_status.get("resolved", 0),
        "rejected": by_status.get("rejected", 0),
        "avg_hours_submit_to_verify": avg_hours(submit_to_verify_ms),
        "avg_hours_assign_to_complete": avg_hours(assign_to_complete_ms),
    }


# ---- Maintenance teams ----

def list_teams() -> list[dict]:
    docs = _db().collection(TEAMS).stream()
    return [{"id": d.id, **d.to_dict()} for d in docs]


def create_team(payload: dict) -> str:
    ref = _db().collection(TEAMS).document()
    ref.set({**payload, "created_at": _now_iso(), "updated_at": _now_iso()})
    return ref.id


def update_team(team_id: str, fields: dict) -> dict:
    snap = _db().collection(TEAMS).document(team_id).get()
    if not snap.exists:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Team not found.")
    _db().collection(TEAMS).document(team_id).update({**fields, "updated_at": _now_iso()})
    return {"id": team_id, **(snap.to_dict() or {}), **fields}
