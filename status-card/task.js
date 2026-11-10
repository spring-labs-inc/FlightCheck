"use strict";

const byId = (id) => document.getElementById(id);
const setText = (id, value) => { byId(id).textContent = value; };
const verdicts = new Set(["APPROVE", "APPROVE_WITH_NITS", "APPROVE_WITH_OBSERVATIONS", "REVISE"]);
const taskPath = location.pathname;

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
    setText("verdict", current ? data.verdict : "Pending");
    setText("publication", "Published on loopback");
    setText("forwarding", String(data.publicationPort) !== location.port ? "Forwarded endpoint reached" : "Endpoint reached");
    setText("rendering", "Snapshot rendered");
    setText("notice", current ? "Verdict applies to the displayed candidate." : "Waiting for a verdict on the current candidate.");
  } catch {
    setText("verdict", "Pending");
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
