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

function observationRow(data, candidate, detail) {
  const row = element("li", "");
  const description = element("div", "");
  const name = element("span", data.url ? "" : data.name, "gate-name");
  if (data.url) name.append(link(data.name, data.url));
  const meta = element("span", detail ? `${detail} · ` : "", "gate-detail");
  meta.append(dateLabel(data.observed_at));
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

function stageRow([name, state]) {
  const marks = { completed: "✓", current: "→", skipped: "-", pending: "·" };
  const row = element("li", "");
  const mark = element("span", marks[state]);
  mark.setAttribute("aria-hidden", "true");
  row.dataset.state = state;
  if (state === "current") row.setAttribute("aria-current", "step");
  const label = state === "current" ? `[ ${name} ]` : name;
  const status = element("span", ` (${state})`, state === "skipped" ? "" : "visually-hidden");
  const description = element("span", label);
  description.append(status);
  row.append(mark, description);
  return row;
}

let lastDetails;
function renderDetails(data) {
  const { candidate, stages = {}, links = [], checks = [], ci = [], history = [] } = data;
  const stageEntries = Object.entries(stages);
  const fingerprint = JSON.stringify([candidate, stageEntries, links, checks, ci, history]);
  if (fingerprint !== lastDetails) {
    const kinds = { issue: "Issue", epic: "Epic", pr: "PR" };
    fill("links", links, ({ kind, label, url }) => {
      const row = element("li", "");
      row.append(element("span", kinds[kind], "pill"), link(label, url));
      return row;
    });
    fill("stages", stageEntries, stageRow);
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

async function refresh() {
  let reachedServer = false;
  const abort = new AbortController();
  const timeout = setTimeout(() => abort.abort(), 4500);
  try {
    const response = await fetch("status.json", { cache: "no-store", signal: abort.signal });
    reachedServer = true;
    if (!response.ok) throw new Error("Task snapshot is unavailable");
    const data = await response.json();
    if (data?.snapshot !== "live" || `/task/${data.task}/` !== taskPath
        || ![data.title, data.summary, data.candidate].every((value) => typeof value === "string")
        || !Number.isInteger(data.publicationPort) || data.publicationPort < 1 || data.publicationPort > 65535) {
      throw new Error("Invalid task snapshot");
    }
    const current = data.candidate && data.candidate === data.verdict_candidate && verdicts.has(data.verdict);
    setText("title", data.title);
    setText("summary", data.summary);
    setText("candidate", data.candidate.slice(0, 12) || "Pending");
    byId("candidate").title = data.candidate;
    setText("worktree", data.worktree ?? "");
    byId("worktree-line").hidden = !data.worktree;
    setText("verdict", current ? data.verdict : "Pending");
    renderDetails(data);
    setText("publication", "Published on loopback");
    setText("forwarding", String(data.publicationPort) !== location.port ? "Forwarded endpoint reached" : "Endpoint reached");
    setText("rendering", "Snapshot rendered");
    setText("notice", current ? "Verdict applies to the displayed candidate." : "Waiting for a verdict on the current candidate.");
  } catch {
    setText("verdict", "Pending");
    byId("task-details").hidden = true;
    setText("publication", reachedServer ? "Snapshot unavailable" : "Publication unconfirmed");
    setText("forwarding", reachedServer ? "Endpoint reached" : "Disconnected");
    setText("rendering", "Current snapshot unavailable");
    setText("notice", "Current status could not be verified. Refer to the task in chat.");
  } finally {
    clearTimeout(timeout);
    setTimeout(refresh, 5000);
  }
}

refresh();
