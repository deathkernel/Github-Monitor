import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

function Stat({ label, value, hint }) {
  return <div className="stat"><div className="stat-label">{label}</div><div className="stat-value">{value}</div><div className="stat-hint">{hint}</div></div>;
}

function App() {
  const [connection, setConnection] = useState(null);
  const [overview, setOverview] = useState(null);
  const [repos, setRepos] = useState([]);
  const [error, setError] = useState("");

  const load = async () => {
    try {
      setError("");
      const [c, o, r] = await Promise.all([
        fetch("/api/v1/connection").then((x) => x.json()),
        fetch("/api/v1/overview").then((x) => x.json()),
        fetch("/api/v1/repositories").then((x) => x.ok ? x.json() : { repositories: [] }),
      ]);
      setConnection(c);
      setOverview(o);
      setRepos(r.repositories || []);
    } catch (e) {
      setError("Backend unavailable. Start FastAPI on port 8000.");
    }
  };

  useEffect(() => { load(); }, []);

  const connected = connection?.connected;
  const core = connection?.rate_limit || overview?.rate_limit;
  const usedPct = core?.limit ? Math.round(((core.limit - core.remaining) / core.limit) * 100) : 0;

  return <main className="shell">
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark">◉</span> GitHub Monitor</div>
      <nav><a className="active">Overview</a><a>Repositories</a><a>Activity</a><a>Issues & PRs</a><a>Actions</a><a>Settings</a></nav>
      <div className="connection"><span className={"dot " + (connected ? "live" : "")} /> GitHub connection<strong>{connected ? "@" + connection.login : "Not connected"}</strong></div>
    </aside>

    <section className="content">
      <header className="topbar">
        <div><div className="eyebrow">ACCOUNT MONITOR</div><h1>GitHub overview</h1><p>One control room for repositories, activity, CI and API health.</p></div>
        <button className="primary" onClick={load}>{connected ? "Refresh" : "Check connection"}</button>
      </header>

      {error && <div className="alert">{error}</div>}

      <section className="stats">
        <Stat label="Repositories" value={overview?.repositories ?? "—"} hint="Account-wide inventory" />
        <Stat label="Open PRs" value={overview?.open_pull_requests ?? "—"} hint="Across accessible repos" />
        <Stat label="Open issues" value={overview?.open_issues ?? "—"} hint="Across accessible repos" />
        <Stat label="API usage" value={core ? usedPct + "%" : "—"} hint={core ? core.remaining + " requests remaining" : "Waiting for auth"} />
      </section>

      <section className="grid">
        <div className="panel large">
          <div className="panel-head"><div><h2>Repository health</h2><p>Recently updated repositories visible to this token.</p></div><button className="ghost" onClick={load}>Refresh</button></div>
          <div className="repo-list">
            {repos.length ? repos.slice(0, 8).map((repo) => <div className="repo-row" key={repo.id}>
              <div className="repo-icon">{repo.private ? "PR" : "PB"}</div>
              <div><strong>{repo.full_name}</strong><span>{repo.language || "No language"} · ★ {repo.stargazers_count || 0} · updated {new Date(repo.updated_at).toLocaleDateString()}</span></div>
              <span className="badge muted">{repo.archived ? "Archived" : repo.private ? "Private" : "Public"}</span>
            </div>) : <div className="empty">No repositories returned yet. Configure GITHUB_TOKEN on the backend.</div>}
          </div>
        </div>

        <div className="panel">
          <div className="panel-head"><div><h2>API health</h2><p>Authenticated REST API budget.</p></div></div>
          <div className="api-card"><div className="ring">{core ? core.remaining : "—"}</div><div><strong>{core ? "Requests remaining" : "Not connected"}</strong><span>{core ? "of " + core.limit + " in the current window" : "Rate limit appears after authentication."}</span></div></div>
        </div>

        <div className="panel large">
          <div className="panel-head"><div><h2>Activity timeline</h2><p>Next module: commits, releases, workflow events and change detection.</p></div></div>
          <div className="empty">{connected ? "GitHub is connected. Activity ingestion is next." : "Connect GitHub to start collecting activity."}</div>
        </div>

        <div className="panel">
          <div className="panel-head"><div><h2>Sync engine</h2><p>Cache-aware polling.</p></div></div>
          <div className="sync"><span>State</span><strong>{overview?.sync ?? "Idle"}</strong><span>Interval</span><strong>{overview?.poll_interval_seconds ?? 300}s</strong><span>Mode</span><strong>Read-only</strong></div>
        </div>
      </section>
    </section>
  </main>;
}

createRoot(document.getElementById("root")).render(<App />);
