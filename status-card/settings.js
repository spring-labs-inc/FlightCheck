"use strict";
const fragment = new URLSearchParams(location.hash.slice(1));
const capability = fragment.get("cap");
const context = {project: fragment.get("project"), task: fragment.get("task"), session: fragment.get("session")};
history.replaceState(null, "", location.pathname);
const byId = id => document.getElementById(id);
const clone = value => JSON.parse(JSON.stringify(value));
let current, plan, activePlan, readers = [], labels = {};
const states = {todo: "To do", ready: "Ready", in_progress: "In progress", review: "In review", done: "Done"};
function node(tag, text) {const value = document.createElement(tag); if (text !== undefined) value.textContent = text; return value;}
function message(text, error = false) {const value = byId("message"); value.textContent = text; value.setAttribute("role", error ? "alert" : "status");}
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
  const details = node("details"); details.append(node("summary", label)); details.append(node("p", url.href));
  const arrow = node("a", "Open destination ↗"); arrow.href = url.href; arrow.target = "_blank"; arrow.rel = "noopener noreferrer"; arrow.setAttribute("aria-label", "Open " + label + " in a new tab"); details.append(arrow); parent.append(details);
}
function section(title) {const value = node("section"); value.className = "panel settings-section"; value.append(node("h2", title)); byId("groups").append(value); return value;}
function select(control, choices, selected) {
  control.replaceChildren();
  if (selected && !choices.some(([value]) => value === selected)) choices = [[selected, selected + " (saved)"], ...choices];
  for (const [value, label] of choices) {const option = node("option", label); option.value = value; control.append(option);}
  control.value = selected ?? "";
}
function field(parent, key, label, value, type = "text", choices) {
  const row = node("div"); row.className = "settings-field";
  const caption = node("label", label); caption.htmlFor = "field-" + key;
  const control = node(choices ? "select" : type === "textarea" ? "textarea" : "input"); control.id = "field-" + key; control.dataset.key = key;
  if (choices) select(control, choices, value);
  else if (type === "checkbox") {control.type = "checkbox"; control.checked = Boolean(value);}
  else {if (type !== "textarea") control.type = type; control.value = value ?? "";}
  labels[key] = label;
  if (type === "checkbox") {row.className += " settings-toggle"; row.append(control, caption);} else row.append(caption, control);
  const hint = node("span"); hint.id = "hint-" + key; hint.className = "settings-hint"; row.append(hint);
  control.setAttribute("aria-describedby", hint.id);
  control._settingsRow = row; parent.append(row); return control;
}
function simple(parent, key, label, type = "text", choices) {
  const control = field(parent, key, label, current.values[key], type, choices);
  readers.push(result => {
    const value = control.value.trim();
    if (value && value !== current.values[key]) result[key] = value;
    else if (!value && current.values[key]) throw new Error(label + " cannot be empty");
  }); return control;
}
function checkbox(parent, key, label, value) {return field(parent, key, label, value, "checkbox");}
function help(control, text) {byId("hint-" + control.dataset.key).textContent = text;}
function quote(argument) {return /^[A-Za-z0-9_./:=@%-]+$/.test(argument) ? argument : "'" + argument.replace(/'/g, "'\\''") + "'";}
function commandText(command) {return command.map(quote).join(" ");}
function commandArgs(text) {
  // Quoting groups literal arguments. No shell evaluation or command execution.
  const result = []; let word = "", started = false, quoted = null, escaped = false;
  for (const char of text) {
    if (escaped) {word += char; escaped = false; started = true;}
    else if (char === "\\" && quoted !== "'") {escaped = true; started = true;}
    else if (quoted) {if (char === quoted) quoted = null; else word += char;}
    else if (char === "'" || char === '"') {quoted = char; started = true;}
    else if (/\s/.test(char)) {if (started) {result.push(word); word = ""; started = false;}}
    else {word += char; started = true;}
  }
  if (quoted || escaped) throw new Error("Close the quote or trailing escape in the check command");
  if (started) result.push(word);
  if (!result.length || result.some(arg => !arg)) throw new Error("Each check needs a command with nonempty arguments");
  return result;
}
function renderResources(parent) {
  const resources = current.values.resources || {}, values = [];
  const locations = node("div"); locations.className = "settings-grid"; parent.append(locations);
  const names = [["issue_tracker", "Issue tracker"], ["project_board", "Project board location"], ["style_guide", "Style guide"], ["documentation", "Documentation"], ["runbook", "Runbooks"], ["logs", "Log location"]];
  for (const name of Object.keys(resources)) if (!names.some(([key]) => key === name)) names.push([name, name.replace(/_/g, " ")]);
  for (const [key, label] of names) {
    const location = node("div"); locations.append(location);
    const existing = resources[key], input = field(location, "resource-" + key, label, typeof existing === "string" ? existing : existing?.url || "");
    const unavailable = field(location, "resource-state-" + key, "Availability", existing?.unavailable ? "unavailable" : "available", "text", [["available", "Location"], ["unavailable", "Unavailable — record reason"]]);
    const reason = field(location, "resource-reason-" + key, "Unavailable reason", existing?.unavailable || ""); reason._settingsRow.hidden = !existing?.unavailable;
    // Keep field groups discoverable without JSON; optional resources can stay blank.
    unavailable.addEventListener("change", () => {reason._settingsRow.hidden = unavailable.value !== "unavailable"; input.disabled = unavailable.value === "unavailable";});
    input.disabled = Boolean(existing?.unavailable);
    values.push({key, existing, input, unavailable, reason});
    if (typeof existing === "string" && key !== "project_board") destination(location, label + " details", existing);
    if (key === "project_board" && existing?.url) destination(location, label + " details", existing.url);
  }
  readers.push(result => {
    const changes = {};
    for (const {key, existing, input, unavailable, reason} of values) {
      let value;
      if (unavailable.value === "unavailable") {
        if (!reason.value.trim()) throw new Error("Add the unavailable reason for " + labels[input.dataset.key]);
        value = {unavailable: reason.value.trim()};
      } else {
        const text = input.value.trim(); if (!text && existing === undefined) continue;
        if (!text) throw new Error("Provide a location or mark " + labels[input.dataset.key] + " unavailable");
        value = key === "project_board" && typeof existing === "object" && existing.url ? {...existing, url: text} : text;
      }
      if (JSON.stringify(value) !== JSON.stringify(existing)) changes[key] = value;
    }
    if (Object.keys(changes).length) result.resources = changes;
  });
}
function renderChecks(parent) {
  parent.append(node("h3", "Check commands"));
  const list = node("div"); list.className = "check-list"; parent.append(list); const rows = [];
  function add(check = {name: "", command: [], phase: "cheap"}) {
    const row = node("div"); row.className = "check-row"; const index = rows.length;
    const name = field(row, "check-name-" + index, "Check name", check.name);
    const command = field(row, "check-command-" + index, "Command", commandText(check.command));
    const phase = field(row, "check-phase-" + index, "Classification", check.phase, "text", [["cheap", "Cheap check"], ["authoritative", "Authoritative check"]]);
    const remove = node("button", "Remove"); remove.type = "button"; remove.setAttribute("aria-label", "Remove check " + (check.name || index + 1));
    const item = {row, name, command, phase, original: check, removed: false}; rows.push(item);
    remove.addEventListener("click", () => {item.removed = true; row.hidden = true; invalidate();}); row.append(remove); list.append(row);
  }
  for (const check of current.values.checks) add(check);
  const button = node("button", "Add check"); button.type = "button"; button.addEventListener("click", () => {add(); invalidate(); rows[rows.length - 1].name.focus();}); parent.append(button);
  parent.append(node("p", "Commands are recorded, never run by Settings. Quote arguments containing spaces; shell expansions are not evaluated."));
  readers.push(result => {const checks = rows.filter(row => !row.removed).map(({name, command, phase, original}) => ({...original, name: name.value.trim(), command: command.value === commandText(original.command) ? original.command : commandArgs(command.value), phase: phase.value})); if (JSON.stringify(checks) !== JSON.stringify(current.values.checks)) result.checks = checks;});
}
function renderSync(parent) {
  parent.append(node("h3", "Project synchronization"));
  const policy = current.values.status_sync, policies = [policy];
  for (const flight of current.flights || []) {const candidate = flight.configuration.values.status_sync; if (candidate?.project_id && !policies.some(p => p.provider === candidate.provider && p.project_id === candidate.project_id && p.field_id === candidate.field_id)) policies.push(candidate);}
  const enabled = checkbox(parent, "sync-enabled", "Synchronize project status", policy.mode !== "disabled");
  const board = field(parent, "sync-board", "Project board", policy.project_id ? "0" : "", "text", [["", "Choose a configured board"], ...policies.flatMap((p, index) => p.project_id ? [[String(index), current.values.resources?.project_board?.url && index === 0 ? current.values.resources.project_board.url : "Recorded board " + (index + 1)]] : [])]);
  const mode = field(parent, "sync-mode", "If synchronization is unavailable", policy.mode === "required" ? "required" : "advisory", "text", [["advisory", "Report and continue"], ["required", "Block the lifecycle transition"]]);
  const mappings = node("div"); mappings.className = "settings-grid"; parent.append(mappings); const controls = {};
  for (const [state, label] of Object.entries(states)) controls[state] = field(mappings, "sync-" + state, label, "", "text", []);
  function mappingsFor(selected) {
    const options = [["", "Choose a status"], ...Object.entries(selected.options || {}).map(([key, value]) => [value, states[key]])];
    for (const state of Object.keys(states)) select(controls[state], options, selected.options?.[state]);
  }
  function enable() {board.disabled = mode.disabled = !enabled.checked; for (const control of Object.values(controls)) control.disabled = !enabled.checked;}
  board.addEventListener("change", () => {mappingsFor(policies[Number(board.value)] || {options: {}}); invalidate();}); enabled.addEventListener("change", enable);
  mappingsFor(policy); enable();
  parent.append(node("p", "Uses existing board membership and Status options. Saving settings does not grant tracker access or change an active flight’s status authority."));
  const details = node("details"); details.append(node("summary", "Board connection details")); parent.append(details);
  const provider = field(details, "sync-provider", "Provider", policy.provider || "github-projects-v2", "text", [["github-projects-v2", "GitHub Projects v2"]]);
  const project = field(details, "sync-project-id", "Project ID", policy.project_id || "");
  const statusField = field(details, "sync-field-id", "Status field ID", policy.field_id || "");
  const optionFields = {};
  for (const [state, label] of Object.entries(states)) optionFields[state] = field(details, "sync-option-" + state, label + " option ID", policy.options[state] || "");
  details.append(node("p", "Use exact IDs from your existing board. These values are recorded locally; no provider inspection or membership change runs here."));
  const configure = node("button", "Use this board connection"); configure.type = "button"; configure.id = "configure-board";
  configure.addEventListener("click", () => {
    const candidate = {...policy, provider: provider.value, project_id: project.value.trim(), field_id: statusField.value.trim(), options: Object.fromEntries(Object.entries(optionFields).map(([key, control]) => [key, control.value.trim()]))};
    if (!candidate.project_id || !candidate.field_id || Object.values(candidate.options).some(value => !value)) {message("Complete the board connection and all status option IDs", true); return;}
    const index = policies.push(candidate) - 1; const option = node("option", "New board connection"); option.value = String(index); board.append(option); board.value = String(index); mappingsFor(candidate); invalidate(); message("Board connection ready for review; it has not been saved.");
  }); details.append(configure);
  readers.push(result => {
    let selected = board.value === "" ? policy : policies[Number(board.value)];
    if (enabled.checked && board.value === "") throw new Error("Choose or configure a project board before enabling synchronization");
    const value = {...selected, mode: enabled.checked ? mode.value : "disabled", options: {...selected.options}};
    if (enabled.checked) for (const state of Object.keys(states)) value.options[state] = controls[state].value;
    if (JSON.stringify(value) !== JSON.stringify(policy)) result.status_sync = value;
    // A bound destination always follows the one canonical provider/project.
    const resource = result.resources?.project_board || current.values.resources?.project_board;
    if (typeof resource === "string" && result.resources?.project_board && value.project_id) result.resources.project_board = {url: resource, provider: value.provider, project_id: value.project_id};
    if (resource?.url && (resource.provider !== value.provider || resource.project_id !== value.project_id)) result.resources = {...result.resources, project_board: {...resource, provider: value.provider, project_id: value.project_id}};
  });
}
function render(data) {
  current = data; readers = []; labels = {}; plan = undefined; activePlan = undefined;
  byId("save").disabled = true; byId("adopt").disabled = true; byId("review").hidden = true; byId("preview").hidden = false;
  byId("recovery").hidden = data.status !== "recovery_required";
  if (data.status !== "configuration") {message(data.reason, data.status === "recovery_required"); byId("locked").hidden = data.status === "recovery_required"; byId("settings").hidden = true; return;}
  byId("locked").hidden = true; byId("settings").hidden = false; byId("groups").hidden = false; byId("groups").replaceChildren(); byId("advanced-fields").replaceChildren();
  const project = section("Project"); renderResources(project);
  const workflow = section("Workflow"); const activation = checkbox(workflow, "activation", "Use FlightCheck by default for coding work", data.values.activation === "default-for-coding"); help(activation, "Leave off to opt in for each task.");
  readers.push(result => {const value = activation.checked ? "default-for-coding" : "opt-in"; if (value !== data.values.activation) result.activation = value;});
  renderChecks(workflow); simple(workflow, "preview", "UI preview instructions", "textarea"); renderSync(workflow);
  const checkout = section("Checkout & Cleanup"), policy = data.values.checkout_policy;
  const mode = field(checkout, "checkout-mode", "Checkout choice", policy.mode, "text", [["native-choice", "Native choice (default)"], ["worktree-required", "Require a separate worktree"]]);
  const fallback = checkbox(checkout, "checkout-fallback", "Allow Git fallback when native checkout creation is unavailable", policy.git_fallback);
  const prefix = field(checkout, "checkout-prefix", "Branch prefix", policy.branch_prefix || "");
  const protectedBranches = field(checkout, "protected_branches", "Protected / shared branches", data.values.protected_branches.join(", ")); help(protectedBranches, "Comma-separated names. The actual default branch is always protected.");
  readers.push(result => {const value = {...policy, mode: mode.value, git_fallback: fallback.checked}; if (prefix.value.trim()) value.branch_prefix = prefix.value.trim(); else if (policy.branch_prefix) throw new Error("Branch prefix cannot be empty"); if (JSON.stringify(value) !== JSON.stringify(policy)) result.checkout_policy = value; const branches = [...new Set(protectedBranches.value.split(",").map(s => s.trim()).filter(Boolean).concat(data.values.default_branch))].sort(); if (JSON.stringify(branches) !== JSON.stringify(data.values.protected_branches)) result.protected_branches = branches;});
  checkout.append(node("h3", "Future cleanup authority"));
  const cleanup = {};
  for (const [key, label] of [["local_branches", "Verified merged local branches"], ["remote_branches", "Verified merged actual remote branches"], ["temporary_worktrees", "Verified merged temporary worktrees"]]) cleanup[key] = checkbox(checkout, "cleanup-" + key, label, data.values.cleanup_policy[key]);
  checkout.append(node("p", "Exact artifacts and authority are captured at launch. Protected, active, dirty, unknown-private and unintegrated work must always be preserved. Ownership verification and safe checkout protections are required."));
  readers.push(result => {const value = {...data.values.cleanup_policy}; for (const [key, control] of Object.entries(cleanup)) value[key] = control.checked; if (JSON.stringify(value) !== JSON.stringify(data.values.cleanup_policy)) result.cleanup_policy = value;});
  const delivery = section("Evidence & Delivery"); simple(delivery, "evidence_dir", "Private evidence location"); simple(delivery, "nit_tracker", "Nit tracker location");
  simple(delivery, "review_client", "Review client", "text", [["", "Choose a client"], ["Codex", "Codex"], ["Claude", "Claude"]]);
  simple(delivery, "delivery", "Delivery policy", "text", [["Reviewed pull request; merge after required approval", "Pull request and approved merge"], ["Prepare review only; no provider writes", "Prepare review only"]]);
  const advanced = byId("advanced-fields"); simple(advanced, "reviewer_access", "Reviewer access requirements", "textarea"); simple(advanced, "policy_reference", "Project policy location");
  const runtimes = field(advanced, "required_runtimes", "Required runtimes", (data.values.required_runtimes || []).join("\n"), "textarea"); help(runtimes, "One existing runtime requirement per line. Settings does not install or execute runtimes.");
  readers.push(result => {const value = runtimes.value.split("\n").map(row => row.trim()).filter(Boolean); if (JSON.stringify(value) !== JSON.stringify(data.values.required_runtimes || [])) result.required_runtimes = value;});
  const retained = node("details"); retained.append(node("summary", "Additional artifacts to preserve")); advanced.append(retained);
  const retentionRows = [];
  function retain(row = {identity: "", reason: ""}) {
    const group = node("div"); retained.append(group); const index = retentionRows.length;
    retentionRows.push({identity: field(group, "retain-identity-" + index, "Artifact location or identity", row.identity), reason: field(group, "retain-reason-" + index, "Reason to preserve", row.reason)});
  }
  for (const row of data.values.cleanup_policy.retained_artifacts) retain(row);
  const addRetention = node("button", "Add preservation preference"); addRetention.type = "button"; addRetention.addEventListener("click", () => {retain(); invalidate();}); retained.append(addRetention);
  readers.push(result => {const rows = retentionRows.map(({identity, reason}) => ({identity: identity.value.trim(), reason: reason.value.trim()})).filter(row => row.identity || row.reason); if (rows.some(row => !row.identity || !row.reason)) throw new Error("Each preservation preference needs an identity and reason"); if (JSON.stringify(rows) !== JSON.stringify(data.values.cleanup_policy.retained_artifacts)) result.cleanup_policy = {...data.values.cleanup_policy, ...result.cleanup_policy, retained_artifacts: rows};});
  byId("repository").textContent = "Checkout: " + data.repository.checkout + " · Git identity: " + data.repository.git_common_dir;
  byId("revision").textContent = data.revision; byId("capabilities").textContent = "Pinned Python: " + data.values.python + ". Runtime: " + data.runtime.status + ". " + data.capabilities.native_checkout + ". " + data.capabilities.mandatory;
  byId("provenance").replaceChildren();
  for (const [key, meta] of Object.entries(data.values._flightcheck?.fields || {})) {const detail = node("p", key + ": " + meta.source + " · " + meta.scope + " · " + (meta.confirmed ? "confirmed" : "suggestion") + " · validation: " + meta.last_validation.status + " (" + meta.last_validation.validator + ")"); byId("provenance").append(detail);}
  const suggestions = Object.entries(data.values._flightcheck?.fields || {}).filter(([key, meta]) => !meta.confirmed && (key.startsWith("resources.") || ["activation", "checks", "preview", "checkout_policy", "cleanup_policy", "status_sync", "required_runtimes", "evidence_dir", "review_client", "reviewer_access", "delivery", "nit_tracker", "policy_reference"].includes(key))).map(([key]) => key);
  if (suggestions.length) {
    const confirm = checkbox(byId("provenance"), "confirm-suggestions", "Confirm displayed suggestions for future flights", false);
    readers.push(result => {if (confirm.checked) for (const key of suggestions) {if (key.startsWith("resources.")) {const name = key.slice(10); result.resources = {[name]: data.values.resources[name], ...result.resources};} else if (!(key in result)) result[key] = data.values[key];}});
  }
  byId("flights").replaceChildren();
  for (const flight of data.flights || []) {const detail = node("details"); detail.append(node("summary", flight.flight + (flight.configuration.revision === data.revision ? " · matches saved settings" : " · uses earlier settings"))); detail.append(node("pre", JSON.stringify(flight, null, 2))); byId("flights").append(detail);}
  message("Review your changes before saving.");
}
async function reload() {render(await api("read"));}
function changes() {const result = {}; for (const reader of readers) reader(result); if (!Object.keys(result).length) throw new Error("Change a value before reviewing"); return result;}
function invalidate() {plan = undefined; activePlan = undefined; byId("save").disabled = true; byId("adopt").disabled = true;}
function human(value, key) {
  if (value === undefined || value === null || value === "") return "Not set";
  if (typeof value === "boolean") return value ? "Enabled" : "Off";
  if (Array.isArray(value)) return value.map(item => typeof item === "object" && item.command ? item.name + ": " + commandText(item.command) + " (" + item.phase + ")" : human(item, key)).join("; ") || "None";
  if (typeof value === "object") return Object.entries(value).filter(([name]) => !name.endsWith("reference")).map(([name, item]) => (labels[name] || states[name] || name.replace(/_/g, " ")) + ": " + human(item, name)).join("; ") || "None";
  return states[value] || ({"default-for-coding": "On for coding work", "opt-in": "Opt in per task", "native-choice": "Native choice", "worktree-required": "Require a separate worktree", "disabled": "Off", "advisory": "Report and continue", "required": "Block if unavailable"})[value] || String(value);
}
function showPreview(result) {
  const effects = byId("effects"); effects.replaceChildren(); const list = node("ul");
  for (const [key, change] of Object.entries(result.changes)) {const item = node("li"); item.append(node("b", (labels[key] || key.replace(/_/g, " ")) + ": ")); item.append(node("span", human(change.before, key) + " → " + human(change.after, key))); list.append(item);}
  effects.append(list); effects.append(node("p", "Saving records this configuration decision. Active flight decisions and grants stay captured."));
  const details = node("details"); details.append(node("summary", "Details: affected files and validation")); details.append(node("pre", JSON.stringify(result.effects, null, 2))); effects.append(details);
  byId("groups").hidden = true; byId("review").hidden = false; byId("preview").hidden = true; byId("save").disabled = false; effects.focus();
}
function action(id, fn) {byId(id).addEventListener("click", async () => {try {await fn();} catch (error) {invalidate(); message(error.message + ". Reload current values and preview again.", true); byId("message").focus();}});}
byId("settings").addEventListener("submit", async event => {event.preventDefault(); try {const result = await api("preview", {changes: changes(), expected_revision: current.revision}); plan = result.plan_id; showPreview(result); message("Changes ready to save.");} catch (error) {invalidate(); message(error.message, true); byId("message").focus();}});
byId("settings").addEventListener("input", invalidate);
byId("settings").addEventListener("change", invalidate);
action("save", async () => {await api("apply", {plan_id: plan}); await reload(); message("Saved future defaults. Active flight decisions and grants were preserved.");});
action("cancel", async () => {byId("review").hidden = true; byId("groups").hidden = false; byId("preview").hidden = false; invalidate(); byId("preview").focus();});
action("reload", reload); action("recover", async () => {await api("recover", {}); await reload();});
action("audit", async () => {
  const report = await api("audit", {remote: byId("audit-remote").checked}); byId("audit-report").textContent = JSON.stringify(report, null, 2); byId("audit-destinations").replaceChildren();
  const seen = new Set(); function links(value, path) {if (typeof value === "string" && !seen.has(value)) {seen.add(value); destination(byId("audit-destinations"), path, value);} else if (value && typeof value === "object") for (const [key, item] of Object.entries(value)) links(item, path + "." + key);}
  links(report, "Audit destination"); byId("audit-report").focus();
});
action("reconfigure", async () => {const result = await api("reconfigure-preview", {flight: context.task}); activePlan = result.plan_id; byId("active-effects").textContent = result.next + ". Existing grants are retained."; byId("adopt").disabled = false; byId("active-effects").focus();});
action("adopt", async () => {await api("reconfigure-apply", {plan_id: activePlan}); await reload(); message("Active configuration adopted. Affected revalidation remains required before execution.");});
if (capability && Object.values(context).every(Boolean)) reload().catch(error => message(error.message, true));
else message("Read-only card view. Start an explicitly authorized local Settings session to edit private configuration.");
