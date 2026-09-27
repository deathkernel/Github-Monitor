import asyncio
import json
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from .db import connect
from .github_client import GitHubClient, RateLimitPaused
from .settings import settings
from .sync_service import SyncService
github = GitHubClient()
sync_task = None
job_task = None
sync_lock = asyncio.Lock()


class IssueRequest(BaseModel):
    repo_full_name: str
    title: str
    body: str = ""


class PullRequestRequest(BaseModel):
    repo_full_name: str
    title: str
    head: str
    base: str
    body: str = ""


class MergeRequest(BaseModel):
    repo_full_name: str
    number: int
    merge_method: str = "merge"


class RerunRequest(BaseModel):
    repo_full_name: str
    run_id: int


async def execute_job(job_id: int, kind: str, payload: dict):
    if kind == "sync":
        async with sync_lock:
            db = connect()
            try:
                return await SyncService(db, github).sync()
            finally:
                db.close()
    return {"status": "ignored", "kind": kind}


async def job_worker():
    while True:
        db = connect()
        try:
            now = datetime.utcnow().isoformat()
            row = db.execute(
                "SELECT id,kind,payload FROM jobs WHERE status='queued' AND run_after <= ? "
                "ORDER BY id LIMIT 1",
                (now,),
            ).fetchone()
            if row:
                db.execute(
                    "UPDATE jobs SET status='running',attempts=attempts+1,started_at=? WHERE id=?",
                    (now, row["id"]),
                )
                db.commit()
            else:
                row = None
        finally:
            db.close()

        if row:
            try:
                payload = json.loads(row["payload"] or "{}")
                await execute_job(row["id"], row["kind"], payload)
                db = connect()
                db.execute(
                    "UPDATE jobs SET status='done',finished_at=?,last_error=NULL WHERE id=?",
                    (datetime.utcnow().isoformat(), row["id"]),
                )
                db.commit()
                db.close()
            except Exception as exc:
                db = connect()
                db.execute(
                    "UPDATE jobs SET status='queued',finished_at=?,last_error=?,run_after=? WHERE id=?",
                    (
                        datetime.utcnow().isoformat(),
                        str(exc)[:1000],
                        (datetime.utcnow() + timedelta(minutes=1)).isoformat(),
                        row["id"],
                    ),
                )
                db.commit()
                db.close()

        await asyncio.sleep(2)


async def enqueue_job(kind: str, payload: dict | None = None) -> int:
    db = connect()
    try:
        now = datetime.utcnow().isoformat()
        cur = db.execute(
            "INSERT INTO jobs(kind,payload,status,run_after,created_at) VALUES(?,?,?,?,?)",
            (kind, json.dumps(payload or {}), "queued", now, now),
        )
        db.commit()
        return cur.lastrowid
    finally:
        db.close()


async def background_sync():
    while True:
        await enqueue_job("sync")
        await asyncio.sleep(max(60, settings.poll_interval_seconds))


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
    global sync_task, job_task

    global sync_task
    db = connect()
    db.close()

    if github.configured:
        job_task = asyncio.create_task(job_worker())
        sync_task = asyncio.create_task(background_sync())

    yield

    if sync_task:
        sync_task.cancel()
    if job_task:
        job_task.cancel()
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


@app.get("/api/v1/changes")
def changes(limit: int = Query(100, ge=1, le=500), severity: str | None = None, acknowledged: bool = False):
    db = connect()
    try:
        if severity:
            rows = db.execute(
                "SELECT * FROM changes WHERE acknowledged=? AND severity=? ORDER BY detected_at DESC LIMIT ?",
                (int(acknowledged), severity, limit),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM changes WHERE acknowledged=? ORDER BY detected_at DESC LIMIT ?",
                (int(acknowledged), limit),
            ).fetchall()
        return {"count": len(rows), "changes": [dict(r) for r in rows]}
    finally:
        db.close()


@app.post("/api/v1/changes/{change_id}/ack")
def acknowledge_change(change_id: int):
    db = connect()
    try:
        db.execute("UPDATE changes SET acknowledged=1 WHERE id=?", (change_id,))
        db.commit()
        return {"status": "ok", "id": change_id}
    finally:
        db.close()


@app.get("/api/v1/alerts")
def alerts(limit: int = Query(100, ge=1, le=500), status: str = "open"):
    db = connect()
    try:
        rows = db.execute(
            "SELECT * FROM alerts WHERE status=? ORDER BY created_at DESC LIMIT ?",
            (status, limit),
        ).fetchall()
        return {"count": len(rows), "alerts": [dict(r) for r in rows]}
    finally:
        db.close()


@app.get("/api/v1/history")
def history(days: int = Query(30, ge=1, le=365)):
    db = connect()
    try:
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        rows = db.execute(
            "SELECT substr(captured_at,1,10) AS day, COUNT(DISTINCT full_name) AS repos, "
            "SUM(stars) AS stars, SUM(forks) AS forks, SUM(open_issues) AS open_issues "
            "FROM repository_history WHERE captured_at >= ? GROUP BY day ORDER BY day",
            (cutoff,),
        ).fetchall()
        return {"days": days, "history": [dict(r) for r in rows]}
    finally:
        db.close()


@app.get("/api/v1/jobs")
def jobs(limit: int = Query(50, ge=1, le=200)):
    db = connect()
    try:
        rows = db.execute(
            "SELECT id,kind,status,attempts,run_after,created_at,started_at,finished_at,last_error "
            "FROM jobs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return {"jobs": [dict(r) for r in rows]}
    finally:
        db.close()


def ensure_write_actions():
    if not settings.enable_write_actions:
        raise HTTPException(
            status_code=403,
            detail="Write actions are disabled. Set ENABLE_WRITE_ACTIONS=true and grant matching GitHub permissions.",
        )


def log_action(action: str, repo: str | None, target: str | None, status: str, detail: str):
    db = connect()
    try:
        db.execute(
            "INSERT INTO action_audit(action,repo_full_name,target,status,detail,created_at) VALUES(?,?,?,?,?,?)",
            (action, repo, target, status, detail[:2000], datetime.utcnow().isoformat()),
        )
        db.commit()
    finally:
        db.close()


@app.post("/api/v1/actions/create-issue")
async def action_create_issue(request: IssueRequest):
    ensure_write_actions()
    try:
        result = await github.create_issue(request.repo_full_name, request.title, request.body)
        log_action("create_issue", request.repo_full_name, str(result.get("number")), "success", result.get("html_url", ""))
        return {"status": "success", "result": result}
    except Exception as exc:
        log_action("create_issue", request.repo_full_name, None, "failed", str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/v1/actions/create-pr")
async def action_create_pr(request: PullRequestRequest):
    ensure_write_actions()
    try:
        result = await github.create_pull_request(
            request.repo_full_name, request.title, request.head, request.base, request.body
        )
        log_action("create_pr", request.repo_full_name, str(result.get("number")), "success", result.get("html_url", ""))
        return {"status": "success", "result": result}
    except Exception as exc:
        log_action("create_pr", request.repo_full_name, None, "failed", str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/v1/actions/merge-pr")
async def action_merge_pr(request: MergeRequest):
    ensure_write_actions()
    try:
        result = await github.merge_pull_request(request.repo_full_name, request.number, request.merge_method)
        log_action("merge_pr", request.repo_full_name, str(request.number), "success", str(result))
        return {"status": "success", "result": result}
    except Exception as exc:
        log_action("merge_pr", request.repo_full_name, str(request.number), "failed", str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/v1/actions/rerun-failed-jobs")
async def action_rerun_failed(request: RerunRequest):
    ensure_write_actions()
    try:
        result = await github.rerun_failed_jobs(request.repo_full_name, request.run_id)
        log_action("rerun_failed_jobs", request.repo_full_name, str(request.run_id), "success", str(result))
        return {"status": "success", "result": result}
    except Exception as exc:
        log_action("rerun_failed_jobs", request.repo_full_name, str(request.run_id), "failed", str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/v1/audit")
def audit(limit: int = Query(100, ge=1, le=500)):
    db = connect()
    try:
        rows = db.execute(
            "SELECT * FROM action_audit ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return {"count": len(rows), "audit": [dict(r) for r in rows]}
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
