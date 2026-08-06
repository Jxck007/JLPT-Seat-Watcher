document.documentElement.classList.add("js");

const REFRESH_INTERVAL_MS = 60_000;
const STALE_AFTER_MS = 15 * 60 * 1000;
const DATA_FILES = ["status.json", "history.json", "metrics.json", "health.json"];
const $ = (id) => document.getElementById(id);
const state = { chart: null, feeds: {}, refreshing: false, lastRefreshAt: 0 };

const value = (obj, ...keys) => keys.reduce((found, key) => found ?? obj?.[key], undefined);
const number = (v) => (v === null || v === undefined || v === "" || Number.isNaN(Number(v)) ? null : Number(v));
const dateOk = (v) => v && !Number.isNaN(new Date(v).getTime());
const formatDate = (v) => dateOk(v) ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(v)) : "Awaiting data";
const formatShort = (v) => dateOk(v) ? new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(v)) : "Awaiting data";
const formatCount = (v) => number(v) === null ? "–" : new Intl.NumberFormat().format(number(v));
const formatMs = (v) => number(v) === null ? "–" : `${Math.round(number(v))} ms`;
const formatDuration = (v) => {
  const n = number(v); if (n === null) return "–";
  if (n < 1000) return `${Math.round(n)} ms`;
  return `${(n / 1000).toFixed(1)} s`;
};
const sessionLabel = (v) => {
  if (!v) return "Awaiting data";
  const text = String(v).replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1).toLowerCase();
};

function setText(id, text) { const node = $(id); if (node) node.textContent = text; }
function setOffline(message) {
  const banner = $("offline-banner");
  if (banner) { banner.hidden = !message; banner.textContent = message || ""; }
  setText("refresh-state", message ? "Offline snapshot" : "Live feed");
}

function render() {
  const status = state.feeds.status || {};
  const metrics = state.feeds.metrics || {};
  const health = state.feeds.health || {};
  const seats = status.seats || {};
  const checks = status.checks || {};
  const remaining = number(value(status, "current_remaining", "remaining_seats") ?? value(seats, "remaining", "current_remaining"));
  const applied = value(status, "applied", "applied_seats") ?? value(seats, "applied");
  const total = value(status, "total", "total_seats") ?? value(seats, "total");
  const lastCheck = value(status, "last_check", "checked_at") ?? value(checks, "last_check", "checked_at");
  const nextCheck = value(status, "next_check", "next_run");
  const workflow = String(value(status, "workflow_status") ?? value(health, "workflow_status") ?? "unknown").toLowerCase();
  const stale = Boolean(health.stale) || (dateOk(lastCheck) && Date.now() - new Date(lastCheck).getTime() > STALE_AFTER_MS);
  setText("remaining-seats", formatCount(remaining));
  setText("applied-seats", formatCount(applied));
  setText("total-seats", formatCount(total));
  setText("current-exam", value(status, "current_level", "level") ?? "Awaiting data");
  setText("current-session", sessionLabel(value(status, "current_session", "session")));
  setText("last-check", formatShort(lastCheck));
  setText("next-check", formatShort(nextCheck));
  setText("updated-at", dateOk(lastCheck) ? `Updated ${formatShort(lastCheck)}` : "Awaiting first check");
  setText("execution-time", formatDuration(value(status, "execution_time_ms", "execution_time") ?? metrics.average_runtime_ms));
  setText("website-latency", formatMs(value(status, "website_latency_ms", "latency_ms") ?? metrics.average_website_latency_ms));
  setText("checks-today", formatCount(metrics.checks_today));
  setText("notifications-today", formatCount(metrics.notifications_today));
  const notification = value(status, "last_notification") ?? metrics.last_successful_alert;
  setText("last-notification", dateOk(notification) ? formatDate(notification) : (notification || "None recorded"));
  setText("revision", metrics.repository?.revision || status.revision || "—");
  setText("snapshot-state", state.lastRefreshAt ? "Published" : "Loading");

  const stateChip = $("availability-state");
  if (stateChip) {
    stateChip.className = "state-chip " + (remaining === null ? "is-loading" : remaining > 0 ? "is-green" : "is-yellow");
    stateChip.textContent = remaining === null ? "Loading" : remaining > 0 ? "Available" : "Full";
  }
  const healthy = health.healthy !== false && workflow !== "failure" && workflow !== "failed" && !stale;
  const attention = stale || workflow === "failure" || workflow === "failed" || health.healthy === false;
  const orb = $("health-orb"); if (orb) orb.className = `health-orb ${healthy ? "is-green" : attention ? "is-red" : "is-yellow"}`;
  setText("monitor-status-title", healthy ? "Operational" : attention ? (stale ? "Snapshot stale" : "Workflow failed") : "Attention needed");
  setText("status-detail", healthy ? "Checks are arriving on schedule." : (stale ? "No recent successful check." : "Review the latest workflow run."));
  setText("workflow-status", workflow === "success" || workflow === "successful" ? "Success" : workflow === "unknown" ? "Unknown" : workflow);
  setText("heartbeat-status", health.heartbeat_status || (healthy ? "Live" : "Delayed"));
}

function drawChart() {
  const canvas = $("remaining-chart"); if (!canvas || !window.Chart) return;
  const entries = Array.isArray(state.feeds.history?.executions) ? state.feeds.history.executions.slice(-30) : [];
  const labels = entries.map((e) => formatShort(e.timestamp || e.execution_time || e.checked_at));
  const data = entries.map((e) => number(e.remaining ?? e.current_remaining ?? e.seats?.remaining));
  setText("history-count", entries.length ? `${entries.length} checks` : "No checks yet");
  const empty = $("history-empty"); if (empty) empty.hidden = entries.length > 0;
  if (state.chart) state.chart.destroy();
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  state.chart = new Chart(canvas, { type: "line", data: { labels, datasets: [{ data, borderColor: "#63e6be", backgroundColor: "rgba(99,230,190,.12)", fill: true, tension: .35, pointRadius: 2, spanGaps: true }] }, options: { responsive: true, maintainAspectRatio: false, animation: { duration: reducedMotion ? 0 : 400 }, plugins: { legend: { display: false } }, scales: { x: { display: false }, y: { beginAtZero: true, ticks: { color: "#8d9c9c", precision: 0 }, grid: { color: "rgba(255,255,255,.07)" } } } } });
}

async function fetchFeed(file) {
  const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 12000);
  try { const response = await fetch(`${file}?refresh=${Date.now()}`, { cache: "no-store", signal: controller.signal }); if (!response.ok) throw new Error(`${response.status}`); return await response.json(); }
  finally { clearTimeout(timer); }
}
async function refreshDashboard() {
  if (state.refreshing) return; state.refreshing = true;
  try {
    const feeds = await Promise.all(DATA_FILES.map(fetchFeed));
    DATA_FILES.forEach((file, index) => { state.feeds[file.replace(".json", "")] = feeds[index]; });
    state.lastRefreshAt = Date.now(); render(); drawChart(); setOffline("");
  } catch (error) { setOffline("Live data unavailable · retrying in 60 seconds"); if (!state.lastRefreshAt) { setText("monitor-status-title", "Data unavailable"); setText("status-detail", "Static monitor feeds unavailable."); } }
  finally { state.refreshing = false; }
}

function applyTheme(theme) {
  const dark = theme !== "light"; document.documentElement.dataset.theme = dark ? "dark" : "light";
  const button = $("theme-toggle"); if (button) { button.setAttribute("aria-pressed", String(dark)); button.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme"); const label = button.querySelector(".theme-label"); if (label) label.textContent = dark ? "Light" : "Dark"; }
  const meta = document.querySelector('meta[name="theme-color"]'); if (meta) meta.content = dark ? "#0a0d0c" : "#eef3f1";
}
function initTheme() { const saved = localStorage.getItem("jlpt-dashboard-theme"); applyTheme(saved || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")); $("theme-toggle")?.addEventListener("click", () => { const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark"; localStorage.setItem("jlpt-dashboard-theme", next); applyTheme(next); }); }

window.addEventListener("online", refreshDashboard); window.addEventListener("offline", () => setOffline("Offline · showing last published snapshot"));
document.addEventListener("DOMContentLoaded", () => { initTheme(); refreshDashboard(); setInterval(refreshDashboard, REFRESH_INTERVAL_MS); });
