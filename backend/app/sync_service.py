import json
from datetime import datetime, timezone
from typing import Any

import httpx

from .github_client import GitHubClient, RateLimitPaused
from .settings import settings


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def parse_dt(value: str | None) -> str:
    if not value:
        return utcnow()
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None).isoformat()


SEVERITY_ORDER = {"info": 0, "warning": 1, "critical": 2}


class SyncService:
    def __init__(self, db, client: GitHubClient):
        self.db = db
        self.client = client
        self.new_changes: list[dict[str, Any]] = []

    def set_state(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO sync_state(key,value,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
            (key, value, utcnow()),
        )
        self.db.commit()

    def get_state(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM sync_state WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    async def sync(self) -> dict[str, Any]:
        if not self.client.configured:
            return {"status": "not_configured"}

        started = datetime.now(timezone.utc)
        self.new_changes = []

        try:
            repos = await self.sync_repositories()
            prs = await self.client.open_prs()
            issues = await self.client.open_issues()
            rate = await self.client.rate_limit()
        except RateLimitPaused as exc:
            self.set_state("sync_status", "rate_limited")
            self.set_state("sync_error", str(exc))
            return {"status": "rate_limited", "message": str(exc)}

        for repo in repos[:settings.detail_repo_limit]:
            try:
                await self.sync_repo_details(repo)
            except RateLimitPaused as exc:
                self.set_state("sync_status", "rate_limited")
                self.set_state("sync_error", str(exc))
                break

        self.set_state("last_sync", started.replace(tzinfo=None).isoformat())
        self.set_state("repo_count", str(len(repos)))
        self.set_state("open_prs", str(prs.get("total_count", 0)))
        self.set_state("open_issues", str(issues.get("total_count", 0)))

        core = rate.get("resources", {}).get("core", {})
        self.set_state("rate_remaining", str(core.get("remaining", "")))
        self.set_state("rate_limit", str(core.get("limit", "")))
        self.set_state("sync_status", "ok")

        await self.emit_notifications()

        return {
            "status": "ok",
            "repositories": len(repos),
            "open_pull_requests": prs.get("total_count", 0),
            "open_issues": issues.get("total_count", 0),
            "new_changes": len(self.new_changes),
            "rate_limit": core,
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
                old = self.db.execute(
                    "SELECT * FROM repositories WHERE github_id=?", (item["id"],)
                ).fetchone()

                if old:
                    tracked = [
                        ("stars", old["stars"], item.get("stargazers_count", 0)),
                        ("forks", old["forks"], item.get("forks_count", 0)),
                        ("open_issues", old["open_issues"], item.get("open_issues_count", 0)),
                        ("pushed_at_github", old["pushed_at_github"], item.get("pushed_at")),
                        ("archived", old["archived"], int(bool(item.get("archived")))),
                    ]
                    for field, before, after in tracked:
                        if str(before) != str(after):
                            sev = "warning" if field in {"archived", "open_issues"} else "info"
                            self.record_change(
                                item["full_name"], "repository_update", field,
                                str(before), str(after), sev,
                            )

                    snapshot_values = (
                        item["id"], item["full_name"], item["stargazers_count"],
                        item["forks_count"], item["open_issues_count"], item.get("pushed_at"),
                        int(bool(item.get("archived"))), int(bool(item.get("private"))), item.get("language"),
                        now,
                    )
                else:
                    self.record_change(
                        item["full_name"], "repository_discovered", "repository",
                        None, item["full_name"], "info",
                    )
                    snapshot_values = (
                        item["id"], item["full_name"], item["stargazers_count"],
                        item["forks_count"], item["open_issues_count"], item.get("pushed_at"),
                        int(bool(item.get("archived"))), int(bool(item.get("private"))), item.get("language"),
                        now,
                    )

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
                        pushed_at_github=excluded.pushed_at_github,synced_at=excluded.synced_at
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

                self.db.execute(
                    """
                    INSERT INTO repository_history(
                        github_id,full_name,captured_at,stars,forks,open_issues,
                        pushed_at_github,archived,private,language
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    snapshot_values,
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
            sha = commit.get("sha", "")
            key = f"commit:{full_name}:{sha}"
            inserted = self.upsert_event(
                key, full_name, "commit",
                ((commit.get("commit", {}).get("message") or "").splitlines() or ["Commit"])[0],
                (commit.get("author") or {}).get("login"),
                commit.get("html_url"),
                parse_dt(commit.get("commit", {}).get("author", {}).get("date")),
                commit,
            )
            if inserted:
                self.record_change(full_name, "new_activity", "commit", None, sha[:12], "info")

        for release in releases[:5]:
            tag = release.get("tag_name") or str(release.get("id"))
            inserted = self.upsert_event(
                f"release:{full_name}:{tag}", full_name, "release",
                release.get("name") or tag,
                (release.get("author") or {}).get("login"),
                release.get("html_url"),
                parse_dt(release.get("published_at") or release.get("created_at")),
                release,
            )
            if inserted:
                self.record_change(full_name, "new_activity", "release", None, tag, "warning")

        for run in runs[:10]:
            status = run.get("conclusion") or run.get("status") or "unknown"
            kind = "workflow_failure" if status in {
                "failure", "cancelled", "timed_out", "action_required", "stale"
            } else "workflow"
            inserted = self.upsert_event(
                f"workflow:{full_name}:{run.get('id')}", full_name, kind,
                f"{run.get('name') or 'Workflow'} · {status}",
                (run.get("actor") or {}).get("login"),
                run.get("html_url"),
                parse_dt(run.get("updated_at") or run.get("created_at")),
                run,
            )
            if inserted and kind == "workflow_failure":
                self.record_change(full_name, "ci_failure", "workflow", "healthy", status, "critical")

        for item in items[:20]:
            kind = "pull_request" if item.get("pull_request") else "issue"
            number = item.get("number")
            state = item.get("state", "unknown")
            inserted = self.upsert_event(
                f"{kind}:{full_name}:{number}:{item.get('updated_at')}", full_name, kind,
                f"#{number} · {item.get('title','')} · {state}"[:500],
                (item.get("user") or {}).get("login"), item.get("html_url"),
                parse_dt(item.get("updated_at") or item.get("created_at")), item,
            )
            if inserted:
                self.record_change(full_name, "new_work_item", kind, None, f"#{number}", "warning")

        self.db.commit()

    async def safe_list(self, awaitable) -> list[dict[str, Any]]:
        try:
            value = await awaitable
            return value if isinstance(value, list) else []
        except RateLimitPaused:
            raise
        except Exception:
            return []

    def upsert_event(self, key: str, repo: str, kind: str, title: str,
                     actor: str | None, url: str | None, created_at: str,
                     payload: dict) -> bool:
        exists = self.db.execute(
            "SELECT id FROM events WHERE event_key=?", (key,)
        ).fetchone()
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
        return exists is None

    def record_change(self, repo: str, change_type: str, field: str,
                      before: str | None, after: str | None, severity: str) -> None:
        detected = utcnow()
        key = f"{repo}:{change_type}:{field}:{after}:{detected[:16]}"
        self.db.execute(
            """
            INSERT OR IGNORE INTO changes(
                change_key,repo_full_name,change_type,field,before_value,after_value,severity,detected_at
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (key, repo, change_type, field, before, after, severity, detected),
        )

        if severity in {"warning", "critical"}:
            alert_key = f"{repo}:{change_type}:{field}:{after}"
            self.db.execute(
                """
                INSERT INTO alerts(alert_key,repo_full_name,rule,severity,title,details,status,created_at)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(alert_key) DO UPDATE SET
                    severity=excluded.severity,
                    title=excluded.title,
                    details=excluded.details
                """,
                (
                    alert_key,
                    repo,
                    change_type,
                    severity,
                    f"{repo}: {change_type.replace('_', ' ')}",
                    json.dumps({
                        "field": field,
                        "before": before,
                        "after": after,
                    }),
                    "open",
                    detected,
                ),
            )
        self.new_changes.append({
            "repo_full_name": repo,
            "change_type": change_type,
            "field": field,
            "before": before,
            "after": after,
            "severity": severity,
            "detected_at": detected,
        })

    async def emit_notifications(self) -> None:
        if not settings.notification_webhook_url or not self.new_changes:
            return

        threshold = SEVERITY_ORDER.get(settings.notification_min_severity, 1)
        changes = [c for c in self.new_changes if SEVERITY_ORDER.get(c["severity"], 0) >= threshold]
        if not changes:
            return

        grouped = {}
        for change in changes:
            grouped.setdefault(change["repo_full_name"], []).append(change)

        payload = {
            "source": "github-monitor",
            "severity": "critical" if any(c["severity"] == "critical" for c in changes) else "warning",
            "changes": changes[:50],
            "repositories": [
                {"repo": repo, "changes": items}
                for repo, items in list(grouped.items())[:20]
            ],
        }

        delivered = utcnow()
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(settings.notification_webhook_url, json=payload)
            status = "delivered" if response.is_success else "failed"
            self.db.execute(
                "INSERT INTO notification_deliveries(alert_id,channel,status,response_code,error,delivered_at) VALUES(NULL,?,?,?,?,?)",
                ("webhook", status, response.status_code, None if response.is_success else response.text[:500], delivered),
            )
        except Exception as exc:
            self.db.execute(
                "INSERT INTO notification_deliveries(alert_id,channel,status,response_code,error,delivered_at) VALUES(NULL,?,?,?,?,?)",
                ("webhook", "failed", None, str(exc)[:500], delivered),
            )
        self.db.commit()
