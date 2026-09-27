# GitHub Monitor

A local, read-only control room for monitoring an authenticated GitHub account.

## Implemented

- Account-wide repository discovery with pagination.
- Local SQLite cache for repository snapshots and activity events.
- Background polling with a configurable interval.
- Manual sync endpoint.
- Recent commits, releases, workflow runs, issues and pull requests for the most recently updated repositories.
- GitHub REST API rate-limit telemetry.
- Open pull requests and open issues authored by the connected account.
- Repository search, repository detail drawer and activity timeline.
- Read-only design: the application does not mutate GitHub resources.

## Architecture

~~~text
GitHub REST API
      |
      v
GitHub API client
      |
      v
SyncService
      |
      +--> repositories
      +--> commits / releases
      +--> workflow runs
      +--> issues / pull requests
      |
      v
SQLite cache
      |
      v
FastAPI
      |
      v
React + Vite dashboard
~~~

## Local setup

### Backend

From the repository root:

~~~powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
~~~

Create backend/.env with your read-only GitHub token:

~~~env
GITHUB_TOKEN=github_pat_your_token_here
GITHUB_API_URL=https://api.github.com
POLL_INTERVAL_SECONDS=300
DETAIL_REPO_LIMIT=15
DATABASE_URL=sqlite:///./data/github_monitor.db
~~~

Start FastAPI:

~~~powershell
uvicorn app.main:app --reload
~~~

Health endpoint: http://localhost:8000/health

### Frontend

Open a second terminal:

~~~powershell
cd frontend
npm install
npm run dev
~~~

Open the Vite URL, normally http://localhost:5173

The Vite development server proxies /api requests to FastAPI on port 8000.

## Monitoring strategy

The monitor separates inventory sync from detail sync. It discovers all repositories, then collects detailed activity for the DETAIL_REPO_LIMIT most recently updated repositories. This keeps API usage predictable while retaining full repository inventory.

Increase DETAIL_REPO_LIMIT only when the account size and API budget justify it.

## Security

Never commit backend/.env or a GitHub token. The root .gitignore excludes .env files and local database data.

Use the minimum GitHub token permissions required for monitoring. The application itself only performs read operations against GitHub.

## API

- GET /api/v1/connection
- POST /api/v1/sync
- GET /api/v1/overview
- GET /api/v1/repositories
- GET /api/v1/repositories/{owner}/{repo}
- GET /api/v1/events
- GET /health

## Next layer

Change diffing, alert rules, notifications, historical charts, deeper repository drill-downs, and durable job scheduling are the logical next modules.