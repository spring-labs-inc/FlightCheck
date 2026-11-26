"use strict";
const fragment = new URLSearchParams(location.hash.slice(1));
const capability = fragment.get("cap");
const context = {project: fragment.get("project"), task: fragment.get("task"), session: fragment.get("session")};
history.replaceState(null, "", location.pathname);
const byId = id => document.getElementById(id);
let current, plan, activePlan;
const fields = [
  ["Project", [
    ["resources", "Repository resources: issue tracker, style guide, docs, runbooks and approved log routes", "json"],
    ["default_branch", "Actual default branch", "text"], ["protected_branches", "Additional protected/shared branches", "json"]]],
  ["Workflow", [
    ["activation", "Activation", "activation"], ["activation_reference", "Default-for-coding owner authorization reference", "text"],
    ["checks", "Check commands and cheap/authoritative classification (recorded only)", "json"],
    ["required_runtimes", "Required runtimes (recorded requirements)", "json"], ["preview", "UI preview instructions (recorded only)", "text"],
    ["python", "Pinned project Python (explicit terminal reconciliation required to change)", "readonly"],
    ["status_sync", "Confirmed synchronization project and status mapping", "readonly-json"]]],
  ["Checkout & Cleanup", [
    ["checkout_policy", "Checkout policy: native-choice or worktree-required, branch prefix and confirmed Git fallback", "json"],
    ["cleanup_policy", "Future cleanup scopes and additional retained artifacts", "json"]]],
  ["Evidence & Delivery", [
    ["evidence_dir", "Private evidence location", "text"], ["review_client", "Review client", "text"],
    ["reviewer_access", "Required reviewer access / existing authorization reference", "text"],
    ["delivery", "Future delivery policy (does not grant provider authority)", "text"],
    ["nit_tracker", "Nit tracker", "text"], ["policy_reference", "Existing project policy / configuration reference", "text"]]]
];
function message(text, error = false) {
  const node = byId("message"); node.textContent = text; node.setAttribute("role", error ? "alert" : "status");
}
async function api(action, body) {
  const headers = {Authorization: "Bearer " + capability};
  for (const [key, value] of Object.entries(context)) headers["X-FlightCheck-" + key[0].toUpperCase() + key.slice(1)] = value;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch("api/" + action, {method: body === undefined ? "GET" : "POST", headers, body: body === undefined ? undefined : JSON.stringify(body), credentials: "omit", cache: "no-store"});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || data.reason || "Settings request failed; reload and preview again");
  return data;
}
function destination(parent, label, value) {
  if (typeof value !== "string") return;
  let url; try {url = new URL(value);} catch (_) {return;}
  if (url.protocol !== "https:" || url.username || url.password) return;
  const details = document.createElement("details"); const summary = document.createElement("summary"); summary.textContent = label; details.append(summary);
  const text = document.createElement("p"); text.textContent = url.href; details.append(text);
  const arrow = document.createElement("a"); arrow.href = url.href; arrow.target = "_blank"; arrow.rel = "noopener noreferrer"; arrow.textContent = "↗"; arrow.setAttribute("aria-label", "Open " + label + " in a new tab"); details.append(arrow); parent.append(details);
}
function render(data) {
  current = data; plan = undefined; activePlan = undefined; byId("save").disabled = true; byId("adopt").disabled = true;
  if (data.status === "unconfigured" || data.status === "incompatible") {message(data.reason); byId("locked").hidden = false; byId("settings").hidden = true; return;}
  byId("locked").hidden = true; byId("settings").hidden = false;
  if (data.status === "recovery_required") {message(data.reason, true); byId("groups").replaceChildren(); return;}
  byId("revision").textContent = data.revision; byId("groups").replaceChildren();
  byId("repository").textContent = "Repository: " + data.repository.checkout + " · Git identity: " + data.repository.git_common_dir;
  for (const [group, items] of fields) {
    const details = document.createElement("details"); details.className = "panel"; details.open = group === "Project"; const summary = document.createElement("summary"); summary.textContent = group; details.append(summary);
    for (const [key, label, type] of items) {
      const row = document.createElement("div"); row.className = "settings-field";
      const caption = document.createElement("label"); caption.htmlFor = "field-" + key; caption.textContent = label; row.append(caption);
      const control = document.createElement(type.includes("json") ? "textarea" : type === "activation" ? "select" : "input"); control.id = "field-" + key; control.dataset.key = key; control.dataset.type = type;
      if (type === "activation") for (const name of ["opt-in", "default-for-coding"]) {const option = document.createElement("option"); option.value = name; option.textContent = name; control.append(option);}
      control.value = type.includes("json") ? JSON.stringify(data.values[key] ?? (key === "required_runtimes" || key === "protected_branches" ? [] : {}), null, 2) : data.values[key] ?? "";
      if (type.startsWith("readonly")) control.readOnly = true;
      const meta = data.values._flightcheck?.fields?.[key];
      const provenance = document.createElement("p"); provenance.id = "meta-" + key; provenance.className = "muted";
      provenance.textContent = meta ? `${meta.source} · ${meta.scope} · ${meta.confirmed ? "confirmed" : "suggestion — confirm before use"} · last validation: ${meta.last_validation.status} (${meta.last_validation.validator})` : "Missing optional value — resolve only when needed";
      control.setAttribute("aria-describedby", provenance.id); row.append(control, provenance); details.append(row);
      if (meta && !meta.confirmed && !type.startsWith("readonly")) {
        const confirm = document.createElement("input"); confirm.type = "checkbox"; confirm.id = "confirm-" + key;
        const label = document.createElement("label"); label.htmlFor = confirm.id; label.textContent = "Confirm this displayed suggestion for future flights";
        row.append(confirm, label);
      }
      if (key === "resources") for (const [name, value] of Object.entries(data.values.resources || {})) {
        const boundBoard = name === "project_board" && value && typeof value === "object" && value.provider === data.values.status_sync.provider && value.project_id === data.values.status_sync.project_id;
        if (name !== "project_board" || boundBoard) destination(details, name, boundBoard ? value.url : value);
        const provenance = document.createElement("p"); const m = data.values._flightcheck?.fields?.["resources." + name];
        provenance.textContent = name + ": " + (m ? m.source + " · " + m.scope + " · " + (m.confirmed ? "confirmed" : "suggestion") : "unconfirmed") + (name === "project_board" && typeof value === "string" ? " · retained pointer; bind the canonical synchronization identity before opening" : ""); details.append(provenance);
      }
    }
    byId("groups").append(details);
  }
  byId("flights").replaceChildren();
  for (const flight of data.flights || []) {const detail = document.createElement("details"); const summary = document.createElement("summary"); summary.textContent = flight.flight + " · captured revision " + flight.configuration.revision + (flight.configuration.revision === data.revision ? " · matches defaults" : " · differs from defaults"); detail.append(summary); const pre = document.createElement("pre"); pre.textContent = JSON.stringify(flight, null, 2); detail.append(pre); byId("flights").append(detail);}
  byId("capabilities").textContent = data.capabilities.native_checkout + ". " + data.capabilities.mandatory + ". Runtime: " + data.runtime.status;
  message("Private Settings session ready. Preview changes before saving.");
}
async function reload() {render(await api("read"));}
function changes() {
  const result = {};
  for (const control of document.querySelectorAll("[data-key]")) {
    if (control.dataset.type.startsWith("readonly")) continue;
    const key = control.dataset.key;
    const value = control.dataset.type === "json" ? JSON.parse(control.value) : control.value;
    if (value === "" && current.values[key] === undefined) continue;
    if (JSON.stringify(value) !== JSON.stringify(current.values[key]) || byId("confirm-" + key)?.checked) result[key] = value;
  }
  if (!Object.keys(result).length) throw new Error("Change or explicitly confirm a value before previewing");
  return result;
}
function action(id, fn) {byId(id).addEventListener("click", async () => {try {await fn();} catch (error) {plan = undefined; byId("save").disabled = true; message(error.message + ". Reload current values and preview again.", true); byId("message").focus();}});}
byId("settings").addEventListener("submit", async event => {event.preventDefault(); try {const result = await api("preview", {changes: changes(), expected_revision: current.revision, reference: byId("reference").value}); plan = result.plan_id; byId("effects").textContent = JSON.stringify(result, null, 2); byId("save").disabled = false; message("Preview ready. Review changed values and effects before saving."); byId("effects").focus();} catch (error) {message(error.message, true);}});
byId("settings").addEventListener("input", () => {plan = undefined; activePlan = undefined; byId("save").disabled = true; byId("adopt").disabled = true;});
action("save", async () => {await api("apply", {plan_id: plan}); await reload(); message("Saved future defaults. Active flight decisions and grants were preserved.");});
action("reload", reload); action("recover", async () => {await api("recover", {}); await reload();});
action("audit", async () => {
  const report = await api("audit", {remote: byId("audit-remote").checked});
  byId("audit-report").textContent = JSON.stringify(report, null, 2); byId("audit-destinations").replaceChildren();
  const seen = new Set();
  function links(value, path) {
    if (typeof value === "string" && !seen.has(value)) {seen.add(value); destination(byId("audit-destinations"), path, value);}
    else if (value && typeof value === "object") for (const [key, item] of Object.entries(value)) links(item, path + "." + key);
  }
  links(report, "Audit destination"); byId("audit-report").focus();
});
action("reconfigure", async () => {const result = await api("reconfigure-preview", {flight: context.task, reference: byId("reference").value}); activePlan = result.plan_id; byId("active-effects").textContent = JSON.stringify(result, null, 2); byId("adopt").disabled = false; byId("active-effects").focus();});
action("adopt", async () => {await api("reconfigure-apply", {plan_id: activePlan}); await reload(); message("Active configuration adopted. Affected revalidation remains required before execution.");});
if (capability && Object.values(context).every(Boolean)) reload().catch(error => message(error.message, true));
else message("Read-only card view. Start an explicitly authorized local Settings session to edit private configuration.");
