from fastapi import FastAPI, HTTPException

from .github_client import GitHubClient
from .settings import settings

app = FastAPI(title="GitHub Monitor API", version="0.3.0")
github = GitHubClient()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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


@app.get("/api/v1/repositories")
async def repositories() -> dict:
    if not github.configured:
        raise HTTPException(status_code=503, detail="Configure GITHUB_TOKEN first")

    all_repos: list[dict] = []
    page = 1

    while True:
        batch = await github.repositories(page)
        all_repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    return {
        "count": len(all_repos),
        "repositories": all_repos,
    }


@app.get("/api/v1/overview")
async def overview() -> dict:
    if not github.configured:
        return {
            "repositories": 0,
            "open_pull_requests": 0,
            "open_issues": 0,
            "failing_checks": 0,
            "sync": "not_connected",
        }

    try:
        repos = await repositories()
        rate = await github.rate_limit()
        core = rate.get("resources", {}).get("core", {})
        prs = await github.open_prs()
        issues = await github.open_issues()

        return {
            "repositories": repos["count"],
            "open_pull_requests": prs.get("total_count", 0),
            "open_issues": issues.get("total_count", 0),
            "failing_checks": 0,
            "sync": "live",
            "poll_interval_seconds": settings.poll_interval_seconds,
            "rate_limit": core,
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GitHub sync failed: {exc}") from exc
