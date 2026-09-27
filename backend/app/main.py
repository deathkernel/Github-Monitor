import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from .db import Base, SessionLocal, engine, get_db
from .github_client import GitHubClient
from .models import Event, Repository
from .settings import settings
from .sync_service import SyncService

github = GitHubClient()
sync_task: asyncio.Task | None = None


async def background_sync() -> None:
    while True:
        try:
            db = SessionLocal()
            try:
                await SyncService(db, github).sync()
            finally:
                db.close()
        except Exception:
            # The next cycle retries; API failures should not kill the server.
            pass
        await asyncio.sleep(max(60, settings.poll_interval_seconds))


@asynccontextmanager
async def lifespan(app: FastAPI):
    global sync_task
    Base.metadata.create_all(bind=engine)
    if github.configured:
        sync_task = asyncio.create_task(background_sync())
    yield
    if sync_task:
        sync_task.cancel()
        with suppress(asyncio.CancelledError):
            await sync_task


app = FastAPI(title="GitHub Monitor API", version="1.0.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "github-monitor"}


@app.get("/api/v1/connection")
async def connection() -> dict:
    if not github.configured:
        return {"connected": False, "reason": "GITHUB_TOKEN is not configured"}

    try:
        profile = await github.profile()
        rate = await github.rate_limit()
        core = rate.get("resources", {}).get("core", {})
        return {
            "connected": True,
            "login": profile.get("login"),
            "name": profile.get("name"),
            "avatar_url": profile.get("avatar_url"),
            "rate_limit": core,
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GitHub connection failed: {exc}") from exc


@app.post("/api/v1/sync")
async def run_sync() -> dict:
    if not github.configured:
        raise HTTPException(status_code=503, detail="Configure GITHUB_TOKEN first")
    db = SessionLocal()
    try:
        return await SyncService(db, github).sync()
    finally:
        db.close()


@app.get("/api/v1/overview")
async def overview(db: Session = Depends(get_db)) -> dict:
    repo_count = db.query(Repository).count()
    last_sync = db.execute(
        select(Event.created_at).order_by(desc(Event.created_at)).limit(1)
    ).scalar_one_or_none()

    if not github.configured:
        return {
            "repositories": repo_count,
            "open_pull_requests": 0,
            "open_issues": 0,
            "failing_checks": 0,
            "sync": "not_connected",
            "last_event": last_sync.isoformat() if last_sync else None,
        }

    try:
        rate = await github.rate_limit()
        prs = await github.open_prs()
        issues = await github.open_issues()
        core = rate.get("resources", {}).get("core", {})
        return {
            "repositories": repo_count,
            "open_pull_requests": prs.get("total_count", 0),
            "open_issues": issues.get("total_count", 0),
            "recent_ci_failures": recent_ci_failures(db),
            "sync": "live",
            "last_sync": SyncService(db, github).get_state("last_sync"),
            "poll_interval_seconds": settings.poll_interval_seconds,
            "detail_repo_limit": settings.detail_repo_limit,
            "rate_limit": core,
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GitHub sync failed: {exc}") from exc


@app.get("/api/v1/repositories")
def repositories(
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
    include_archived: bool = True,
) -> dict:
    query = select(Repository).order_by(desc(Repository.updated_at_github))
    if not include_archived:
        query = query.where(Repository.archived.is_(False))
    items = list(db.execute(query.limit(limit)).scalars())
    return {
        "count": db.query(Repository).count(),
        "repositories": [repo_to_dict(r) for r in items],
    }


@app.get("/api/v1/events")
def events(
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    event_type: str | None = None,
) -> dict:
    query = select(Event).order_by(desc(Event.created_at))
    if event_type:
        query = query.where(Event.event_type == event_type)
    items = list(db.execute(query.limit(limit)).scalars())
    return {
        "count": len(items),
        "events": [event_to_dict(e) for e in items],
    }


@app.get("/api/v1/repositories/{full_name:path}")
def repository_detail(full_name: str, db: Session = Depends(get_db)) -> dict:
    repo = db.execute(select(Repository).where(Repository.full_name == full_name)).scalar_one_or_none()
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found in local monitor cache")
    recent = list(
        db.execute(
            select(Event)
            .where(Event.repo_full_name == repo.full_name)
            .order_by(desc(Event.created_at))
            .limit(30)
        ).scalars()
    )
    result = repo_to_dict(repo)
    result["events"] = [event_to_dict(e) for e in recent]
    return result


def recent_ci_failures(db: Session) -> int:
    cutoff = datetime.utcnow() - timedelta(days=7)
    return db.query(Event).filter(
        Event.event_type == "workflow_failure",
        Event.created_at >= cutoff,
    ).count()


def repo_to_dict(repo: Repository) -> dict:
    return {
        "id": repo.id,
        "github_id": repo.github_id,
        "name": repo.name,
        "full_name": repo.full_name,
        "owner": repo.owner,
        "description": repo.description,
        "language": repo.language,
        "visibility": repo.visibility,
        "private": repo.private,
        "archived": repo.archived,
        "fork": repo.fork,
        "stars": repo.stars,
        "forks": repo.forks,
        "open_issues": repo.open_issues,
        "default_branch": repo.default_branch,
        "updated_at": repo.updated_at_github.isoformat() if repo.updated_at_github else None,
        "pushed_at": repo.pushed_at_github.isoformat() if repo.pushed_at_github else None,
        "synced_at": repo.synced_at.isoformat() if repo.synced_at else None,
    }


def event_to_dict(event: Event) -> dict:
    return {
        "id": event.id,
        "repo_full_name": event.repo_full_name,
        "type": event.event_type,
        "title": event.title,
        "actor": event.actor,
        "url": event.url,
        "created_at": event.created_at.isoformat(),
    }
