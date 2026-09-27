import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const tabs = ["Overview", "Repositories", "Activity", "Analytics", "Changes", "Commands", "Audit"];

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const type = response.headers.get("content-type") || "";
  const raw = await response.text();
  if (!type.includes("application/json")) throw new Error("Backend returned non-JSON. Check FastAPI on http://127.0.0.1:8000.");
  const body = JSON.parse(raw);
  if (!response.ok) throw new Error(body.detail || "Request failed");
  return body;
}

function Stat({ label, value, note, tone = "" }) {
  return <div className="stat"><div className="stat-top"><span>{label}</span><i className={tone} /></div><div className="stat-value">{value}</div><div className="stat-note">{note}</div></div>;
}

function App() {
  const [tab, setTab] = useState("Overview");
  const [connection, setConnection] = useState(null);
  const [overview, setOverview] = useState(null);
  const [repos, setRepos] = useState([]);
  const [events, setEvents] = useState([]);
  const [analytics, setAnalytics] = useState(null);
  const [changes, setChanges] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [history, setHistory] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [audit, setAudit] = useState([]);
  const [commands, setCommands] = useState(null);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [selectedRepo, setSelectedRepo] = useState(null);

  const load = async (runSync = false) => {
    try {
      setError("");
      setBusy(true);
      if (runSync) await api("/api/v1/sync", { method: "POST" });
      const results = await Promise.all([
        api("/api/v1/connection"),
        api("/api/v1/overview"),
        api("/api/v1/repositories?limit=500"),
        api("/api/v1/events?limit=120"),
        api("/api/v1/analytics"),
        api("/api/v1/changes?limit=100"),
        api("/api/v1/alerts?limit=100"),
        api("/api/v1/history?days=30"),
        api("/api/v1/jobs?limit=50"),
        api("/api/v1/audit?limit=50"),
        api("/api/v1/commands"),
      ]);
      const [c, o, r, e, a, ch, al, h, j, au, cmd] = results;
      setConnection(c); setOverview(o); setRepos(r.repositories || []); setEvents(e.events || []);
      setAnalytics(a); setChanges(ch.changes || []); setAlerts(al.alerts || []);
      setHistory(h.history || []); setJobs(j.jobs || []); setAudit(au.audit || []); setCommands(cmd);
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
    return repos.filter(r => r.full_name.toLowerCase().includes(q) || (r.description || "").toLowerCase().includes(q) || (r.language || "").toLowerCase().includes(q));
  }, [repos, query]);

  const core = connection?.rate_limit;
  const usage = core?.limit ? Math.round(((core.limit - core.remaining) / core.limit) * 100) : 0;

  const openRepo = async (repo) => {
    try { setSelectedRepo(await api("/api/v1/repositories/" + encodeURIComponent(repo.full_name))); }
    catch (err) { setError(err.message); }
  };

  return <div className="app">
    <aside className="sidebar">
      <div className="brand"><div className="brand-symbol">⌁</div><div><strong>GitHub Monitor</strong><span>account control room</span></div></div>
      <div className="nav-title">MONITOR</div>
      <nav>{tabs.map(name => <button key={name} className={tab === name ? "nav-active" : ""} onClick={() => setTab(name)}>{name}</button>)}</nav>
      <div className="side-footer"><div className="connection-card"><span className={"status-dot " + (connection?.connected ? "online" : "")} /><div><span>GitHub</span><strong>{connection?.connected ? "@" + connection.login : "Not connected"}</strong></div></div><div className="read-only">{commands?.write_actions_enabled ? "WRITE ACTIONS ENABLED" : "READ-ONLY DEFAULT"}</div></div>
    </aside>

    <main className="main">
      <header className="header">
        <div><span className="eyebrow">ACCOUNT-WIDE TELEMETRY</span><h1>{tab === "Overview" ? "GitHub overview" : tab}</h1><p>Monitor state, change intelligence, history and controlled GitHub actions from one local control room.</p></div>
        <div className="header-actions"><span className="sync-pill"><i className={"status-dot " + (connection?.connected ? "online" : "")} /> {busy ? "Working…" : overview?.sync === "live" ? "Live" : "Waiting"}</span><button className="primary" onClick={() => load(true)} disabled={busy}>{busy ? "Syncing…" : "Sync now"}</button></div>
      </header>

      {error && <div className="alert"><strong>Monitor</strong><span>{error}</span><button onClick={() => setError("")}>×</button></div>}

      {tab === "Overview" && <Overview overview={overview} repos={repos} events={events} core={core} usage={usage} changes={changes} alerts={alerts} onRepo={openRepo} />}
      {tab === "Repositories" && <Repositories repos={filteredRepos} total={repos.length} query={query} setQuery={setQuery} onRepo={openRepo} />}
      {tab === "Activity" && <Activity events={events} />}
      {tab === "Analytics" && <Analytics analytics={analytics} history={history} />}
      {tab === "Changes" && <Changes changes={changes} alerts={alerts} reload={() => load(false)} />}
      {tab === "Commands" && <Commands enabled={Boolean(commands?.write_actions_enabled)} onDone={() => load(false)} />}
      {tab === "Audit" && <Audit rows={audit} jobs={jobs} />}

      {selectedRepo && <RepoDrawer repo={selectedRepo} onClose={() => setSelectedRepo(null)} />}
    </main>
  </div>;
}

function Overview({ overview, repos, events, core, usage, changes, alerts, onRepo }) {
  return <section className="page">
    <div className="stats">
      <Stat label="Repositories" value={overview?.repositories ?? "—"} note="account-wide inventory" />
      <Stat label="My open PRs" value={overview?.open_pull_requests ?? "—"} note="open pull requests" tone="amber" />
      <Stat label="My open issues" value={overview?.open_issues ?? "—"} note="open issues" tone="violet" />
      <Stat label="Recent CI failures" value={overview?.recent_ci_failures ?? "—"} note="last 7 days" tone="red" />
      <Stat label="API used" value={core ? usage + "%" : "—"} note={core ? core.remaining + " remaining" : "waiting for token"} tone="green" />
    </div>
    <div className="dashboard-grid">
      <section className="panel span-2"><PanelHead title="Repository health" sub="Recently updated repositories in the monitor cache." /><div className="repo-table">{repos.slice(0,8).map(r => <RepoRow key={r.id} repo={r} onClick={() => onRepo(r)} />)}{!repos.length && <Empty title="No repositories synced" text="Configure GITHUB_TOKEN and run Sync now." />}</div></section>
      <section className="panel"><PanelHead title="Attention" sub="Newest warning/critical change records." /><div className="mini-list">{alerts.slice(0,6).map(a => <div className="mini-row" key={a.id}><span className={"severity " + a.severity}>{a.severity}</span><div><strong>{a.title}</strong><span>{a.repo_full_name || "account"} · {formatDate(a.created_at)}</span></div></div>)}{!alerts.length && <Empty title="No open alerts" text="The monitor is quiet." />}</div></section>
      <section className="panel"><PanelHead title="Sync engine" sub="Durable job state and local cache." /><div className="kv"><span>Status</span><strong>{overview?.sync ?? "Waiting"}</strong><span>Last sync</span><strong>{formatDate(overview?.last_sync)}</strong><span>Next interval</span><strong>{overview?.poll_interval_seconds ?? 300}s</strong><span>Changes waiting</span><strong>{changes.length}</strong></div></section>
      <section className="panel span-2"><PanelHead title="Recent activity" sub="Events collected from commits, releases, workflows, issues and PRs." /><ActivityList events={events.slice(0,10)} /></section>
    </div>
  </section>;
}

function Repositories({ repos, total, query, setQuery, onRepo }) {
  return <section className="page"><div className="toolbar"><div><strong>{total}</strong><span> repositories cached</span></div><input placeholder="Search name, language or description…" value={query} onChange={e => setQuery(e.target.value)} /></div><section className="panel"><div className="repo-table full">{repos.map(r => <RepoRow key={r.id} repo={r} onClick={() => onRepo(r)} />)}{!repos.length && <Empty title="Nothing matched" text="Try a different search." />}</div></section></section>;
}

function Activity({ events }) { return <section className="page"><section className="panel"><PanelHead title="Full activity stream" sub={events.length + " stored events."} /><ActivityList events={events} /></section></section>; }

function Analytics({ analytics, history }) {
  if (!analytics) return <section className="page"><section className="panel"><Empty title="Analytics not ready" text="Run a sync to populate the analysis layer." /></section></section>;
  const maxLang = Math.max(1, ...(analytics.languages || []).map(x => x.count));
  const maxAct = Math.max(1, ...(analytics.top_activity || []).map(x => x.count));
  const maxHistory = Math.max(1, ...(history || []).map(x => Number(x.stars || 0)));
  return <section className="page"><div className="analysis-grid">
    <section className="panel analysis-hero"><PanelHead title="Portfolio pulse" sub="Cross-repository signals from the local cache." /><div className="pulse-grid"><div><strong>{analytics.active_7d}</strong><span>active 7d</span></div><div><strong>{analytics.active_30d}</strong><span>active 30d</span></div><div><strong>{analytics.stale_30d}</strong><span>stale 30d+</span></div><div><strong>{analytics.stale_90d}</strong><span>stale 90d+</span></div></div><div className="analysis-note"><strong>{analytics.public}</strong> public · <strong>{analytics.private}</strong> private · <strong>{analytics.archived}</strong> archived · <strong>{analytics.total_stars}</strong> stars · <strong>{analytics.total_forks}</strong> forks</div></section>
    <section className="panel"><PanelHead title="CI reliability" sub="Last 7 days." /><div className="ci-rate"><strong>{analytics.workflow_success_rate_7d == null ? "—" : analytics.workflow_success_rate_7d + "%"}</strong><span>{analytics.workflow_runs_7d} workflow events · {analytics.workflow_failures_7d} failures</span></div><div className="meter-track"><div className="meter-fill" style={{width:(analytics.workflow_success_rate_7d ?? 0)+"%"}} /></div></section>
    <section className="panel"><PanelHead title="Language mix" sub="Repository count." /><BarList items={analytics.languages || []} max={maxLang} /></section>
    <section className="panel"><PanelHead title="Activity concentration" sub="Events by repository." /><BarList items={(analytics.top_activity || []).map(x => ({name:x.repo,count:x.count}))} max={maxAct} /></section>
    <section className="panel"><PanelHead title="Historical stars" sub="Daily repository snapshots collected by each sync." /><div className="history-chart">{history.length ? history.map(x => <div className="history-bar" key={x.day} title={x.day + " · " + x.stars + " stars"}><i style={{height: Math.max(4, Number(x.stars || 0) / maxHistory * 100) + "%"}} /><span>{x.day.slice(5)}</span></div>) : <Empty title="No history yet" text="History grows with each sync." />}</div></section>
    <section className="panel"><PanelHead title="Event mix" sub="Stored event types." /><div className="event-mix">{(analytics.events || []).slice(0,8).map(x => <div className="event-mix-row" key={x.type}><span>{x.type.replaceAll("_"," ")}</span><strong>{x.count}</strong></div>)}</div></section>
    <section className="panel span-2"><PanelHead title="Attention queue" sub="Transparent heuristic flags only." /><div className="attention-list">{(analytics.health || []).map(x => <div className="attention-row" key={x.full_name}><div><strong>{x.full_name}</strong><span>{x.flags.length ? x.flags.join(" · ") : "No heuristic flags"}</span></div><div className="attention-score"><span>{x.score >= 80 ? "Stable" : x.score >= 60 ? "Watch" : "Needs attention"}</span><strong>{x.score}</strong></div></div>)}</div></section>
  </div></section>;
}

function BarList({ items, max }) { return <div className="bar-list">{items.map(x => <div className="bar-row" key={x.name}><div><span>{x.name}</span><strong>{x.count}</strong></div><div className="bar-track"><div className="bar-fill" style={{width:(x.count/max*100)+"%"}} /></div></div>)}</div>; }

function Changes({ changes, alerts, reload }) {
  const ack = async id => { await api("/api/v1/changes/" + id + "/ack", {method:"POST"}); reload(); };
  const ackAlert = async id => { await api("/api/v1/alerts/" + id + "/ack", {method:"POST"}); reload(); };
  return <section className="page"><div className="dashboard-grid"><section className="panel span-2"><PanelHead title="Detected changes" sub={changes.length + " unacknowledged changes."} /><div className="change-list">{changes.map(c => <div className="change-row" key={c.id}><div><span className={"severity " + c.severity}>{c.severity}</span><strong>{c.repo_full_name}</strong><span>{c.change_type} · {c.field} · {c.before_value ?? "∅"} → {c.after_value ?? "∅"}</span></div><button className="ghost" onClick={() => ack(c.id)}>Acknowledge</button></div>)}{!changes.length && <Empty title="No unacknowledged changes" text="Nothing new to review." />}</div></section><section className="panel span-2"><PanelHead title="Open alerts" sub="Warning and critical change signals." /><div className="change-list">{alerts.map(a => <div className="change-row" key={a.id}><div><span className={"severity " + a.severity}>{a.severity}</span><strong>{a.title}</strong><span>{a.repo_full_name || "account"} · {a.rule}</span></div><button className="ghost" onClick={() => ackAlert(a.id)}>Acknowledge</button></div>)}{!alerts.length && <Empty title="No open alerts" text="The alert queue is clear." />}</div></section></div></section>;
}

function Commands({ enabled, onDone }) {
  const [form, setForm] = useState({ repo_full_name:"", title:"", body:"", head:"", base:"main", number:"", run_id:"", merge_method:"merge" });
  const [result, setResult] = useState("");
  const update = e => setForm({...form,[e.target.name]:e.target.value});
  const act = async (path, payload) => { try { setResult("Working…"); const r=await api(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)}); setResult(JSON.stringify(r.result || r)); onDone(); } catch(e){ setResult(e.message); } };
  return <section className="page"><section className="panel"><PanelHead title="Command center" sub={enabled ? "Write actions are enabled for this local instance." : "Write actions are intentionally disabled by default."} />
    <div className="command-grid">
      <div className="command-card"><h3>Create issue</h3><input name="repo_full_name" placeholder="owner/repo" value={form.repo_full_name} onChange={update}/><input name="title" placeholder="Issue title" value={form.title} onChange={update}/><textarea name="body" placeholder="Body" value={form.body} onChange={update}/><button className="primary" disabled={!enabled} onClick={()=>act("/api/v1/actions/create-issue",{repo_full_name:form.repo_full_name,title:form.title,body:form.body})}>Create issue</button></div>
      <div className="command-card"><h3>Create pull request</h3><input name="repo_full_name" placeholder="owner/repo" value={form.repo_full_name} onChange={update}/><input name="title" placeholder="PR title" value={form.title} onChange={update}/><input name="head" placeholder="head branch" value={form.head} onChange={update}/><input name="base" placeholder="base branch" value={form.base} onChange={update}/><button className="primary" disabled={!enabled} onClick={()=>act("/api/v1/actions/create-pr",{repo_full_name:form.repo_full_name,title:form.title,head:form.head,base:form.base,body:form.body})}>Create PR</button></div>
      <div className="command-card"><h3>Merge pull request</h3><input name="repo_full_name" placeholder="owner/repo" value={form.repo_full_name} onChange={update}/><input name="number" placeholder="PR number" value={form.number} onChange={update}/><select name="merge_method" value={form.merge_method} onChange={update}><option value="merge">merge</option><option value="squash">squash</option><option value="rebase">rebase</option></select><button className="primary" disabled={!enabled} onClick={()=>act("/api/v1/actions/merge-pr",{repo_full_name:form.repo_full_name,number:Number(form.number),merge_method:form.merge_method})}>Merge PR</button></div>
      <div className="command-card"><h3>Re-run failed jobs</h3><input name="repo_full_name" placeholder="owner/repo" value={form.repo_full_name} onChange={update}/><input name="run_id" placeholder="workflow run ID" value={form.run_id} onChange={update}/><button className="primary" disabled={!enabled} onClick={()=>act("/api/v1/actions/rerun-failed-jobs",{repo_full_name:form.repo_full_name,run_id:Number(form.run_id)})}>Re-run failed jobs</button></div>
    </div>
    {!enabled && <div className="command-warning">To enable these actions, set <code>ENABLE_WRITE_ACTIONS=true</code> and grant the corresponding GitHub token permissions. Creating issues needs Issues: write; re-running workflows needs Actions: write. Merge/PR actions require their applicable repository write permissions. </div>}
    {result && <pre className="command-result">{result}</pre>}
  </section></section>;
}

function Audit({ rows, jobs }) { return <section className="page"><div className="dashboard-grid"><section className="panel span-2"><PanelHead title="Action audit log" sub="Every command-center mutation is recorded locally." /><div className="change-list">{rows.map(r=><div className="change-row" key={r.id}><div><span className={"severity " + (r.status==="success" ? "info":"critical")}>{r.status}</span><strong>{r.action}</strong><span>{r.repo_full_name || "account"} · {r.target || "—"} · {formatDate(r.created_at)}</span></div></div>)}{!rows.length && <Empty title="No actions recorded" text="Read-only monitoring produces no mutation audit entries." />}</div></section><section className="panel span-2"><PanelHead title="Durable jobs" sub="Persistent scheduler state." /><div className="change-list">{jobs.map(j=><div className="change-row" key={j.id}><div><span className={"severity " + (j.status==="done" ? "info" : j.status==="queued" ? "warning":"critical")}>{j.status}</span><strong>#{j.id} · {j.kind}</strong><span>attempts {j.attempts} · {formatDate(j.created_at)} {j.last_error ? "· " + j.last_error : ""}</span></div></div>)}</div></section></div></section>; }

function RepoRow({ repo, onClick }) { return <button className="repo-row" onClick={onClick}><div className="repo-avatar">{repo.archived ? "A" : repo.fork ? "F" : "R"}</div><div className="repo-main"><strong>{repo.full_name}</strong><span>{repo.language || "No language"} · ★ {repo.stars} · forks {repo.forks}</span></div><div className="repo-health"><span className="badge">{repo.archived ? "Archived" : repo.private ? "Private" : "Public"}</span><small>{formatDate(repo.updated_at)}</small></div></button>; }
function ActivityList({ events }) { if(!events.length) return <Empty title="No activity" text="Run a sync to collect activity." />; return <div className="activity-list">{events.map(e=><a className="activity-row" href={e.url || "#"} target="_blank" rel="noreferrer" key={e.id}><div className={"event-icon " + (e.event_type || "unknown")}>{eventSymbol(e.event_type)}</div><div><strong>{e.title}</strong><span>{e.repo_full_name} · {e.actor || "GitHub"} · {formatDate(e.created_at)}</span></div></a>)}</div>; }
function RepoDrawer({ repo, onClose }) { const maxStars=Math.max(1,...(repo.history||[]).map(x=>Number(x.stars||0))); return <div className="overlay" onClick={onClose}><aside className="drawer" onClick={e=>e.stopPropagation()}><button className="drawer-close" onClick={onClose}>×</button><span className="eyebrow">REPOSITORY</span><h2>{repo.full_name}</h2><p>{repo.description || "No description provided."}</p><div className="drawer-stats"><div><strong>{repo.stars}</strong><span>stars</span></div><div><strong>{repo.forks}</strong><span>forks</span></div><div><strong>{repo.open_issues}</strong><span>open issues*</span></div></div><div className="kv"><span>Language</span><strong>{repo.language||"—"}</strong><span>Default branch</span><strong>{repo.default_branch||"—"}</strong><span>Visibility</span><strong>{repo.private?"Private":"Public"}</strong><span>Updated</span><strong>{formatDate(repo.updated_at)}</strong></div><div className="drawer-chart">{(repo.history||[]).slice().reverse().map((x,i)=><i key={i} title={x.day} style={{height:Math.max(6,Number(x.stars||0)/maxStars*100)+"%"}} />)}</div><a className="primary wide" href={"https://github.com/"+repo.full_name} target="_blank" rel="noreferrer">Open on GitHub ↗</a><h3>Recent changes</h3>{(repo.changes||[]).length ? <div className="change-list">{repo.changes.map(c=><div className="change-row" key={c.id}><div><span className={"severity "+c.severity}>{c.severity}</span><strong>{c.change_type}</strong><span>{c.field}: {c.after_value}</span></div></div>)}</div> : <Empty title="No stored changes" text="The monitor has not detected changes yet." />}<h3>Recent events</h3><ActivityList events={repo.events||[]} /></aside></div>; }
function PanelHead({title,sub,action}){return <div className="panel-head"><div><h2>{title}</h2><p>{sub}</p></div>{action}</div>;}
function Empty({title,text}){return <div className="empty"><strong>{title}</strong><span>{text}</span></div>;}
function formatDate(v){if(!v)return "—";const d=new Date(v);return Number.isNaN(d.getTime())?"—":d.toLocaleString(undefined,{month:"short",day:"numeric",hour:"2-digit",minute:"2-digit"});}
function eventSymbol(type=""){return type==="commit"?"↗":type==="release"?"◆":type.startsWith("workflow")?(type==="workflow_failure"?"!":"⚙"):type==="pull_request"?"PR":type==="issue"?"IS":"•";}

class ErrorBoundary extends React.Component { constructor(p){super(p);this.state={error:null};} static getDerivedStateFromError(error){return {error};} render(){if(this.state.error)return <main className="fatal"><div><strong>GitHub Monitor UI crashed</strong><span>{String(this.state.error.message||this.state.error)}</span></div></main>;return this.props.children;} }

createRoot(document.getElementById("root")).render(<ErrorBoundary><App /></ErrorBoundary>);
