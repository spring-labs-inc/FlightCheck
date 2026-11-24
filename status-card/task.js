"use strict";

const byId = (id) => document.getElementById(id);
const setText = (id, value) => { byId(id).textContent = value; };
const verdicts = new Set(["APPROVE", "APPROVE_WITH_NITS", "APPROVE_WITH_OBSERVATIONS", "REVISE"]);
const taskPath = location.pathname;
const timeFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

function element(tag, content, className) {
  const node = document.createElement(tag);
  node.textContent = content;
  if (className) node.className = className;
  return node;
}

function link(label, url) {
  const destination = new URL(url);
  if (destination.protocol !== "https:" || destination.username || destination.password || destination.search) {
    throw new Error("Invalid work link");
  }
  const anchor = element("a", label);
  anchor.href = destination.href;
  anchor.rel = "noreferrer";
  return anchor;
}

function dateLabel(value) {
  const time = element("time", timeFormat.format(new Date(value)));
  time.dateTime = value;
  return time;
}

function activityTime(data) {
  return [data.observed_at, data.updated_at, data.created_at]
    .filter((value) => Number.isFinite(Date.parse(value)))
    .sort((left, right) => Date.parse(right) - Date.parse(left))[0];
}

function observationRow(data, candidate, detail) {
  const row = element("li", "");
  const description = element("div", "");
  const name = element("span", data.url ? "" : data.name, "gate-name");
  if (data.url) name.append(link(data.name, data.url));
  const meta = element("span", detail ? `${detail} · ` : "", "gate-detail");
  meta.append(dateLabel(activityTime(data)));
  const state = candidate === data.candidate && !data.stale ? data.state : "stale";
  if (state === "stale") {
    meta.append(` · Candidate ${data.candidate.slice(0, 12)}`);
    meta.title = data.candidate;
    meta.append(` · Was ${data.state}`);
  }
  const status = element("span", state.charAt(0).toUpperCase() + state.slice(1), "gate-state");
  status.dataset.state = state;
  description.append(name, meta);
  row.append(description, status);
  return row;
}

function fill(id, rows, render) {
  byId(`${id}-panel`).hidden = rows.length === 0;
  byId(id).replaceChildren(...rows.map(render));
}

function stageRow([name, state], updatedAt) {
  const marks = { completed: "✓", current: "→", skipped: "-", pending: "·" };
  const row = element("li", "");
  const mark = element("span", marks[state]);
  mark.setAttribute("aria-hidden", "true");
  row.dataset.state = state;
  if (updatedAt) row.title = `Updated ${timeFormat.format(new Date(updatedAt))}`;
  if (state === "current") row.setAttribute("aria-current", "step");
  const label = state === "current" ? `[ ${name} ]` : name;
  const status = element("span", ` (${state})`, state === "skipped" ? "" : "visually-hidden");
  const description = element("span", label);
  description.append(status);
  row.append(mark, description);
  return row;
}

let lastLinks;
let selectedWorkLink;
let issueStages;
function renderWorkLinkStage() {
  const flight = selectedWorkLink?.item.flight;
  const record = flight && Object.hasOwn(issueStages, flight) ? issueStages[flight] : undefined;
  byId("work-link-stage").hidden = !record;
  if (record) {
    const label = record.shared ? "Shared flight stage" : "Workflow stage";
    const value = `${label} · ${record.stage}`;
    if (byId("work-link-stage").textContent !== value) setText("work-link-stage", value);
  }
}

function renderWorkLinks(links, stages) {
  issueStages = stages;
  const signature = JSON.stringify(links);
  if (signature === lastLinks) {
    renderWorkLinkStage();
    return;
  }
  const labels = { epic: "Epic", issue: "Issue", pr: "PR" };
  const choices = [];
  const detail = byId("work-link-detail");

  function showSelection() {
    const selected = choices.find(({ key }) => key === selectedWorkLink?.key);
    selectedWorkLink = selected;
    renderWorkLinkStage();
    for (const choice of choices) choice.button.setAttribute("aria-expanded", String(choice === selected));
    detail.hidden = !selected;
    if (!selected) {
      byId("work-link-destination").replaceChildren();
      return;
    }
    const { item } = selected;
    const title = item.title || item.label;
    setText("work-link-title", title);
    const metadata = item.metadata;
    let description = item.description || "Details not loaded.";
    if (metadata?.state === "empty") description = "No description published.";
    else if (metadata?.state === "stale") {
      description = `Last known details · ${metadata.reason || "Refresh is due."}${item.description ? ` ${item.description}` : ""}`;
    } else if (metadata && metadata.state !== "ready") description = metadata.reason || "Details unavailable.";
    setText("work-link-description", description);
    const destination = link(">", item.url);
    destination.className = "work-link-open";
    destination.target = "_blank";
    destination.rel = "noopener noreferrer";
    destination.setAttribute("aria-label", `Open ${title} in a new tab or window`);
    byId("work-link-destination").replaceChildren(destination);
  }

  const orderedLinks = [...links.filter(item => item.kind === "epic"), ...links.filter(item => item.kind !== "epic")];
  fill("links", orderedLinks, (item) => {
    const row = element("li", "", item.kind === "epic" ? "work-link-epic" : "");
    const entry = element("span", "", item.kind === "epic" ? "work-link-item work-link-item--epic" : "work-link-item");
    const label = labels[item.kind];
    entry.append(element("span", label, "pill"), " ");
    const reference = item.label.replace(/^(?:epic|issue|pr)\s+(?=#)/i, "");
    const epicTitle = item.title && item.title.length > 48
      ? `${item.title.slice(0, 48).replace(/\s+\S*$/, "").replace(/[,:;]$/, "")} …` : item.title;
    const text = item.kind === "epic" && epicTitle ? `${reference} ${epicTitle}` : reference;
    const key = `${item.kind}:${item.url}`;
    const button = element("button", text, "work-link-select");
    button.type = "button";
    const fullLabel = item.kind === "epic" && item.title ? `${reference} ${item.title}` : text;
    button.setAttribute("aria-label", `${label} ${fullLabel}`);
    if (item.kind === "epic" && item.title) button.title = item.title;
    button.setAttribute("aria-controls", "work-link-detail");
    const choice = { key, item, button };
    button.addEventListener("click", () => {
      selectedWorkLink = selectedWorkLink?.key === key ? undefined : choice;
      showSelection();
    });
    choices.push(choice);
    entry.append(button);
    row.append(entry, " ");
    return row;
  });
  showSelection();
  lastLinks = signature;
}

let lastDetails;
function renderDetails(data) {
  const { candidate, stages = {}, links = [], checks = [], ci = [], history = [] } = data;
  const stageEntries = Object.entries(stages);
  renderWorkLinks(links, data.issue_stages ?? {});
  const fingerprint = JSON.stringify([candidate, stageEntries, data.stage_updated_at, checks, ci, history]);
  if (fingerprint !== lastDetails) {
    fill("stages", stageEntries, (entry) => stageRow(entry, data.stage_updated_at?.[entry[0]]));
    byId("evidence").hidden = !checks.length && !ci.length;
    fill("checks", checks, (check) => observationRow(check, candidate,
      Object.entries(check.counts).map(([label, count]) => `${count} ${label}`).join(" · ")));
    fill("ci", ci, (run) => observationRow(run, candidate,
      [run.kind === "pr" ? "PR" : "Post-merge", run.attempt && `Attempt ${run.attempt}`, run.commit.slice(0, 12)]
        .filter(Boolean).join(" · ")));
    fill("history", history, (event) => {
      const row = element("li", "");
      const description = element("div", "");
      const meta = element("span", ` · ${event.kind} · Candidate ${event.candidate.slice(0, 12)}`, "gate-detail");
      meta.prepend(dateLabel(event.observed_at));
      meta.title = event.candidate;
      description.append(element("span", event.summary, "gate-name"), meta);
      row.append(description);
      return row;
    });
    setText("history-count", String(history.length));
    lastDetails = fingerprint;
  }
  byId("task-details").hidden = ![stageEntries, links, checks, ci, history].some((rows) => rows.length);
}

const pollInterval = 5000;
const requestDeadline = 4500;
const staleAfter = 30;
let lastSnapshot;
let receivedAt;
let connectionState = "Unknown";
let updateState = "Unknown";
let receiptMessage = "";
let hadTransportFailure = false;
let refreshTimer;
let refreshing = false;
let wakePending = false;
let observationGap = false;

function freshness(data) {
  const value = data.freshness;
  const ages = [value?.activity_age_seconds, value?.publication_age_seconds, value?.heartbeat_age_seconds];
  const timestamps = [value?.activity_at, value?.published_at, value?.publisher_heartbeat_at, value?.owner_expires_at];
  // Ages come from the worker's clock. Never compare its timestamps with the browser clock.
  if (!value || !Number.isInteger(value.revision) || value.revision < 1
      || !timestamps.every((time) => typeof time === "string" && Number.isFinite(Date.parse(time)))
      || !ages.every((age) => typeof age === "number" && Number.isFinite(age) && age >= 0)
      || typeof value.owner_remaining_seconds !== "number" || !Number.isFinite(value.owner_remaining_seconds)
      || !["active", "closed", "expired", "stale"].includes(value.state)) {
    return { current: false, closed: false, unknown: true };
  }
  const elapsed = Math.max(0, (performance.now() - receivedAt) / 1000);
  const heartbeatAge = value.heartbeat_age_seconds + elapsed;
  const closed = value.state === "closed";
  const leaseExpired = !closed && (value.state === "expired" || value.owner_remaining_seconds <= elapsed);
  const stale = !closed && (value.state === "stale" || heartbeatAge > staleAfter);
  return { current: !leaseExpired && !stale, closed };
}

function relativeAge(value) {
  const age = Math.max(0, value);
  const [unit, scale] = age >= 86400 ? ["d", 86400] : age >= 3600 ? ["h", 3600]
    : age >= 60 ? ["m", 60] : ["s", 1];
  return `${Math.floor(age / scale)}${unit}`;
}

function renderFreshness(data) {
  const status = freshness(data);
  const elapsed = Math.max(0, (performance.now() - receivedAt) / 1000);
  const value = data.freshness;
  const progressKnown = typeof value?.activity_age_seconds === "number"
    && Number.isFinite(value.activity_age_seconds) && value.activity_age_seconds >= 0
    && typeof value.activity_at === "string" && Number.isFinite(Date.parse(value.activity_at));
  setText("progress-summary", progressKnown
    ? `Last progress ${relativeAge(value.activity_age_seconds + elapsed)} ago · Details` : "Last progress unknown · Details");
  return status;
}

function notice(value) {
  setText("notice", value);
  byId("notice").hidden = !value;
}

function renderUpdateDetails() {
  setText("connection-status", `Connection: ${connectionState} · Updates: ${updateState}`);
  const age = receivedAt === undefined ? "unknown" : performance.now() - receivedAt < 1000
    ? "just now" : `${relativeAge((performance.now() - receivedAt) / 1000)} ago`;
  setText("receipt-status", `Last received: ${age}${receiptMessage ? ` · ${receiptMessage}` : ""}`);
}

function unverified(updates = "Unknown", message = observationGap ? "Resuming after gap" : "") {
  setText("verdict", "Pending");
  notice(lastSnapshot ? "Updates paused · Showing last known status" : "Update freshness unknown");
  updateState = updates;
  receiptMessage = message;
  if (lastSnapshot) renderFreshness(lastSnapshot);
  renderUpdateDetails();
}

async function refresh() {
  if (refreshing) { wakePending = true; return; }
  refreshing = true;
  clearTimeout(refreshTimer);
  const startedAt = performance.now();
  if (lastSnapshot && startedAt - receivedAt > pollInterval + requestDeadline) {
    observationGap = true;
    unverified();
  } else if (lastSnapshot && !freshness(lastSnapshot).current) {
    unverified();
  }
  let reachedServer = false;
  let timeout;
  let closed = false;
  const abort = new AbortController();
  try {
    const request = (async () => {
      const response = await fetch("status.json", { cache: "no-store", signal: abort.signal });
      reachedServer = true;
      if (!response.ok) throw new Error("Task snapshot is unavailable");
      return await response.json();
    })();
    // Bound both headers and body decoding even when a transport fails to settle on abort.
    const deadline = new Promise((resolve, reject) => {
      timeout = setTimeout(() => { abort.abort(); reject(new Error("Snapshot deadline exceeded")); }, requestDeadline);
    });
    const data = await Promise.race([request, deadline]);
    if (document.visibilityState === "hidden") return;
    if (data?.snapshot !== "live" || `/task/${data.task}/` !== taskPath
        || ![data.title, data.summary, data.candidate].every((value) => typeof value === "string")
        || !Number.isInteger(data.publicationPort) || data.publicationPort < 1 || data.publicationPort > 65535) {
      throw new Error("Invalid task snapshot");
    }
    if (Number.isInteger(lastSnapshot?.freshness?.revision)
        && Number.isInteger(data.freshness?.revision)
        && data.freshness.revision < lastSnapshot.freshness.revision) {
      throw new Error("Snapshot revision moved backwards");
    }
    receivedAt = performance.now();
    lastSnapshot = data;
    const status = renderFreshness(data);
    closed = status.closed;
    const current = status.current && data.candidate && data.candidate === data.verdict_candidate && verdicts.has(data.verdict);
    setText("title", data.title);
    setText("summary", data.summary);
    setText("candidate", data.candidate.slice(0, 12) || "Pending");
    byId("candidate").title = data.candidate;
    const checkoutName = data.worktree ?? data.branch;
    setText("checkout-label", data.worktree ? "Worktree" : "Branch");
    setText("checkout-name", checkoutName ?? "");
    byId("checkout-line").hidden = !checkoutName;
    setText("verdict", current ? data.verdict : "Pending");
    renderDetails(data);
    const reconnected = hadTransportFailure;
    connectionState = "Connected";
    updateState = status.closed ? "Closed" : status.unknown ? "Unknown" : status.current ? "Live" : "Paused";
    receiptMessage = reconnected ? "Reconnected after gap" : observationGap ? "Resumed after gap" : "";
    hadTransportFailure = false;
    renderUpdateDetails();
    notice(status.current ? "" : status.unknown ? "Update freshness unknown" : "Updates paused · Showing last known status");
    observationGap = false;
  } catch {
    connectionState = reachedServer ? "Connected" : "Disconnected";
    if (!reachedServer && receivedAt !== undefined) hadTransportFailure = true;
    unverified(reachedServer ? "Unavailable" : "Unknown", "");
  } finally {
    clearTimeout(timeout);
    refreshing = false;
    if (document.visibilityState === "hidden") {
      wakePending = false;
    } else if (wakePending) {
      wakePending = false;
      refreshTimer = setTimeout(refresh, 0);
    } else if (!closed) {
      refreshTimer = setTimeout(refresh, Math.max(0, pollInterval - (performance.now() - startedAt)));
    }
  }
}

function wake() {
  observationGap = receivedAt !== undefined;
  unverified();
  clearTimeout(refreshTimer);
  if (document.visibilityState !== "hidden") refresh();
}

document.addEventListener("visibilitychange", wake);
window.addEventListener("online", wake);
window.addEventListener("pageshow", wake);
refresh();
