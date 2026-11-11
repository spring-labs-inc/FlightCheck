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
  const groups = [
    ["epic", "Epic"], ["issue", "Issue"], ["pr", "PR"],
  ].map(([kind, label]) => ({ kind, label, items: links.filter((item) => item.kind === kind) }))
    .filter(({ items }) => items.length);
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
    setText("work-link-description", item.description || "No description published.");
    const destination = link(">", item.url);
    destination.className = "work-link-open";
    destination.target = "_blank";
    destination.setAttribute("aria-label", `Open ${title} in a new tab or window`);
    byId("work-link-destination").replaceChildren(destination);
  }

  fill("links", groups, ({ kind, label, items }, groupIndex) => {
    const group = element("li", "");
    items.forEach((item, index) => {
      const entry = element("span", "", "work-link-item");
      if (index === 0) {
        if (groupIndex > 0) {
          const separator = element("span", "|", "work-link-separator");
          separator.setAttribute("aria-hidden", "true");
          entry.append(separator);
        }
        entry.append(element("span", label, "pill"), " ");
      }
      const reference = item.label.replace(/^(?:epic|issue|pr)\s+(?=#)/i, "");
      const text = kind === "epic" && item.title ? `${reference} ${item.title}` : reference;
      const key = `${kind}:${item.url}`;
      const button = element("button", text, "work-link-select");
      button.type = "button";
      button.setAttribute("aria-label", `${label} ${text}`);
      button.setAttribute("aria-controls", "work-link-detail");
      const choice = { key, item, button };
      button.addEventListener("click", () => {
        selectedWorkLink = selectedWorkLink?.key === key ? undefined : choice;
        showSelection();
      });
      choices.push(choice);
      entry.append(button);
      if (index + 1 < items.length) entry.append(",");
      group.append(entry, " ");
    });
    return group;
  });
  showSelection();
  lastLinks = signature;
}

let lastDetails;
function renderDetails(data) {
  const { candidate, stages = {}, links = [], checks = [], ci = [], history = [] } = data;
  const stageEntries = Object.entries(stages);
  renderWorkLinks(links, data.issue_stages ?? {});
  const fingerprint = JSON.stringify([candidate, stageEntries, checks, ci, history]);
  if (fingerprint !== lastDetails) {
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
    const checkoutName = data.worktree ?? data.branch;
    setText("checkout-label", data.worktree ? "Worktree" : "Branch");
    setText("checkout-name", checkoutName ?? "");
    byId("checkout-line").hidden = !checkoutName;
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
