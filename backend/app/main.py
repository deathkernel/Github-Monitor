import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, Query

from .db import connect
from .github_client import GitHubClient
from .settings import settings
from .sync_service import SyncService

github = GitHubClient()
sync_task = None
sync_lock = asyncio.Lock()


async def background_sync():
    while True:
        try:
            async with sync_lock:
                db = connect()
                try:
                    await SyncService(db, github).sync()
                finally:
                    db.close()
        except Exception:
            pass
        await asyncio.sleep(max(60, settings.poll_interval_seconds))


@asynccontextmanager
async def lifespan(app: FastAPI):
    global sync_task
    db = connect()
    db.close()

    if github.configured:
        sync_task = asyncio.create_task(background_sync())

    yield

    if sync_task:
        sync_task.cancel()
        with suppress(asyncio.CancelledError):
            await sync_task


app = FastAPI(title="GitHub Monitor API", version="1.1.0", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "service": "github-monitor"}


@app.get("/api/v1/connection")
async def connection():
    if not github.configured:
        return {"connected": False, "reason": "GITHUB_TOKEN is not configured"}

    try:
        profile = await github.profile()
        rate = await github.rate_limit()
        return {
            "connected": True,
            "login": profile.get("login"),
            "name": profile.get("name"),
            "avatar_url": profile.get("avatar_url"),
            "rate_limit": rate.get("resources", {}).get("core", {}),
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GitHub connection failed: {exc}") from exc


@app.post("/api/v1/sync")
async def run_sync():
    if not github.configured:
        raise HTTPException(status_code=503, detail="Configure GITHUB_TOKEN first")

    async with sync_lock:
        db = connect()
        try:
            return await SyncService(db, github).sync()
        finally:
            db.close()


@app.get("/api/v1/overview")
def overview():
    db = connect()
    try:
        def state(name):
            row = db.execute(
                "SELECT value FROM sync_state WHERE key=?",
                (name,),
            ).fetchone()
            return row[0] if row else None

        repo_count = int(state("repo_count") or db.execute(
            "SELECT COUNT(*) FROM repositories"
        ).fetchone()[0])

        recent_cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
        ci_failures = db.execute(
            "SELECT COUNT(*) FROM events "
            "WHERE event_type='workflow_failure' AND created_at >= ?",
            (recent_cutoff,),
        ).fetchone()[0]

        last_sync = state("last_sync")
        open_prs = int(state("open_prs") or 0)
        open_issues = int(state("open_issues") or 0)
        remaining = state("rate_remaining")
        limit = state("rate_limit")
    finally:
        db.close()

    if not github.configured:
        return {
            "repositories": repo_count,
            "open_pull_requests": 0,
            "open_issues": 0,
            "recent_ci_failures": ci_failures,
            "sync": "not_connected",
            "last_sync": last_sync,
        }

    return {
        "repositories": repo_count,
        "open_pull_requests": open_prs,
        "open_issues": open_issues,
        "recent_ci_failures": ci_failures,
        "sync": "live",
        "last_sync": last_sync,
        "poll_interval_seconds": settings.poll_interval_seconds,
        "detail_repo_limit": settings.detail_repo_limit,
        "rate_limit": {
            "remaining": int(remaining) if remaining else None,
            "limit": int(limit) if limit else None,
        },
    }


@app.get("/api/v1/repositories")
def repositories(
    limit: int = Query(100, ge=1, le=500),
    include_archived: bool = True,
):
    db = connect()
    try:
        sql = "SELECT * FROM repositories"
        params = []
        if not include_archived:
            sql += " WHERE archived=0"
        sql += " ORDER BY updated_at_github DESC LIMIT ?"
        params.append(limit)
        rows = db.execute(sql, params).fetchall()
        total = db.execute("SELECT COUNT(*) FROM repositories").fetchone()[0]
        return {"count": total, "repositories": [dict(row) for row in rows]}
    finally:
        db.close()


@app.get("/api/v1/events")
def events(limit: int = Query(50, ge=1, le=200), event_type: str | None = None):
    db = connect()
    try:
        if event_type:
            rows = db.execute(
                "SELECT * FROM events WHERE event_type=? ORDER BY created_at DESC LIMIT ?",
                (event_type, limit),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM events ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return {"count": len(rows), "events": [dict(row) for row in rows]}
    finally:
        db.close()


@app.get("/api/v1/repositories/{full_name:path}")
def repository_detail(full_name: str):
    db = connect()
    try:
        repo = db.execute(
            "SELECT * FROM repositories WHERE full_name=?",
            (full_name,),
        ).fetchone()

        if repo is None:
            raise HTTPException(
                status_code=404,
                detail="Repository not found in local monitor cache",
            )

        rows = db.execute(
            "SELECT * FROM events WHERE repo_full_name=? ORDER BY created_at DESC LIMIT 30",
            (full_name,),
        ).fetchall()

        result = dict(repo)
        result["events"] = [dict(row) for row in rows]
        return result
    finally:
        db.close()
