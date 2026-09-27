import asyncio
import time
from typing import Any

import httpx

from .settings import settings


class RateLimitPaused(RuntimeError):
    pass


class GitHubClient:
    def __init__(self) -> None:
        self.base_url = settings.github_api_url.rstrip("/")
        self.headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2026-03-10",
            "User-Agent": "github-monitor",
        }
        if settings.github_token:
            self.headers["Authorization"] = f"Bearer {settings.github_token}"

        self.remaining: int | None = None
        self.limit: int | None = None
        self.reset_epoch: int | None = None
        self.last_request_monotonic = 0.0

    @property
    def configured(self) -> bool:
        return bool(settings.github_token)

    def _govern(self, path: str) -> None:
        if path == "/rate_limit":
            return

        if self.remaining is not None and self.remaining <= settings.rate_hard_floor:
            reset = self.reset_epoch or int(time.time()) + 60
            wait_seconds = max(1, reset - int(time.time()))
            raise RateLimitPaused(
                f"GitHub API budget is at hard floor ({self.remaining}); retry after about {wait_seconds}s"
            )

        if self.remaining is not None and self.remaining <= settings.rate_soft_floor:
            elapsed = time.monotonic() - self.last_request_monotonic
            if elapsed < 0.75:
                time.sleep(0.75 - elapsed)

    def _capture_rate_headers(self, response: httpx.Response) -> None:
        try:
            self.remaining = int(response.headers.get("x-ratelimit-remaining", self.remaining))
        except (TypeError, ValueError):
            pass
        try:
            self.limit = int(response.headers.get("x-ratelimit-limit", self.limit))
        except (TypeError, ValueError):
            pass
        try:
            self.reset_epoch = int(response.headers.get("x-ratelimit-reset", self.reset_epoch))
        except (TypeError, ValueError):
            pass
        self.last_request_monotonic = time.monotonic()

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        self._govern(path)

        for attempt in range(settings.request_retry_limit + 1):
            try:
                async with httpx.AsyncClient(timeout=25) as client:
                    response = await client.request(
                        method,
                        f"{self.base_url}{path}",
                        headers=self.headers,
                        params=params,
                        json=payload,
                    )

                self._capture_rate_headers(response)

                if response.status_code in {403, 429}:
                    retry_after = response.headers.get("retry-after")
                    if attempt >= settings.request_retry_limit:
                        response.raise_for_status()
                    delay = int(retry_after) if retry_after and retry_after.isdigit() else min(60, 2 ** attempt * 2)
                    await asyncio.sleep(delay)
                    continue

                response.raise_for_status()
                if response.status_code == 204:
                    return {"ok": True}
                return response.json()
            except httpx.HTTPError:
                if attempt >= settings.request_retry_limit:
                    raise
                await asyncio.sleep(min(30, 2 ** attempt))

        raise RuntimeError("GitHub request failed")

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return await self._request("GET", path, params=params)

    async def post(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        return await self._request("POST", path, payload=payload)

    async def profile(self) -> dict[str, Any]:
        return await self.get("/user")

    async def rate_limit(self) -> dict[str, Any]:
        return await self.get("/rate_limit")

    async def repositories(self, page: int = 1) -> list[dict[str, Any]]:
        return await self.get(
            "/user/repos",
            {
                "visibility": "all",
                "affiliation": "owner,collaborator,organization_member",
                "per_page": 100,
                "page": page,
                "sort": "updated",
                "direction": "desc",
            },
        )

    async def open_prs(self) -> dict[str, Any]:
        return await self.get("/search/issues", {"q": "is:open is:pr user:@me", "per_page": 1})

    async def open_issues(self) -> dict[str, Any]:
        return await self.get("/search/issues", {"q": "is:open is:issue user:@me", "per_page": 1})

    async def recent_commits(self, full_name: str) -> list[dict[str, Any]]:
        return await self.get(f"/repos/{full_name}/commits", {"per_page": 10})

    async def recent_releases(self, full_name: str) -> list[dict[str, Any]]:
        return await self.get(f"/repos/{full_name}/releases", {"per_page": 5})

    async def recent_workflow_runs(self, full_name: str) -> list[dict[str, Any]]:
        data = await self.get(f"/repos/{full_name}/actions/runs", {"per_page": 10})
        return data.get("workflow_runs", [])

    async def recent_issues_and_prs(self, full_name: str) -> list[dict[str, Any]]:
        return await self.get(
            f"/repos/{full_name}/issues",
            {"state": "all", "sort": "updated", "direction": "desc", "per_page": 20},
        )

    async def create_issue(self, full_name: str, title: str, body: str = "") -> dict[str, Any]:
        return await self.post(
            f"/repos/{full_name}/issues",
            {"title": title, "body": body},
        )

    async def create_pull_request(
        self, full_name: str, title: str, head: str, base: str, body: str = ""
    ) -> dict[str, Any]:
        return await self.post(
            f"/repos/{full_name}/pulls",
            {"title": title, "head": head, "base": base, "body": body},
        )

    async def merge_pull_request(
        self, full_name: str, number: int, merge_method: str = "merge"
    ) -> dict[str, Any]:
        return await self._request(
            "PUT",
            f"/repos/{full_name}/pulls/{number}/merge",
            payload={"merge_method": merge_method},
        )

    async def rerun_failed_jobs(self, full_name: str, run_id: int) -> dict[str, Any]:
        return await self.post(f"/repos/{full_name}/actions/runs/{run_id}/rerun-failed-jobs")
