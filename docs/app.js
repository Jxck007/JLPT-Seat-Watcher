document.documentElement.classList.add("js");

const REFRESH_INTERVAL_MS = 60_000;
const STALE_AFTER_MS = 15 * 60 * 1000;
const DATA_FILES = ["status.json", "history.json", "metrics.json", "health.json"];
const $ = (id) => document.getElementById(id);

const elements = {
  applied: $("applied-seats"),
  availability: $("availability-copy"),
  currentExam: $("current-exam"),
  currentSession: $("current-session"),
  dataNote: $("data-note"),
  deploymentDetail: $("deployment-detail"),
  deploymentLink: $("deployment-link"),
  deploymentRing: $("deployment-ring"),
  deploymentState: $("deployment-state"),
  deploymentTime: $("deployment-time"),
  freshness: $("freshness-label"),
  healthDetail: $("health-detail"),
  healthRing: $("health-ring"),
  healthTitle: $("health-title"),
  healthValue: $("health-value"),
  heroRemaining: $("hero-remaining"),
  historyDuration: $("history-duration"),
  historyEmpty: $("history-empty"),
  historyExecutions: $("history-executions"),
  historyLatency: $("history-latency"),
  historyNotifications: $("history-notifications"),
  lastDuration: $("last-duration"),
  lastNotification: $("last-notification"),
  lastSuccess: $("last-success"),
  lastUpdated: $("last-updated"),
  monitorUptime: $("monitor-uptime"),
  nextCheck: $("next-check"),
  notificationTime: $("notification-time"),
  notificationTitle: $("notification-title"),
  offlineBanner: $("offline-banner"),
  projectStatus: $("project-status"),
  projectStatusDetail: $("project-status-detail"),
  remaining: $("remaining-seats"),
  repoBranch: $("repo-branch"),
  repoCommits: $("repo-commits"),
  repoLanguage: $("repo-language"),
  repoRevision: $("repo-revision"),
  seatContextExam: $("seat-context-exam"),
  seatContextSession: $("seat-context-session"),
  statusOrbit: $("status-orbit"),
  total: $("total-seats"),
  workflowLink: $("workflow-link"),
  workflowRuns: $("workflow-runs"),
  workflowSummary: $("workflow-summary"),
};

const appState = {
  charts: [],
  hasData: false,
  lastRefreshAt: 0,
  refreshing: false,
};

function isValidDate(value) {
  return Boolean(value) && !Number.isNaN(new Date(value).getTime());
}

function formatDate(value) {
  if (!isValidDate(value)) return "Awaiting data";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatShortDate(value) {
  if (!isValidDate(value)) return "Pending";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatRelative(value) {
  if (!isValidDate(value)) return "Awaiting data";
  const seconds = Math.round((new Date(value).getTime() - Date.now()) / 1000);
  const absolute = Math.abs(seconds);
  let amount = seconds;
  let unit = "second";

  if (absolute >= 86400) {
    amount = Math.round(seconds / 86400);
    unit = "day";
  } else if (absolute >= 3600) {
    amount = Math.round(seconds / 3600);
    unit = "hour";
  } else if (absolute >= 60) {
    amount = Math.round(seconds / 60);
    unit = "minute";
  }
  return new Intl.RelativeTimeFormat(undefined, { numeric: "auto" }).format(amount, unit);
}

function formatDuration(value) {
  if (!Number.isFinite(value) || value < 0) return "Awaiting data";
  if (value < 1000) return `${Math.round(value)} ms`;
  return `${(value / 1000).toFixed(2)} s`;
}

function numeric(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : Number.NaN;
}

function formatCount(value) {
  if (!Number.isFinite(value)) return "-";
  return new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

function setStatusClass(element, status) {
  if (!element) return;
  element.classList.remove("is-loading", "is-green", "is-yellow", "is-red");
  element.classList.add(`is-${status}`);
}

function normalizedWorkflowStatus(value) {
  const status = String(value || "unknown").toLowerCase();
  if (status === "success") return "green";
  if (["failure", "failed", "timed_out"].includes(status)) return "red";
  return "yellow";
}

function chartTheme() {
  const styles = getComputedStyle(document.documentElement);
  return {
    accent: styles.getPropertyValue("--accent").trim(),
    accentStrong: styles.getPropertyValue("--accent-strong").trim(),
    line: styles.getPropertyValue("--line-strong").trim(),
    muted: styles.getPropertyValue("--muted").trim(),
    danger: styles.getPropertyValue("--danger").trim(),
    warning: styles.getPropertyValue("--warning").trim(),
  };
}

function updateChartTheme() {
  const colors = chartTheme();
  const palette = [colors.accent, colors.warning, colors.danger, colors.accentStrong];
  appState.charts.forEach((chart) => {
    chart.options.color = colors.muted;
    chart.options.plugins.legend.labels.color = colors.muted;
    chart.data.datasets.forEach((dataset, index) => {
      if (chart.config.type === "line") dataset.borderColor = palette[index % palette.length];
      else dataset.backgroundColor = palette[index % palette.length];
    });
    Object.values(chart.options.scales).forEach((scale) => {
      scale.grid.color = colors.line;
      scale.ticks.color = colors.muted;
    });
    chart.update("none");
  });
}

function chartOptions() {
  const colors = chartTheme();
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: reduceMotion ? false : { duration: 450 },
    interaction: { intersect: false, mode: "index" },
    color: colors.muted,
    plugins: {
      legend: {
        align: "start",
        labels: { boxWidth: 9, boxHeight: 2, color: colors.muted, padding: 18, usePointStyle: true },
      },
    },
    scales: {
      x: {
        border: { display: false },
        grid: { display: false, color: colors.line },
        ticks: { color: colors.muted, maxRotation: 0, maxTicksLimit: 7 },
      },
      y: {
        beginAtZero: true,
        border: { display: false },
        grid: { color: colors.line },
        ticks: { color: colors.muted, precision: 0 },
      },
    },
  };
}

function sampled(items, maximum = 240) {
  if (items.length <= maximum) return items;
  const step = Math.ceil(items.length / maximum);
  return items.filter((_, index) => index % step === 0 || index === items.length - 1);
}

function observationRecords(execution) {
  return execution.seats || execution.observations || [];
}

function renderCharts(history) {
  if (!window.Chart) {
    elements.historyEmpty.hidden = false;
    elements.historyEmpty.querySelector("strong").textContent = "Charts could not be loaded.";
    return;
  }

  appState.charts.forEach((chart) => chart.destroy());
  appState.charts = [];
  const colors = chartTheme();
  const palette = [colors.accent, colors.warning, colors.danger, colors.accentStrong];
  const executions = sampled(history.executions || []);
  const targetNames = new Set();

  executions.forEach((execution) => {
    observationRecords(execution).forEach((record) => {
      targetNames.add(record.target || `${record.level} ${record.session}`);
    });
  });

  const dateLabel = new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
  const labels = executions.map((execution) => dateLabel.format(new Date(execution.executed_at)));
  const datasets = [...targetNames].map((target, index) => ({
    label: target,
    data: executions.map((execution) => {
      const record = observationRecords(execution).find(
        (item) => (item.target || `${item.level} ${item.session}`) === target
      );
      return record ? record.remaining ?? record.value ?? null : null;
    }),
    borderColor: palette[index % palette.length],
    backgroundColor: "transparent",
    borderWidth: 2,
    pointRadius: executions.length > 45 ? 0 : 2,
    pointHoverRadius: 4,
    spanGaps: true,
    tension: 0.24,
  }));

  const remainingChart = new window.Chart($("remaining-chart"), {
    type: "line",
    data: { labels, datasets },
    options: chartOptions(),
  });

  const daily = history.daily_statistics || [];
  const dayLabel = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });
  const performanceChart = new window.Chart($("performance-chart"), {
    type: "bar",
    data: {
      labels: daily.map((item) => dayLabel.format(new Date(`${item.date}T00:00:00`))),
      datasets: [
        {
          label: "Website latency",
          data: daily.map((item) => item.average_latency_ms),
          backgroundColor: colors.accent,
          borderRadius: 6,
          maxBarThickness: 20,
        },
        {
          label: "Execution time",
          data: daily.map((item) => item.average_execution_time_ms),
          backgroundColor: colors.warning,
          borderRadius: 6,
          maxBarThickness: 20,
        },
      ],
    },
    options: chartOptions(),
  });
  appState.charts = [remainingChart, performanceChart];
}

function renderStatus(status) {
  const seats = status.seats || {};
  const remaining = status.current_remaining ?? seats.remaining;
  const applied = status.applied ?? seats.applied;
  const total = status.total ?? seats.total;
  const lastCheck = status.last_check || status.checks?.last_success_at || status.updated_at;
  const nextCheck = status.next_check || status.checks?.next_check_at;
  const duration = status.execution_time_ms ?? status.checks?.duration_ms;
  const exam = status.current_level || status.current_exam || "N4";
  const rawSession = status.current_session || "Afternoon";
  const session = rawSession.toLowerCase().includes("session") ? rawSession : `${rawSession} session`;
  const hasSeats = [remaining, applied, total].every(Number.isFinite);
  const notification = status.last_notification || {};

  elements.currentExam.textContent = exam;
  elements.currentSession.textContent = session;
  elements.seatContextExam.textContent = exam;
  elements.seatContextSession.textContent = session;
  elements.remaining.textContent = hasSeats ? String(remaining) : "-";
  elements.heroRemaining.textContent = hasSeats ? String(remaining) : "-";
  elements.applied.textContent = hasSeats ? String(applied) : "-";
  elements.total.textContent = hasSeats ? String(total) : "-";
  elements.lastSuccess.textContent = formatDate(lastCheck);
  elements.lastDuration.textContent = formatDuration(numeric(duration));
  elements.lastUpdated.textContent = formatDate(lastCheck);
  elements.nextCheck.textContent = formatDate(nextCheck);
  elements.freshness.textContent = isValidDate(lastCheck) ? `Updated ${formatRelative(lastCheck)}` : "Snapshot pending";

  elements.availability.textContent = hasSeats
    ? remaining > 0
      ? "Seats detected"
      : "No seats detected"
    : "Awaiting snapshot";
  setStatusClass(elements.availability, hasSeats && remaining > 0 ? "green" : hasSeats ? "yellow" : "loading");

  if (isValidDate(notification.at)) {
    elements.notificationTitle.textContent = notification.type || "Notification delivered";
    elements.lastNotification.textContent = "A successful alert was recorded by the monitor.";
    elements.notificationTime.textContent = `${formatDate(notification.at)} (${formatRelative(notification.at)})`;
    elements.notificationTime.dateTime = notification.at;
  }

  if (hasSeats && isValidDate(lastCheck)) elements.dataNote.hidden = true;
}

function isClientStale(status, health) {
  const lastCheck = status.last_check || status.updated_at;
  return Boolean(health.stale) || !isValidDate(lastCheck) || Date.now() - new Date(lastCheck).getTime() > STALE_AFTER_MS;
}

function renderHealth(status, health) {
  const stale = isClientStale(status, health);
  const workflowStatus = health.workflow_status || status.workflow_status || "unknown";
  let state = "green";
  let title = "Operational";
  let detail = "The latest workflow completed and the public snapshot is current.";

  if (normalizedWorkflowStatus(workflowStatus) === "red") {
    state = "red";
    title = "Workflow failed";
    detail = health.last_failure
      ? `The latest failure was recorded ${formatRelative(health.last_failure)}.`
      : "The latest monitoring workflow did not complete successfully.";
  } else if (!health.healthy || stale) {
    state = "yellow";
    title = stale ? "Snapshot stale" : "Attention needed";
    detail = stale
      ? "The public snapshot is older than the expected monitoring interval."
      : `Heartbeat status is ${String(health.heartbeat_status || "pending").replaceAll("_", " ")}.`;
  }

  setStatusClass(elements.statusOrbit, state);
  setStatusClass(elements.healthRing, state);
  elements.projectStatus.textContent = title;
  elements.projectStatusDetail.textContent = detail;
  elements.healthTitle.textContent = title;
  elements.healthDetail.textContent = detail;
  elements.healthValue.textContent = state === "green" ? "Good" : state === "red" ? "Issue" : "Check";
  setStatusClass(document.querySelector(".signal-success"), normalizedWorkflowStatus(workflowStatus));
  setStatusClass(document.querySelector(".signal-fresh"), stale ? "yellow" : "green");
  setStatusClass(
    document.querySelector(".signal-delivery"),
    health.heartbeat_status === "healthy" ? "green" : health.heartbeat_status === "overdue" ? "red" : "yellow"
  );
}

function renderMetrics(metrics) {
  elements.historyExecutions.textContent = formatCount(Number(metrics.checks_today));
  elements.historyNotifications.textContent = formatCount(Number(metrics.notifications_today));
  elements.historyLatency.textContent = formatDuration(numeric(metrics.average_website_latency_ms));
  elements.historyDuration.textContent = formatDuration(numeric(metrics.average_runtime_ms));
  elements.monitorUptime.textContent = Number.isFinite(metrics.monitor_uptime_percent)
    ? `${metrics.monitor_uptime_percent.toFixed(2)}%`
    : "Awaiting data";

  const repository = metrics.repository || {};
  elements.repoCommits.textContent = formatCount(Number(repository.commit_count));
  elements.repoRevision.textContent = repository.revision || "Pending";
  elements.repoBranch.textContent = repository.branch || "main";
  elements.repoLanguage.textContent = repository.language || "Python";
}

function renderWorkflowHistory(history, workflowStatus) {
  const publishedRuns = (history.workflow_runs || []).slice(-5).reverse();
  const executions = (history.executions || []).slice(-5).reverse();
  elements.workflowRuns.replaceChildren();
  if (publishedRuns.length) {
    publishedRuns.forEach((run) => {
      const item = document.createElement("li");
      const title = document.createElement(run.run_url ? "a" : "span");
      const state = document.createElement("span");
      const time = document.createElement("time");
      title.textContent = run.run_number ? `Run #${run.run_number}` : "Monitor run";
      if (title instanceof HTMLAnchorElement) {
        title.href = run.run_url;
        title.target = "_blank";
        title.rel = "noreferrer";
      }
      state.className = "run-state";
      state.textContent = run.status || "unknown";
      setStatusClass(state, normalizedWorkflowStatus(run.status));
      time.textContent = formatShortDate(run.updated_at);
      time.dateTime = run.updated_at || "";
      item.append(title, state, time);
      elements.workflowRuns.append(item);
    });
    const latestRun = publishedRuns[0];
    elements.workflowSummary.textContent = `Latest monitor run is ${latestRun.status || "unknown"}. Updated ${formatRelative(latestRun.updated_at)}.`;
    if (latestRun.run_url) elements.workflowLink.href = latestRun.run_url;
    return;
  }

  if (!executions.length) {
    const item = document.createElement("li");
    const message = document.createElement("span");
    message.textContent = "Workflow history is awaiting its first published check.";
    item.append(message);
    elements.workflowRuns.append(item);
    elements.workflowSummary.textContent = "No successful checks have been published yet.";
    return;
  }

  executions.forEach((execution, index) => {
    const workflow = execution.workflow || {};
    const item = document.createElement("li");
    const label = workflow.run_number
      ? `Run #${workflow.run_number}`
      : `Check ${formatShortDate(execution.executed_at)}`;
    const title = document.createElement(workflow.run_url ? "a" : "span");
    const state = document.createElement("span");
    const time = document.createElement("time");

    title.textContent = label;
    if (title instanceof HTMLAnchorElement) {
      title.href = workflow.run_url;
      title.target = "_blank";
      title.rel = "noreferrer";
    }
    const status = workflow.status || (index === 0 ? workflowStatus : "success");
    state.className = "run-state";
    state.textContent = status;
    setStatusClass(state, normalizedWorkflowStatus(status));
    time.textContent = formatShortDate(execution.executed_at);
    time.dateTime = execution.executed_at;
    item.append(title, state, time);
    elements.workflowRuns.append(item);
  });

  const latest = executions[0];
  const latestWorkflow = latest.workflow || {};
  const latestStatus = latestWorkflow.status || workflowStatus;
  elements.workflowSummary.textContent = `Latest published check is ${latestStatus}. Updated ${formatRelative(latest.executed_at)}.`;
  if (latestWorkflow.run_url) elements.workflowLink.href = latestWorkflow.run_url;
}

function renderDeployment(status, health) {
  const workflowStatus = health.workflow_status || status.workflow_status || "unknown";
  const stale = isClientStale(status, health);
  const state = normalizedWorkflowStatus(workflowStatus) === "red" ? "red" : stale ? "yellow" : "green";
  setStatusClass(elements.deploymentRing, state);
  elements.deploymentState.textContent = state === "green" ? "Snapshot published" : state === "red" ? "Monitor run failed" : "Publication needs attention";
  elements.deploymentDetail.textContent = state === "green"
    ? "The committed JSON snapshot is ready for automatic Pages deployment."
    : state === "red"
      ? "Failure health was published for this monitoring run."
      : "The committed snapshot is missing or stale.";
  elements.deploymentTime.textContent = formatDate(status.generated_at || health.generated_at);
  elements.deploymentTime.dateTime = status.generated_at || health.generated_at || "";
}

function renderHistory(history) {
  const executions = history.executions || [];
  elements.historyEmpty.hidden = executions.length > 0;
  if (executions.length > 0) renderCharts(history);
}

function setOffline(offline, message = "Offline. Showing the most recently loaded monitor snapshot.") {
  elements.offlineBanner.hidden = !offline;
  elements.offlineBanner.textContent = message;
  document.body.classList.toggle("is-offline", offline);
}

async function fetchJson(file, signal) {
  const separator = file.includes("?") ? "&" : "?";
  const response = await fetch(`${file}${separator}refresh=${Date.now()}`, {
    cache: "no-store",
    signal,
  });
  if (!response.ok) throw new Error(`${file} returned ${response.status}`);
  const payload = await response.json();
  if (![1, 2].includes(payload.schema_version)) throw new Error(`${file} has an unsupported schema`);
  return payload;
}

async function refreshDashboard() {
  if (appState.refreshing) return;
  appState.refreshing = true;
  elements.freshness.textContent = appState.hasData ? "Refreshing live data" : "Loading live data";
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 12_000);

  try {
    const [status, history, metrics, health] = await Promise.all(
      DATA_FILES.map((file) => fetchJson(file, controller.signal))
    );
    renderStatus(status);
    renderMetrics(metrics);
    renderHealth(status, health);
    renderWorkflowHistory(history, health.workflow_status || status.workflow_status);
    renderDeployment(status, health);
    renderHistory(history);
    appState.hasData = true;
    appState.lastRefreshAt = Date.now();
    setOffline(false);
  } catch (error) {
    setOffline(
      true,
      navigator.onLine
        ? "Live data is temporarily unavailable. Showing the last loaded snapshot."
        : "Offline. Showing the most recently loaded monitor snapshot."
    );
    elements.freshness.textContent = appState.hasData ? "Refresh failed" : "Live data unavailable";
    if (!appState.hasData) {
      setStatusClass(elements.statusOrbit, "yellow");
      setStatusClass(elements.healthRing, "yellow");
      elements.projectStatus.textContent = "Data unavailable";
      elements.projectStatusDetail.textContent = "The static monitoring feeds could not be loaded.";
      elements.healthTitle.textContent = "Connection issue";
      elements.healthDetail.textContent = "Retrying automatically every 60 seconds.";
      elements.healthValue.textContent = "Offline";
    }
    console.warn("Could not refresh dashboard data:", error);
  } finally {
    window.clearTimeout(timeout);
    appState.refreshing = false;
  }
}

function setupTheme() {
  const toggle = $("theme-toggle");
  const label = toggle.querySelector(".theme-label");
  const stored = localStorage.getItem("jlpt-dashboard-theme");
  const preferred = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  const initial = stored === "light" || stored === "dark" ? stored : preferred;

  function apply(theme) {
    document.documentElement.dataset.theme = theme;
    toggle.setAttribute("aria-pressed", String(theme === "dark"));
    toggle.setAttribute("aria-label", theme === "dark" ? "Switch to light theme" : "Switch to dark theme");
    label.textContent = theme === "dark" ? "Light theme" : "Dark theme";
    document.querySelector('meta[name="theme-color"]').content = theme === "dark" ? "#0a0d0c" : "#edf2ef";
    updateChartTheme();
  }

  apply(initial);
  toggle.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    localStorage.setItem("jlpt-dashboard-theme", next);
    apply(next);
  });
}

function setupReveals() {
  const items = document.querySelectorAll(".reveal");
  if (!window.IntersectionObserver || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    items.forEach((item) => item.classList.add("is-visible"));
    return;
  }
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      });
    },
    { threshold: 0.12 }
  );
  items.forEach((item) => observer.observe(item));
}

setupTheme();
setupReveals();
window.addEventListener("offline", () => setOffline(true));
window.addEventListener("online", () => refreshDashboard());
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && Date.now() - appState.lastRefreshAt >= REFRESH_INTERVAL_MS) refreshDashboard();
});
refreshDashboard();
window.setInterval(refreshDashboard, REFRESH_INTERVAL_MS);
