import json
from datetime import datetime, timezone
from typing import Any

from .github_client import GitHubClient
from .settings import settings


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def parse_dt(value: str | None) -> str:
    if not value:
        return utcnow()
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None).isoformat()


class SyncService:
    def __init__(self, db, client: GitHubClient):
        self.db = db
        self.client = client

    def set_state(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO sync_state(key,value,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
            (key, value, utcnow()),
        )
        self.db.commit()

    async def sync(self) -> dict[str, Any]:
        if not self.client.configured:
            return {"status": "not_configured"}

        started = datetime.now(timezone.utc)
        repos = await self.sync_repositories()
        prs = await self.client.open_prs()
        issues = await self.client.open_issues()
        rate = await self.client.rate_limit()

        for repo in repos[:settings.detail_repo_limit]:
            await self.sync_repo_details(repo)

        self.set_state("last_sync", started.replace(tzinfo=None).isoformat())
        self.set_state("repo_count", str(len(repos)))
        self.set_state("open_prs", str(prs.get("total_count", 0)))
        self.set_state("open_issues", str(issues.get("total_count", 0)))
        core = rate.get("resources", {}).get("core", {})
        self.set_state("rate_remaining", str(core.get("remaining", "")))
        self.set_state("rate_limit", str(core.get("limit", "")))

        return {
            "status": "ok",
            "repositories": len(repos),
            "open_pull_requests": prs.get("total_count", 0),
            "open_issues": issues.get("total_count", 0),
            "rate_limit": rate.get("resources", {}).get("core", {}),
            "detail_repo_limit": settings.detail_repo_limit,
            "duration_seconds": round((datetime.now(timezone.utc) - started).total_seconds(), 2),
        }

    async def sync_repositories(self) -> list[dict[str, Any]]:
        repos: list[dict[str, Any]] = []
        page = 1

        while True:
            batch = await self.client.repositories(page)
            repos.extend(batch)
            now = utcnow()

            for item in batch:
                self.db.execute(
                    """
                    INSERT INTO repositories(
                        github_id,full_name,name,owner,description,language,visibility,
                        private,archived,fork,stars,forks,open_issues,default_branch,
                        updated_at_github,pushed_at_github,synced_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(github_id) DO UPDATE SET
                        full_name=excluded.full_name,name=excluded.name,owner=excluded.owner,
                        description=excluded.description,language=excluded.language,
                        visibility=excluded.visibility,private=excluded.private,
                        archived=excluded.archived,fork=excluded.fork,stars=excluded.stars,
                        forks=excluded.forks,open_issues=excluded.open_issues,
                        default_branch=excluded.default_branch,
                        updated_at_github=excluded.updated_at_github,
                        pushed_at_github=excluded.pushed_at_github,
                        synced_at=excluded.synced_at
                    """,
                    (
                        item["id"], item["full_name"], item["name"], item["owner"]["login"],
                        item.get("description"), item.get("language"), item.get("visibility"),
                        int(bool(item.get("private"))), int(bool(item.get("archived"))),
                        int(bool(item.get("fork"))), item.get("stargazers_count", 0),
                        item.get("forks_count", 0), item.get("open_issues_count", 0),
                        item.get("default_branch"), item.get("updated_at"),
                        item.get("pushed_at"), now,
                    ),
                )

            self.db.commit()

            if len(batch) < 100:
                break

            page += 1

        return repos

    async def sync_repo_details(self, repo: dict[str, Any]) -> None:
        full_name = repo["full_name"]
        commits = await self.safe_list(self.client.recent_commits(full_name))
        releases = await self.safe_list(self.client.recent_releases(full_name))
        runs = await self.safe_list(self.client.recent_workflow_runs(full_name))
        items = await self.safe_list(self.client.recent_issues_and_prs(full_name))

        for commit in commits[:10]:
            msg = (commit.get("commit", {}).get("message") or "").splitlines()[0][:500]
            self.upsert_event(
                f"commit:{full_name}:{commit.get('sha','')}",
                full_name, "commit", msg or "Commit",
                (commit.get("author") or {}).get("login"),
                commit.get("html_url"),
                parse_dt(commit.get("commit", {}).get("author", {}).get("date")),
                commit,
            )

        for release in releases[:5]:
            tag = release.get("tag_name") or str(release.get("id"))
            self.upsert_event(
                f"release:{full_name}:{tag}",
                full_name, "release", release.get("name") or tag,
                (release.get("author") or {}).get("login"),
                release.get("html_url"),
                parse_dt(release.get("published_at") or release.get("created_at")),
                release,
            )

        for run in runs[:10]:
            status = run.get("conclusion") or run.get("status") or "unknown"
            kind = "workflow_failure" if status in {
                "failure", "cancelled", "timed_out", "action_required", "stale"
            } else "workflow"

            self.upsert_event(
                f"workflow:{full_name}:{run.get('id')}",
                full_name, kind,
                f"{run.get('name') or 'Workflow'} · {status}",
                (run.get("actor") or {}).get("login"),
                run.get("html_url"),
                parse_dt(run.get("updated_at") or run.get("created_at")),
                run,
            )

        for item in items[:20]:
            kind = "pull_request" if item.get("pull_request") else "issue"
            number = item.get("number")
            state = item.get("state", "unknown")
            self.upsert_event(
                f"{kind}:{full_name}:{number}:{item.get('updated_at')}",
                full_name, kind,
                f"#{number} · {item.get('title','')} · {state}"[:500],
                (item.get("user") or {}).get("login"),
                item.get("html_url"),
                parse_dt(item.get("updated_at") or item.get("created_at")),
                item,
            )

        self.db.commit()

    async def safe_list(self, awaitable) -> list[dict[str, Any]]:
        try:
            value = await awaitable
            return value if isinstance(value, list) else []
        except Exception:
            return []

    def upsert_event(
        self, key: str, repo: str, kind: str, title: str,
        actor: str | None, url: str | None, created_at: str, payload: dict,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO events(
                event_key,repo_full_name,event_type,title,actor,url,created_at,payload
            ) VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(event_key) DO UPDATE SET
                title=excluded.title,actor=excluded.actor,url=excluded.url,
                created_at=excluded.created_at,payload=excluded.payload
            """,
            (
                key, repo, kind, title[:500], actor, url, created_at,
                json.dumps(payload, default=str)[:50000],
            ),
        )
