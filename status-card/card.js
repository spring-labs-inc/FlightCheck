"use strict";

const byId = (id) => document.getElementById(id);
const setText = (id, value) => { byId(id).textContent = value; };

const date = new Intl.DateTimeFormat("en-US", {
  dateStyle: "medium", timeStyle: "short", timeZone: "America/Chicago",
});
const states = new Set(["passed", "failed", "pending", "unavailable", "stale", "inapplicable"]);
let rendered = false;

function snapshotIsValid(data) {
  const text = (value) => typeof value === "string" && value.length > 0;
  return data?.snapshot === "historical"
    && [data.title, data.summary, data.candidate, data.reviews?.code, data.reviews?.evidence,
      data.reviews?.warningInventory, data.reviews?.reviewerProfile, data.decisions?.presentation,
      data.decisions?.observationsApproval, data.decisions?.cutover, data.decisions?.next,
      data.decisions?.delivery].every(text)
    && Number.isInteger(data.publicationPort) && data.publicationPort > 0 && data.publicationPort <= 65535
    && Number.isFinite(Date.parse(data.reviewedAt)) && Number.isFinite(Date.parse(data.cutoverAt))
    && Array.isArray(data.gates) && data.gates.length > 0
    && data.gates.every((gate) => text(gate?.name) && text(gate.detail) && states.has(gate.state));
}

function renderGates(gates) {
  const activity = (gate) => Math.max(-Infinity,
    ...[gate.updated_at, gate.observed_at, gate.created_at].map(Date.parse).filter(Number.isFinite));
  const ordered = [...gates].sort((left, right) => activity(right) - activity(left));
  const rows = ordered.map(({ name, state, detail }) => {
    const row = document.createElement("li");
    const description = document.createElement("div");
    const label = document.createElement("span");
    const note = document.createElement("span");
    const status = document.createElement("span");

    label.className = "gate-name";
    label.textContent = name;
    note.className = "gate-detail";
    note.textContent = detail;
    status.className = "gate-state";
    status.dataset.state = state;
    status.textContent = state.charAt(0).toUpperCase() + state.slice(1);
    description.append(label, note);
    row.append(description, status);
    return row;
  });
  byId("gates").replaceChildren(...rows);
  setText("gate-count", `${gates.filter(({ state }) => state === "passed").length}/${gates.length} passed`);
  const pending = ordered.filter(({ state }) => state === "pending").map(({ name }) => name);
  setText("pending", pending.length ? pending.join(" · ") : "None in this example.");
}

function render(data) {
  setText("title", data.title);
  setText("summary", data.summary);
  setText("candidate", data.candidate.slice(0, 12));
  byId("candidate").title = data.candidate;
  setText("verdict", data.reviews.evidence);
  setText("reviewed", `Reviewed ${date.format(new Date(data.reviewedAt))} CT`);
  setText("code-review", data.reviews.code);
  setText("warnings", data.reviews.warningInventory);
  setText("profile", data.reviews.reviewerProfile);
  setText("presentation", data.decisions.presentation);
  setText("observations", data.decisions.observationsApproval);
  setText("cutover", data.decisions.cutover);
  byId("cutover").title = `Merged ${date.format(new Date(data.cutoverAt))} CT`;
  setText("next-action", data.decisions.next);
  setText("delivery", data.decisions.delivery);
  renderGates(data.gates);
  rendered = true;
}

async function refresh() {
  let reachedServer = false;
  const abort = new AbortController();
  const timeout = setTimeout(() => abort.abort(), 4500);
  try {
    const response = await fetch("/status.json", { cache: "no-store", signal: abort.signal });
    reachedServer = true;
    if (!response.ok) throw new Error("Snapshot endpoint returned an error");
    const data = await response.json();
    if (!snapshotIsValid(data)) throw new Error("Snapshot shape is invalid");
    render(data);
    setText("publication", "Published on loopback");
    setText("forwarding", String(data.publicationPort) !== location.port ? "Forwarded endpoint reached" : "Endpoint reached");
    setText("rendering", "Snapshot rendered");
    setText("notice", "Synthetic snapshot · illustrates a completed workflow.");
  } catch {
    setText("publication", reachedServer ? "Snapshot unavailable" : "Publication unconfirmed");
    setText("forwarding", reachedServer ? "Endpoint reached" : "Disconnected");
    setText("rendering", rendered ? "Last snapshot retained" : "Shell only");
    if (!rendered) {
      for (const field of ["candidate", "verdict", "gate-count", "presentation", "observations", "cutover", "code-review"]) {
        setText(field, "Unavailable");
      }
      setText("summary", "The example snapshot could not be loaded.");
      setText("reviewed", "Review time unavailable");
      setText("pending", "Unavailable until the snapshot loads.");
    }
    setText("notice", reachedServer
      ? "Snapshot unavailable · check the status endpoint on the checkout host."
      : "Disconnected · check the loopback server, then reopen its URL in Codex.");
  } finally {
    clearTimeout(timeout);
    setTimeout(refresh, 15000);
  }
}

refresh();
