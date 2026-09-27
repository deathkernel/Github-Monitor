import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from .github_client import GitHubClient
from .models import Event, Repository, SyncState
from .settings import settings


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SyncService:
    def __init__(self, db: Session, client: GitHubClient):
        self.db = db
        self.client = client

    def set_state(self, key: str, value: str) -> None:
        row = self.db.execute(select(SyncState).where(SyncState.key == key)).scalar_one_or_none()
        if row is None:
            row = SyncState(key=key, value=value)
            self.db.add(row)
        else:
            row.value = value
            row.updated_at = utcnow()
        self.db.commit()

    def get_state(self, key: str) -> str | None:
        row = self.db.execute(select(SyncState).where(SyncState.key == key)).scalar_one_or_none()
        return row.value if row else None

    async def sync(self) -> dict[str, Any]:
        if not self.client.configured:
            return {"status": "not_configured"}

        started = utcnow()
        repos = await self._sync_repositories()
        prs = await self.client.open_prs()
        issues = await self.client.open_issues()
        rate = await self.client.rate_limit()

        for repo in repos[: settings.detail_repo_limit]:
            await self._sync_repo_details(repo)

        self.set_state("last_sync", started.isoformat())
        self.set_state("repo_count", str(len(repos)))

        return {
            "status": "ok",
            "repositories": len(repos),
            "open_pull_requests": prs.get("total_count", 0),
            "open_issues": issues.get("total_count", 0),
            "rate_limit": rate.get("resources", {}).get("core", {}),
            "detail_repo_limit": settings.detail_repo_limit,
            "duration_seconds": round((utcnow() - started).total_seconds(), 2),
        }

    async def _sync_repositories(self) -> list[dict[str, Any]]:
        repos: list[dict[str, Any]] = []
        page = 1

        while True:
            batch = await self.client.repositories(page)
            repos.extend(batch)

            for item in batch:
                existing = self.db.execute(
                    select(Repository).where(Repository.github_id == item["id"])
                ).scalar_one_or_none()
                if existing is None:
                    existing = Repository(github_id=item["id"])
                    self.db.add(existing)

                existing.full_name = item["full_name"]
                existing.name = item["name"]
                existing.owner = item["owner"]["login"]
                existing.description = item.get("description")
                existing.language = item.get("language")
                existing.visibility = item.get("visibility")
                existing.private = bool(item.get("private"))
                existing.archived = bool(item.get("archived"))
                existing.fork = bool(item.get("fork"))
                existing.stars = item.get("stargazers_count", 0)
                existing.forks = item.get("forks_count", 0)
                existing.open_issues = item.get("open_issues_count", 0)
                existing.default_branch = item.get("default_branch")
                existing.updated_at_github = parse_dt(item.get("updated_at"))
                existing.pushed_at_github = parse_dt(item.get("pushed_at"))
                existing.synced_at = utcnow()

            self.db.commit()
            if len(batch) < 100:
                break
            page += 1

        return repos

    async def _sync_repo_details(self, repo: dict[str, Any]) -> None:
        full_name = repo["full_name"]
        commits = await self.client.recent_commits(full_name)
        releases = await self.client.recent_releases(full_name)
        runs = await self.client.recent_workflow_runs(full_name)
        work_items = await self.client.recent_issues_and_prs(full_name)

        for commit in commits[:10]:
            sha = commit.get("sha", "")
            created = (
                parse_dt(commit.get("commit", {}).get("author", {}).get("date"))
                or utcnow()
            )
            self._upsert_event(
                event_key=f"commit:{full_name}:{sha}",
                repo_full_name=full_name,
                event_type="commit",
                title=commit.get("commit", {}).get("message", "").splitlines()[0][:500],
                actor=(commit.get("author") or {}).get("login"),
                url=commit.get("html_url"),
                created_at=created,
                payload=commit,
            )

        for release in releases[:5]:
            tag = release.get("tag_name") or str(release.get("id"))
            self._upsert_event(
                event_key=f"release:{full_name}:{tag}",
                repo_full_name=full_name,
                event_type="release",
                title=release.get("name") or tag,
                actor=(release.get("author") or {}).get("login"),
                url=release.get("html_url"),
                created_at=parse_dt(
                    release.get("published_at") or release.get("created_at")
                ) or utcnow(),
                payload=release,
            )

        for run in runs[:10]:
            run_id = run.get("id")
            status = run.get("conclusion") or run.get("status") or "unknown"
            event_type = (
                "workflow_failure"
                if status in {"failure", "cancelled", "timed_out", "action_required", "stale"}
                else "workflow"
            )
            self._upsert_event(
                event_key=f"workflow:{full_name}:{run_id}",
                repo_full_name=full_name,
                event_type=event_type,
                title=f"{run.get('name') or 'Workflow'} · {status}",
                actor=(run.get("actor") or {}).get("login"),
                url=run.get("html_url"),
                created_at=parse_dt(
                    run.get("updated_at") or run.get("created_at")
                ) or utcnow(),
                payload=run,
            )

        for item in work_items[:20]:
            number = item.get("number")
            is_pr = bool(item.get("pull_request"))
            kind = "pull_request" if is_pr else "issue"
            state = item.get("state", "unknown")
            self._upsert_event(
                event_key=f"{kind}:{full_name}:{number}:{item.get('updated_at')}",
                repo_full_name=full_name,
                event_type=kind,
                title=f"#{number} · {item.get('title', '')} · {state}"[:500],
                actor=(item.get("user") or {}).get("login"),
                url=item.get("html_url"),
                created_at=parse_dt(
                    item.get("updated_at") or item.get("created_at")
                ) or utcnow(),
                payload=item,
            )

        self.db.commit()

    def _upsert_event(
        self,
        event_key: str,
        repo_full_name: str,
        event_type: str,
        title: str,
        actor: str | None,
        url: str | None,
        created_at: datetime,
        payload: dict[str, Any],
    ) -> None:
        row = self.db.execute(
            select(Event).where(Event.event_key == event_key)
        ).scalar_one_or_none()

        if row is None:
            row = Event(event_key=event_key)
            self.db.add(row)

        row.repo_full_name = repo_full_name
        row.event_type = event_type
        row.title = title[:500]
        row.actor = actor
        row.url = url
        row.created_at = created_at
        row.payload = json.dumps(payload, default=str)[:50000]

    def recent_events(self, limit: int = 50) -> list[Event]:
        return list(
            self.db.execute(
                select(Event).order_by(desc(Event.created_at)).limit(limit)
            ).scalars()
        )
