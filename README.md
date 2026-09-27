# GitHub Monitor

A local GitHub account control room for repository monitoring, change intelligence, analytics, alerts, history and explicitly controlled GitHub actions.

## Implemented

### Monitoring
- Account-wide repository discovery with pagination.
- Local SQLite state and historical snapshots.
- Background polling plus a durable SQLite-backed job queue.
- Manual sync endpoint.
- Recent commits, releases, Actions workflow runs, issues and pull requests for detail-scoped repositories.
- Rate-limit telemetry with soft throttling, hard-floor pausing, retry/backoff and serialized request behavior.

### Change intelligence
- Repository metadata change detection.
- New commit, release and work-item detection.
- Workflow failure detection.
- Persistent change records with acknowledgement.
- Warning/critical alert records from actionable changes.
- Optional outbound webhook notification delivery.

### Analytics
- 7-day and 30-day activity windows.
- Stale repository exposure.
- Public/private/archived breakdown.
- Stars and forks totals.
- Language distribution.
- Activity concentration.
- CI reliability over the last 7 days.
- Event mix.
- Historical daily repository snapshots.
- Transparent per-repository attention heuristics.
- Repository detail history, changes and events.

### Command center
- Create issue.
- Create pull request.
- Merge pull request.
- Re-run failed workflow jobs.
- Local action audit log.

Mutating actions are disabled by default. Enable them only when the GitHub token has the matching write permissions. Creating issues requires repository Issues write permission, and re-running workflows requires Actions write permission for fine-grained tokens.

## Architecture

~~~text
GitHub REST API
      |
      v
Rate-aware GitHub client
      |
      v
Durable job queue
      |
      v
Sync + change detection
      |
      +--> repositories
      +--> history
      +--> events
      +--> changes
      +--> alerts
      +--> notifications
      +--> action audit
      |
      v
FastAPI
      |
      v
React + Vite command center
~~~

## Local setup

### Backend
~~~powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
~~~

Create backend/.env:

~~~env
GITHUB_TOKEN=github_pat_your_token_here
GITHUB_API_URL=https://api.github.com
POLL_INTERVAL_SECONDS=300
DETAIL_REPO_LIMIT=15
DATABASE_URL=sqlite:///./data/github_monitor.db
RATE_SOFT_FLOOR=500
RATE_HARD_FLOOR=100
REQUEST_RETRY_LIMIT=3
NOTIFICATION_WEBHOOK_URL=
NOTIFICATION_MIN_SEVERITY=warning
ENABLE_WRITE_ACTIONS=false
JOB_LEASE_SECONDS=900
~~~

Start FastAPI:
~~~powershell
python -m uvicorn app.main:app --reload
~~~

Health endpoint: http://127.0.0.1:8000/health

### Frontend
~~~powershell
cd frontend
npm install
npm run dev
~~~

Open http://127.0.0.1:5173

## API

Monitoring: /health, /api/v1/connection, /api/v1/sync, /api/v1/overview, /api/v1/repositories, /api/v1/events
Intelligence: /api/v1/analytics, /api/v1/changes, /api/v1/alerts, /api/v1/history, /api/v1/notifications, /api/v1/jobs
Commands: /api/v1/commands, /api/v1/actions/create-issue, /api/v1/actions/create-pr, /api/v1/actions/merge-pr, /api/v1/actions/rerun-failed-jobs, /api/v1/audit

## API efficiency
GitHub recommends authenticated conditional requests, avoiding unnecessary concurrency, and backoff when rate limits are encountered. The monitor uses serialized sync work, local persistence, a request rate governor and retry/backoff.

## Security
- Never commit backend/.env or a GitHub token.
- Use the minimum token permissions required.
- Keep ENABLE_WRITE_ACTIONS=false for monitoring-only deployments.
- Treat notification webhook URLs as secrets.