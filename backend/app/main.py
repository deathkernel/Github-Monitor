from fastapi import FastAPI

app = FastAPI(title="GitHub Monitor API", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/overview")
def overview() -> dict:
    return {
        "repositories": 0,
        "open_pull_requests": 0,
        "open_issues": 0,
        "failing_checks": 0,
        "sync": "not_started",
    }
