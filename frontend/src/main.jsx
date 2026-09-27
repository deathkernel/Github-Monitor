import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const tabs = ["Overview", "Repositories", "Activity"];

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail || "Request failed");
  return body;
}

function Stat({ label, value, note, tone = "" }) {
  return <div className="stat">
    <div className="stat-top"><span>{label}</span><i className={tone} /></div>
    <div className="stat-value">{value}</div>
    <div className="stat-note">{note}</div>
  </div>;
}

function App() {
  const [tab, setTab] = useState("Overview");
  const [connection, setConnection] = useState(null);
  const [overview, setOverview] = useState(null);
  const [repos, setRepos] = useState([]);
  const [events, setEvents] = useState([]);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [selectedRepo, setSelectedRepo] = useState(null);

  const load = async (withSync = false) => {
    try {
      setError("");
      setBusy(true);
      if (withSync) await api("/api/v1/sync", { method: "POST" });
      const [c, o, r, e] = await Promise.all([
        api("/api/v1/connection"),
        api("/api/v1/overview"),
        api("/api/v1/repositories?limit=500"),
        api("/api/v1/events?limit=100"),
      ]);
      setConnection(c);
      setOverview(o);
      setRepos(r.repositories || []);
      setEvents(e.events || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    load();
    const id = setInterval(() => load(false), 30000);
    return () => clearInterval(id);
  }, []);

  const filteredRepos = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return repos;
    return repos.filter((r) =>
      r.full_name.toLowerCase().includes(q) ||
      (r.description || "").toLowerCase().includes(q) ||
      (r.language || "").toLowerCase().includes(q)
    );
  }, [repos, query]);

  const core = connection?.rate_limit;
  const usage = core?.limit ? Math.round(((core.limit - core.remaining) / core.limit) * 100) : 0;
  const syncLabel = busy ? "Syncing…" : overview?.sync === "live" ? "Live" : "Waiting";

  const openRepo = async (repo) => {
    try {
      const detail = await api("/api/v1/repositories/" + encodeURIComponent(repo.full_name));
      setSelectedRepo(detail);
    } catch (err) {
      setError(err.message);
    }
  };

  return <div className="app">
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-symbol">⌁</div>
        <div><strong>GitHub Monitor</strong><span>account control room</span></div>
      </div>
      <div className="nav-title">MONITOR</div>
      <nav>{tabs.map((name) => <button key={name} className={tab === name ? "nav-active" : ""} onClick={() => setTab(name)}>{name}</button>)}</nav>
      <div className="side-footer">
        <div className="connection-card">
          <span className={"status-dot " + (connection?.connected ? "online" : "")} />
          <div><span>GitHub</span><strong>{connection?.connected ? "@" + connection.login : "Not connected"}</strong></div>
        </div>
        <div className="read-only">READ-ONLY MONITOR</div>
      </div>
    </aside>

    <main className="main">
      <header className="header">
        <div>
          <span className="eyebrow">ACCOUNT-WIDE TELEMETRY</span>
          <h1>{tab === "Overview" ? "GitHub overview" : tab}</h1>
          <p>{tab === "Overview" ? "Repositories, change activity, CI signals and API health in one place." : "Live data from your local monitoring cache."}</p>
        </div>
        <div className="header-actions">
          <span className="sync-pill"><i className="status-dot online" /> {syncLabel}</span>
          <button className="primary" onClick={() => load(true)} disabled={busy}>{busy ? "Syncing…" : "Sync now"}</button>
        </div>
      </header>

      {error && <div className="alert"><strong>Monitor error</strong><span>{error}</span><button onClick={() => setError("")}>×</button></div>}

      {tab === "Overview" && <Overview overview={overview} repos={repos} events={events} core={core} usage={usage} onRepo={openRepo} />}
      {tab === "Repositories" && <Repositories repos={filteredRepos} total={repos.length} query={query} setQuery={setQuery} onRepo={openRepo} />}
      {tab === "Activity" && <Activity events={events} />}

      {selectedRepo && <RepoDrawer repo={selectedRepo} onClose={() => setSelectedRepo(null)} />}
    </main>
  </div>;
}

function Overview({ overview, repos, events, core, usage, onRepo }) {
  const recentRepos = repos.slice(0, 8);
  return <section className="page">
    <div className="stats">
      <Stat label="Repositories" value={overview?.repositories ?? "—"} note="account-wide inventory" />
      <Stat label="My open PRs" value={overview?.open_pull_requests ?? "—"} note="open pull requests" tone="amber" />
      <Stat label="My open issues" value={overview?.open_issues ?? "—"} note="open issues" tone="violet" />
      <Stat label="API used" value={core ? usage + "%" : "—"} note={core ? core.remaining + " requests remaining" : "waiting for token"} tone="green" />
    </div>

    <div className="dashboard-grid">
      <section className="panel span-2">
        <PanelHead title="Repository health" sub="Recently updated repositories in the monitor cache." action={<button className="link-button">All repositories →</button>} />
        <div className="repo-table">
          {recentRepos.map((r) => <RepoRow key={r.id} repo={r} onClick={() => onRepo(r)} />)}
          {!recentRepos.length && <Empty title="No repositories synced" text="Add GITHUB_TOKEN to backend/.env and press Sync now." />}
        </div>
      </section>

      <section className="panel">
        <PanelHead title="API health" sub="Authenticated REST API budget." />
        <div className="meter">
          <div className="meter-number">{core?.remaining ?? "—"}</div>
          <div className="meter-track"><div className="meter-fill" style={{ width: core?.limit ? Math.max(3, core.remaining / core.limit * 100) + "%" : "0%" }} /></div>
          <div className="meter-meta"><span>remaining</span><strong>{core?.limit ?? "—"} total</strong></div>
        </div>
      </section>

      <section className="panel">
        <PanelHead title="Sync engine" sub="Background refresh with local persistence." />
        <div className="kv"><span>Status</span><strong>{overview?.sync ?? "Waiting"}</strong><span>Last sync</span><strong>{formatDate(overview?.last_sync)}</strong><span>Interval</span><strong>{overview?.poll_interval_seconds ?? 300}s</strong><span>Detail depth</span><strong>{overview?.detail_repo_limit ?? 15} repos</strong></div>
      </section>

      <section className="panel span-2">
        <PanelHead title="Activity timeline" sub="Commits, releases and workflow runs collected by the monitor." />
        <ActivityList events={events.slice(0, 8)} />
      </section>
    </div>
  </section>;
}

function Repositories({ repos, total, query, setQuery, onRepo }) {
  return <section className="page">
    <div className="toolbar"><div><strong>{total}</strong><span> repositories cached</span></div><input placeholder="Search name, language or description…" value={query} onChange={(e) => setQuery(e.target.value)} /></div>
    <section className="panel">
      <div className="repo-table full">
        {repos.map((r) => <RepoRow key={r.id} repo={r} onClick={() => onRepo(r)} />)}
        {!repos.length && <Empty title="Nothing matched" text="Try a different search." />}
      </div>
    </section>
  </section>;
}

function Activity({ events }) {
  return <section className="page">
    <section className="panel">
      <PanelHead title="Full activity stream" sub={events.length + " events currently stored in the local monitor database."} />
      <ActivityList events={events} />
    </section>
  </section>;
}

function RepoRow({ repo, onClick }) {
  const visibility = repo.private ? "Private" : "Public";
  return <button className="repo-row" onClick={onClick}>
    <div className="repo-avatar">{repo.archived ? "A" : repo.fork ? "F" : "R"}</div>
    <div className="repo-main"><strong>{repo.full_name}</strong><span>{repo.language || "No language"} · ★ {repo.stars} · forks {repo.forks}</span></div>
    <div className="repo-health"><span className={"badge " + (repo.archived ? "muted" : "")}>{repo.archived ? "Archived" : visibility}</span><small>{formatDate(repo.updated_at)}</small></div>
  </button>;
}

function ActivityList({ events }) {
  if (!events.length) return <Empty title="No activity collected yet" text="Run a sync to populate commits, releases and workflow events." />;
  return <div className="activity-list">{events.map((e) => <a className="activity-row" href={e.url || "#"} target="_blank" rel="noreferrer" key={e.id}>
    <div className={"event-icon " + e.type}>{eventSymbol(e.type)}</div>
    <div><strong>{e.title}</strong><span>{e.repo_full_name} · {e.actor || "GitHub"} · {formatDate(e.created_at)}</span></div>
  </a>)}</div>;
}

function RepoDrawer({ repo, onClose }) {
  return <div className="overlay" onClick={onClose}>
    <aside className="drawer" onClick={(e) => e.stopPropagation()}>
      <button className="drawer-close" onClick={onClose}>×</button>
      <span className="eyebrow">REPOSITORY</span>
      <h2>{repo.full_name}</h2>
      <p>{repo.description || "No description provided."}</p>
      <div className="drawer-stats"><div><strong>{repo.stars}</strong><span>stars</span></div><div><strong>{repo.forks}</strong><span>forks</span></div><div><strong>{repo.open_issues}</strong><span>open issues*</span></div></div>
      <div className="kv"><span>Language</span><strong>{repo.language || "—"}</strong><span>Default branch</span><strong>{repo.default_branch || "—"}</strong><span>Visibility</span><strong>{repo.private ? "Private" : "Public"}</strong><span>Last GitHub update</span><strong>{formatDate(repo.updated_at)}</strong></div>
      <a className="primary wide" href={"https://github.com/" + repo.full_name} target="_blank" rel="noreferrer">Open on GitHub ↗</a>
      <div className="drawer-note">* GitHub repository metadata may include issue/PR counts in its aggregate field. Detailed PR/issue analytics are handled separately.</div>
      <h3>Recent monitored events</h3>
      <ActivityList events={repo.events || []} />
    </aside>
  </div>;
}

function PanelHead({ title, sub, action }) {
  return <div className="panel-head"><div><h2>{title}</h2><p>{sub}</p></div>{action}</div>;
}

function Empty({ title, text }) {
  return <div className="empty"><strong>{title}</strong><span>{text}</span></div>;
}

function formatDate(value) {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function eventSymbol(type) {
  return type === "commit" ? "↗" : type === "release" ? "◆" : type === "workflow" ? "⚙" : "•";
}

createRoot(document.getElementById("root")).render(<App />);
