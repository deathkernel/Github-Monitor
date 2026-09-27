import React from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const repos = [
  { name: "No repositories synced", detail: "Connect GitHub to populate this view." },
];

function Stat({ label, value, hint }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      <div className="stat-hint">{hint}</div>
    </div>
  );
}

function App() {
  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">◉</span> GitHub Monitor</div>
        <nav>
          <a className="active">Overview</a>
          <a>Repositories</a>
          <a>Activity</a>
          <a>Issues & PRs</a>
          <a>Actions</a>
          <a>Settings</a>
        </nav>
        <div className="connection">
          <span className="dot" /> GitHub connection
          <strong>Not connected</strong>
        </div>
      </aside>

      <section className="content">
        <header className="topbar">
          <div>
            <div className="eyebrow">ACCOUNT MONITOR</div>
            <h1>GitHub overview</h1>
            <p>Track your repositories and development activity from one control room.</p>
          </div>
          <button className="primary">Connect GitHub</button>
        </header>

        <section className="stats">
          <Stat label="Repositories" value="—" hint="Awaiting sync" />
          <Stat label="Open PRs" value="—" hint="Across all repos" />
          <Stat label="Open issues" value="—" hint="Across all repos" />
          <Stat label="CI / checks" value="—" hint="Latest status" />
        </section>

        <section className="grid">
          <div className="panel large">
            <div className="panel-head">
              <div>
                <h2>Repository health</h2>
                <p>Latest monitored state across your account.</p>
              </div>
              <button className="ghost">View all</button>
            </div>
            <div className="repo-list">
              {repos.map((repo) => (
                <div className="repo-row" key={repo.name}>
                  <div className="repo-icon">GH</div>
                  <div>
                    <strong>{repo.name}</strong>
                    <span>{repo.detail}</span>
                  </div>
                  <span className="badge muted">Pending</span>
                </div>
              ))}
            </div>
          </div>

          <div className="panel">
            <div className="panel-head">
              <div>
                <h2>API health</h2>
                <p>Authentication and rate-limit telemetry.</p>
              </div>
            </div>
            <div className="api-card">
              <div className="ring">—</div>
              <div><strong>Not connected</strong><span>Rate limit will appear after authentication.</span></div>
            </div>
          </div>

          <div className="panel large">
            <div className="panel-head">
              <div>
                <h2>Activity timeline</h2>
                <p>Commits, PRs, issues, releases and workflow events.</p>
              </div>
            </div>
            <div className="empty">Connect GitHub to start collecting activity.</div>
          </div>

          <div className="panel">
            <div className="panel-head">
              <div>
                <h2>Sync engine</h2>
                <p>Incremental polling with cache-aware API usage.</p>
              </div>
            </div>
            <div className="sync">
              <span>State</span><strong>Idle</strong>
              <span>Last sync</span><strong>—</strong>
              <span>Next sync</span><strong>—</strong>
            </div>
          </div>
        </section>
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
