# GitHub Monitor

A privacy-conscious dashboard for monitoring GitHub repositories, activity, issues, pull requests, commits, Actions, and API health.

## Direction

- Account-wide repository discovery through authenticated GitHub API access.
- Read-only monitoring by default.
- Dashboard-first UI with clear repository health and activity signals.
- API-aware polling, caching, pagination, and rate-limit protection.
- Sensitive credentials stay server-side and out of source control.

## Planned architecture

```
GitHub API
   |
   v
API client + cache
   |
   +--> repository snapshots
   +--> activity timeline
   +--> issues / pull requests
   +--> Actions / checks
   +--> rate-limit telemetry
   |
   v
Dashboard API
   |
   v
Web UI
```

## MVP screens

1. Overview
2. Repositories
3. Activity
4. Pull requests & issues
5. Actions / CI
6. Repository detail
7. Settings / connection health

## Security

Never commit `.env`, personal access tokens, or secrets. Use server-side environment variables.

## API considerations

GitHub documents 5,000 requests/hour as the general primary REST API limit for authenticated users, with additional restrictions for search and secondary limits. The application therefore needs caching, incremental synchronization, pagination, and backoff instead of aggressive polling.

## Status

Foundation initialized. Next steps are the application scaffold, GitHub client, persistence/cache layer, and dashboard UI.
