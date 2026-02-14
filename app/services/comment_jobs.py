from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

_JOBS: Dict[str, Dict[str, Any]] = {}
_LOCK = asyncio.Lock()
_MAX_JOBS = 800
_DONE_TTL = timedelta(hours=8)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _job_view(job: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "job_id": job["job_id"],
        "user_id": job["user_id"],
        "post_id": job["post_id"],
        "post_title": job.get("post_title") or "",
        "status": job["status"],
        "error": job.get("error"),
        "pending_variants": list(job.get("pending_variants") or []),
        "ready_variants": list(job.get("ready_variants") or []),
        "updated_at": job.get("updated_at"),
        "created_at": job.get("created_at"),
    }


def _prune_jobs_locked(now: datetime) -> None:
    stale_ids = []
    for job_id, job in _JOBS.items():
        updated_raw = job.get("_updated_dt")
        if not isinstance(updated_raw, datetime):
            stale_ids.append(job_id)
            continue
        if job.get("status") in ("done", "error") and now - updated_raw > _DONE_TTL:
            stale_ids.append(job_id)
    for job_id in stale_ids:
        _JOBS.pop(job_id, None)

    if len(_JOBS) > _MAX_JOBS:
        # Keep newest records only.
        ordered = sorted(
            _JOBS.values(),
            key=lambda item: item.get("_updated_dt") or now,
            reverse=True,
        )
        keep_ids = {job["job_id"] for job in ordered[:_MAX_JOBS]}
        for job_id in list(_JOBS.keys()):
            if job_id not in keep_ids:
                _JOBS.pop(job_id, None)


async def create_comment_job(
    *,
    user_id: int,
    post_id: int,
    post_title: str = "",
    pending_variants: Optional[list[str]] = None,
    ready_variants: Optional[list[str]] = None,
) -> Dict[str, Any]:
    now = _utcnow()
    job_id = uuid4().hex
    job = {
        "job_id": job_id,
        "user_id": int(user_id),
        "post_id": int(post_id),
        "post_title": post_title or "",
        "status": "running",
        "error": None,
        "pending_variants": list(pending_variants or []),
        "ready_variants": list(ready_variants or []),
        "created_at": _iso(now),
        "updated_at": _iso(now),
        "_updated_dt": now,
    }
    async with _LOCK:
        _prune_jobs_locked(now)
        _JOBS[job_id] = job
        return _job_view(job)


async def mark_comment_job_done(
    job_id: str,
    *,
    ready_variants: Optional[list[str]] = None,
    pending_variants: Optional[list[str]] = None,
) -> Optional[Dict[str, Any]]:
    now = _utcnow()
    async with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None
        job["status"] = "done"
        job["error"] = None
        if ready_variants is not None:
            job["ready_variants"] = list(ready_variants)
        if pending_variants is not None:
            job["pending_variants"] = list(pending_variants)
        job["updated_at"] = _iso(now)
        job["_updated_dt"] = now
        _prune_jobs_locked(now)
        return _job_view(job)


async def mark_comment_job_error(
    job_id: str,
    *,
    error: str,
) -> Optional[Dict[str, Any]]:
    now = _utcnow()
    async with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None
        job["status"] = "error"
        job["error"] = (error or "unknown_error")[:500]
        job["updated_at"] = _iso(now)
        job["_updated_dt"] = now
        _prune_jobs_locked(now)
        return _job_view(job)


async def get_comment_job(job_id: str, *, user_id: int) -> Optional[Dict[str, Any]]:
    now = _utcnow()
    async with _LOCK:
        _prune_jobs_locked(now)
        job = _JOBS.get(job_id)
        if not job:
            return None
        if int(job.get("user_id") or 0) != int(user_id):
            return None
        return _job_view(job)

