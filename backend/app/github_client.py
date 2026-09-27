from typing import Any

import httpx

from .settings import settings


class GitHubClient:
    def __init__(self) -> None:
        self.base_url = settings.github_api_url.rstrip("/")
        self.headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "github-monitor",
        }
        if settings.github_token:
            self.headers["Authorization"] = f"Bearer {settings.github_token}"

    @property
    def configured(self) -> bool:
        return bool(settings.github_token)

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.get(
                f"{self.base_url}{path}",
                headers=self.headers,
                params=params,
            )
            response.raise_for_status()
            return response.json()

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
