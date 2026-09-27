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


def analytics_payload(db) -> dict:
    now = datetime.utcnow()
    repos = [dict(r) for r in db.execute("SELECT * FROM repositories").fetchall()]

    def parse(value):
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None

    active_7 = active_30 = stale_30 = stale_90 = archived = private = 0
    total_stars = total_forks = 0
    languages = {}
    health = []

    for repo in repos:
        last = parse(repo.get("pushed_at")) or parse(repo.get("updated_at_github"))
        age = (now - last).days if last else 9999
        active_7 += age <= 7
        active_30 += age <= 30
        stale_30 += age > 30
        stale_90 += age > 90
        archived += bool(repo.get("archived"))
        private += bool(repo.get("private"))
        total_stars += int(repo.get("stars") or 0)
        total_forks += int(repo.get("forks") or 0)

        lang = repo.get("language") or "Unknown"
        languages[lang] = languages.get(lang, 0) + 1

        failures = db.execute(
            "SELECT COUNT(*) FROM events WHERE repo_full_name=? "
            "AND event_type='workflow_failure' AND created_at >= ?",
            (repo["full_name"], (now - timedelta(days=7)).isoformat()),
        ).fetchone()[0]

        score = 100
        flags = []
        if repo.get("archived"):
            score -= 25
            flags.append("archived")
        if age > 90:
            score -= 30
            flags.append("stale_90d")
        elif age > 30:
            score -= 15
            flags.append("stale_30d")
        if int(repo.get("open_issues") or 0) > 10:
            score -= 5
            flags.append("many_open_issues")
        if failures:
            score -= min(25, failures * 5)
            flags.append(f"ci_failures_7d:{failures}")

        health.append({
            "full_name": repo["full_name"],
            "score": max(0, score),
            "flags": flags,
            "language": lang,
            "stars": int(repo.get("stars") or 0),
            "open_issues": int(repo.get("open_issues") or 0),
            "updated_at": repo.get("updated_at_github"),
        })

    event_rows = db.execute(
        "SELECT event_type, COUNT(*) AS n FROM events GROUP BY event_type ORDER BY n DESC"
    ).fetchall()
    activity_rows = db.execute(
        "SELECT repo_full_name, COUNT(*) AS n FROM events "
        "GROUP BY repo_full_name ORDER BY n DESC LIMIT 10"
    ).fetchall()

    cutoff = (now - timedelta(days=7)).isoformat()
    workflow_runs = db.execute(
        "SELECT COUNT(*) FROM events WHERE event_type IN ('workflow','workflow_failure') "
        "AND created_at >= ?", (cutoff,)
    ).fetchone()[0]
    workflow_failures = db.execute(
        "SELECT COUNT(*) FROM events WHERE event_type='workflow_failure' AND created_at >= ?",
        (cutoff,)
    ).fetchone()[0]

    return {
        "repo_count": len(repos),
        "active_7d": active_7,
        "active_30d": active_30,
        "stale_30d": stale_30,
        "stale_90d": stale_90,
        "archived": archived,
        "private": private,
        "public": len(repos) - private,
        "total_stars": total_stars,
        "total_forks": total_forks,
        "languages": [
            {"name": k, "count": v}
            for k, v in sorted(languages.items(), key=lambda x: x[1], reverse=True)[:10]
        ],
        "events": [{"type": r["event_type"], "count": r["n"]} for r in event_rows],
        "top_activity": [{"repo": r["repo_full_name"], "count": r["n"]} for r in activity_rows],
        "workflow_runs_7d": workflow_runs,
        "workflow_failures_7d": workflow_failures,
        "workflow_success_rate_7d": round((workflow_runs-workflow_failures)/workflow_runs*100, 1) if workflow_runs else None,
        "health": sorted(health, key=lambda x: (x["score"], x["full_name"]))[:12],
    }


@app.get("/api/v1/analytics")
def analytics():
    db = connect()
    try:
        return analytics_payload(db)
    finally:
        db.close()


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
