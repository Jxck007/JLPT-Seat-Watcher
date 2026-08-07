"use strict";

const REFRESH_INTERVAL_MS = 60_000;
const DEFAULT_CHECK_INTERVAL_SECONDS = 900;
const DATA_FILES = ["status.json", "health.json", "metrics.json", "history.json"];
const feeds = {};
let refreshing = false;

const byId = (id) => document.getElementById(id);

function primitive(value) {
  return ["string", "number", "boolean"].includes(typeof value) ? value : null;
}

function finiteNumber(value) {
  const safe = primitive(value);
  if (safe === null || safe === "" || Number.isNaN(Number(safe))) return null;
  return Number(safe);
}

function timestamp(value) {
  const safe = primitive(value);
  if (safe === null || safe === "") return null;
  const parsed = new Date(safe);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function notificationTime(value, urgentOnly = false) {
  if (value && typeof value === "object") {
    const type = primitive(value.type);
    if (urgentOnly && (!type || !String(type).startsWith("urgent"))) return null;
    return primitive(value.at);
  }
  return primitive(value);
}

function formatTime(value, fallback) {
  const parsed = timestamp(value);
  if (!parsed) return fallback;
  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Kolkata",
  }).format(parsed);
}

function setText(id, value) {
  const element = byId(id);
  if (element) element.textContent = String(value);
}

function setClass(id, base, modifier) {
  const element = byId(id);
  if (element) element.className = `${base} ${modifier}`;
}

function legacyStatusValue(status, key) {
  const seats = status.seats && typeof status.seats === "object" ? status.seats : {};
  const aliases = {
    remaining: status.current_remaining ?? status.remaining_seats ?? seats.remaining,
    applied: status.applied ?? seats.applied,
    total: status.total ?? seats.total,
    next_expected_check: status.next_check,
    last_heartbeat: status.last_heartbeat_at,
    last_seat_alert: notificationTime(status.last_notification, true),
  };
  return aliases[key];
}

function statusValue(status, key) {
  return primitive(status[key]) ?? primitive(legacyStatusValue(status, key));
}

function deriveMonitorStatus(status, health) {
  const published = statusValue(status, "monitor_status");
  if (["healthy", "delayed", "failed", "waiting"].includes(String(published))) {
    return String(published);
  }

  const workflow = String(
    statusValue(status, "workflow_status") ?? primitive(health.workflow_status) ?? "unknown",
  ).toLowerCase();
  if (["failure", "failed", "cancelled"].includes(workflow) || health.healthy === false) {
    return "failed";
  }

  const lastCheck = timestamp(statusValue(status, "last_check"));
  if (!lastCheck) return "waiting";
  const interval = finiteNumber(statusValue(status, "check_interval_seconds")) ?? DEFAULT_CHECK_INTERVAL_SECONDS;
  if (health.stale === true || Date.now() - lastCheck.getTime() > interval * 3 * 1000) {
    return "delayed";
  }
  return "healthy";
}

function render() {
  const status = feeds.status || {};
  const health = feeds.health || {};
  const metrics = feeds.metrics || {};
  const remaining = finiteNumber(statusValue(status, "remaining"));
  const applied = finiteNumber(statusValue(status, "applied"));
  const total = finiteNumber(statusValue(status, "total"));

  setText("remaining", remaining === null ? "..." : remaining.toLocaleString("en-IN"));
  setText("applied", applied === null ? "..." : applied.toLocaleString("en-IN"));
  setText("total", total === null ? "..." : total.toLocaleString("en-IN"));

  const availability = statusValue(status, "availability");
  const seatsAvailable = availability === "available" || (remaining !== null && remaining > 0);
  const seatsKnown = remaining !== null || availability === "full" || availability === "available";
  setText("availability-state", seatsKnown ? (seatsAvailable ? "AVAILABLE" : "FULL") : "Waiting");
  setClass(
    "availability-state",
    "availability-state",
    seatsKnown ? (seatsAvailable ? "is-available" : "is-full") : "is-neutral",
  );

  const monitorStatus = deriveMonitorStatus(status, health);
  const monitorLabels = {
    healthy: "Healthy",
    delayed: "Delayed",
    failed: "Failed",
    waiting: "Waiting for first check",
  };
  setText("monitor-state", monitorLabels[monitorStatus]);
  setClass("monitor-state", "monitor-state", `is-${monitorStatus}`);

  setText(
    "last-check",
    formatTime(statusValue(status, "last_check") ?? primitive(health.last_success), "Waiting for first successful check"),
  );
  setText(
    "next-check",
    formatTime(statusValue(status, "next_expected_check"), "Waiting for first successful check"),
  );
  setText(
    "last-heartbeat",
    formatTime(statusValue(status, "last_heartbeat") ?? primitive(health.last_heartbeat_at), "Not sent yet"),
  );

  const oldAlert = notificationTime(metrics.last_successful_alert, true);
  setText(
    "last-alert",
    formatTime(statusValue(status, "last_seat_alert") ?? oldAlert, "No seat alert yet"),
  );
}

async function loadFeed(file) {
  const response = await fetch(`${file}?refresh=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Could not load ${file}`);
  const payload = await response.json();
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error(`Invalid ${file}`);
  }
  return payload;
}

async function refreshDashboard() {
  if (refreshing) return;
  refreshing = true;
  const button = byId("refresh");
  if (button) {
    button.disabled = true;
    button.textContent = "Refreshing...";
  }

  const results = await Promise.allSettled(DATA_FILES.map(loadFeed));
  results.forEach((result, index) => {
    if (result.status === "fulfilled") feeds[DATA_FILES[index].replace(".json", "")] = result.value;
  });

  const statusAvailable = Boolean(feeds.status);
  if (statusAvailable) render();
  const connection = byId("connection-message");
  if (connection) {
    connection.hidden = results.every((result) => result.status === "fulfilled");
    connection.textContent = statusAvailable
      ? "Some dashboard data is temporarily unavailable"
      : "Temporarily unavailable";
  }
  setText("data-state", statusAvailable ? "Auto refresh: 60 seconds" : "Temporarily unavailable");

  if (button) {
    button.disabled = false;
    button.textContent = "Refresh";
  }
  refreshing = false;
}

document.addEventListener("DOMContentLoaded", () => {
  byId("refresh")?.addEventListener("click", refreshDashboard);
  refreshDashboard();
  window.setInterval(refreshDashboard, REFRESH_INTERVAL_MS);
});
