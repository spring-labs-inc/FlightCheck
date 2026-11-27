"use strict";
const fragment = new URLSearchParams(location.hash.slice(1));
const navigationKey = "flightcheck-settings:" + location.pathname;
const taskFromPath = decodeURIComponent(location.pathname.split("/").filter(Boolean).at(-2) || "");
let retained;
try {retained = JSON.parse(sessionStorage.getItem(navigationKey));} catch (_) {}
if (retained?.expires < Date.now() || retained?.context?.task !== taskFromPath) {retained = undefined; try {sessionStorage.removeItem(navigationKey);} catch (_) {}}
const navigationExpires = fragment.get("cap") ? Date.now() + 30 * 60 * 1000 : retained?.expires;
let capability = fragment.get("cap") || retained?.capability;
const context = fragment.get("cap") ? {project: fragment.get("project"), task: fragment.get("task"), session: fragment.get("session")} : retained?.context || {};
history.replaceState(null, "", location.pathname);
function forgetContext() {try {sessionStorage.removeItem(navigationKey);} catch (_) {}}
function rememberContext() {
  // Same-origin, exact-task, current-tab navigation only. Never a public link,
  // cookie or persistent localStorage grant. The server revalidates every use.
  try {sessionStorage.setItem(navigationKey, JSON.stringify({capability, context, expires: navigationExpires}));} catch (_) {}
}
const byId = id => document.getElementById(id);
const clone = value => JSON.parse(JSON.stringify(value));
const canonical = value => Array.isArray(value) ? value.map(canonical) : value && typeof value === "object" ? Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])])) : value;
const equal = (a, b) => JSON.stringify(canonical(a)) === JSON.stringify(canonical(b));
let friendlyStatuses = {};
let current, plan, activePlan, readers = [], labels = {};
const states = {todo: "To do", ready: "Ready", in_progress: "In progress", review: "In review", done: "Done"};
function node(tag, text) {const value = document.createElement(tag); if (text !== undefined) value.textContent = text; return value;}
function message(text, error = false) {const value = byId("message"); value.textContent = text; value.className = error ? "settings-message problem" : "settings-message"; value.setAttribute("role", error ? "alert" : "status");}
async function api(action, body) {
  const headers = {Authorization: "Bearer " + capability};
  for (const [key, value] of Object.entries(context)) headers["X-FlightCheck-" + key[0].toUpperCase() + key.slice(1)] = value;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch("api/" + action, {method: body === undefined ? "GET" : "POST", headers, body: body === undefined ? undefined : JSON.stringify(body), credentials: "omit", cache: "no-store"});
  const data = await response.json();
  if (!response.ok) {if (response.status === 403) forgetContext(); throw new Error(data.error || data.reason || "Settings request failed; reload and preview again");}
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
function resourceControl(parent, key, label) {
  const existing = current.values.resources?.[key];
  const value = typeof existing === "string" ? existing : existing?.url || "";
  const input = field(parent, "resource-" + key, label, value); input.placeholder = "Not configured";
  let clearUnavailable = false;
  const status = node("span"); status.className = "settings-hint"; input._settingsRow.append(status);
  const details = node("details"); details.append(node("summary", "Details"));
  if (existing?.unavailable) {
    details.append(node("p", existing.unavailable));
    const clear = node("button", "Clear unavailable record"); clear.type = "button";
    clear.addEventListener("click", () => {clearUnavailable = true; update(); invalidate();}); details.append(clear);
  }
  if (value) destination(details, label + " destination", value);
  if (existing?.unavailable || value) input._settingsRow.append(details);
  function update() {
    status.textContent = input.value.trim() ? "" : existing?.unavailable && !clearUnavailable ? "Unavailable · see Details" : "Not configured";
    status.className = "settings-hint" + (!input.value.trim() && existing?.unavailable && !clearUnavailable ? " problem-text" : "");
  }
  input.addEventListener("input", update); update();
  return {input, existing, value: () => {
    const text = input.value.trim();
    if (!text && existing?.unavailable && !clearUnavailable) return existing;
    if (!text) return undefined;
    return typeof existing === "object" && existing.url && text === existing.url ? existing : text;
  }};
}
function renderResources(parent) {
  const locations = node("div"); locations.className = "settings-grid"; parent.append(locations);
  const names = [["issue_tracker", "Tracker"], ["style_guide", "Style guide"], ["documentation", "Documentation"], ["runbook", "Runbooks"], ["logs", "Logs"]];
  for (const name of Object.keys(current.values.resources || {})) if (name !== "project_board" && !names.some(([key]) => key === name)) names.push([name, name.replace(/_/g, " ")]);
  const controls = names.map(([key, label]) => ({key, ...resourceControl(locations, key, label)}));
  readers.push(result => {const changes = {}; for (const control of controls) {const value = control.value(); if (JSON.stringify(value) !== JSON.stringify(control.existing)) changes[control.key] = value ?? null;} if (Object.keys(changes).length) result.resources = changes;});
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
function renderSync(parent, advanced) {
  const policy = current.values.status_sync;
  const resource = resourceControl(parent, "project_board", "Board");
  help(resource.input, "Configure this board once. Synchronization uses the same connection.");
  const title = node("p"); title.id = "board-name"; parent.append(title);
  const status = node("p"); status.id = "board-status"; status.className = "settings-hint"; parent.append(status);
  const discover = node("button", "Read board details"); discover.type = "button"; discover.id = "discover-board"; parent.append(discover);
  const enabled = checkbox(parent, "sync-enabled", "Synchronize status", policy.mode !== "disabled");
  const mappings = node("div"); mappings.id = "sync-mappings"; mappings.className = "settings-grid"; parent.append(mappings);
  const advancedGroup = node("section"); advancedGroup.append(node("h3", "Synchronization")); advanced.append(advancedGroup);
  const mode = field(advancedGroup, "sync-mode", "When synchronization fails", policy.mode === "required" ? "required" : "advisory", "text", [["advisory", "Report and continue"], ["required", "Block the transition"]]);
  help(mode, "Required policy blocks the scoped lifecycle transition when synchronization cannot be verified.");
  const manual = node("details"); manual.id = "board-manual"; manual.append(node("summary", "Manual board connection · fallback")); advancedGroup.append(manual);
  manual.append(node("p", "Use existing connection IDs only when board details cannot be read. GitHub Projects v2 is supported. Existing membership is required; Settings never adds it."));
  const project = field(manual, "sync-project-id", "Project ID", policy.project_id || "");
  const statusField = field(manual, "sync-field-id", "Status field ID", policy.field_id || "");
  const optionFields = {};
  for (const [state, label] of Object.entries(states)) optionFields[state] = field(manual, "sync-option-" + state, label + " status ID", policy.options[state] || "");
  const controls = {}; let manualDecision; let metadata = current.board_details, selected = clone(policy), lastMode = policy.mode === "required" ? "required" : "advisory";
  function manualValues() {return {project_id: project.value.trim() || null, field_id: statusField.value.trim() || null, options: Object.fromEntries(Object.entries(optionFields).map(([key, control]) => [key, control.value.trim()]))};}
  const confirm = node("button", "Use this connection"); confirm.type = "button"; confirm.id = "confirm-board";
  confirm.addEventListener("click", () => {
    const values = manualValues(), url = resource.input.value.trim();
    if (!url || !values.project_id || !values.field_id || Object.values(values.options).some(value => !value) || new Set(Object.values(values.options)).size !== 5) {message("Provide this board’s exact project, field and five distinct status IDs", true); return;}
    manualDecision = {url, ...values}; invalidate(); message("Manual connection ready for review. These supplied IDs have not been discovered or access-verified.");
  }); manual.append(confirm);
  function renderMappings() {
    mappings.replaceChildren();
    if (metadata) {
      title.textContent = metadata.title + " · " + metadata.field.name;
      friendlyStatuses = Object.fromEntries(metadata.field.options.map(option => [option.id, option.name]));
    }
    if (metadata) for (const [state, label] of Object.entries(states)) {
      const options = metadata.field.options.map(option => [option.id, option.name]);
      // An absent mapping remains an explicit choice; never infer from names.
      const saved = selected.options[state] || "", missing = saved && !options.some(([id]) => id === saved);
      controls[state] = field(mappings, "sync-" + state, label, saved, "text", [["", "Choose a status"], ...(missing ? [[saved, "Previously configured status · unavailable"]] : []), ...options]);
      if (missing) {help(controls[state], "The observed field no longer contains this saved status. Choose an available status."); controls[state].setAttribute("aria-invalid", "true");}
    } else mappings.append(node("p", "Read board details for named status choices. Saved mappings are preserved; manual setup is available in Advanced."));
    relevance();
  }
  function relevance() {
    mappings.hidden = !enabled.checked; mode._settingsRow.hidden = !enabled.checked;
    manual.hidden = Boolean(metadata); advancedGroup.hidden = !enabled.checked && Boolean(metadata);
    discover.disabled = !resource.input.value.trim();
  }
  enabled.addEventListener("change", relevance);
  resource.input.addEventListener("input", () => {
    metadata = undefined; title.textContent = ""; status.textContent = "";
    // A changed URL cannot inherit another board's IDs. Preserve saved policy
    // while synchronization is off; enabling requires the newly resolved board.
    selected = clone(policy); renderMappings(); invalidate();
  });
  discover.addEventListener("click", async () => {
    try {
      const data = await api("board-discover", {url: resource.input.value.trim(), authorize_read: true});
      if (data.field.options.length < 5) throw new Error("This field has fewer than five statuses; distinct lifecycle mappings cannot be configured");
      metadata = data; title.textContent = data.title + " · " + data.field.name;
      status.textContent = "Board details read. Review mappings before saving."; status.className = "settings-hint";
      const same = selected.project_id === data.project_id && selected.field_id === data.field.id;
      selected = {...policy, provider: data.provider, project_id: data.project_id, field_id: data.field.id, options: same ? {...selected.options} : {}};
      renderMappings(); invalidate();
    } catch (error) {metadata = undefined; status.textContent = error.message; status.className = "settings-hint problem-text"; renderMappings();}
  });
  renderMappings();
  readers.push(result => {
    const pointer = resource.value(), url = typeof pointer === "string" ? pointer : pointer?.url;
    let value = clone(policy);
    const supplied = manualValues(), manualAccepted = equal(manualDecision, {url, ...supplied});
    const manualChanged = supplied.project_id !== policy.project_id || supplied.field_id !== policy.field_id || Object.keys(states).some(key => supplied.options[key] !== (policy.options[key] || ""));
    if (metadata && enabled.checked && Object.values(controls).some(control => !metadata.field.options.some(option => option.id === control.value))) throw new Error("Choose existing statuses from the observed board field");
    if (metadata) value = {...selected, options: enabled.checked ? Object.fromEntries(Object.entries(controls).map(([key, control]) => [key, control.value])) : {...selected.options}};
    else if (manualAccepted) value = {...policy, provider: "github-projects-v2", ...supplied};
    else if (manualChanged) throw new Error("Use this connection to confirm edited manual IDs before reviewing");
    if (enabled.checked && (!url || !value.project_id || !value.field_id || Object.keys(states).some(key => !value.options[key]))) throw new Error("Read board details or complete Advanced connection setup before enabling synchronization");
    const previousURL = typeof resource.existing === "string" ? resource.existing : resource.existing?.url;
    const bound = Boolean(resource.existing?.url && resource.existing.url === url && resource.existing.provider === policy.provider && resource.existing.project_id === policy.project_id);
    if (enabled.checked && !bound && !metadata && !manualAccepted) throw new Error("Read details or explicitly confirm the connection for this board before enabling synchronization");
    if (enabled.checked) {lastMode = mode.value; value.mode = lastMode;} else value.mode = "disabled";
    if (!equal(value, policy)) result.status_sync = value;
    let destination = pointer;
    if (url && value.project_id && (metadata || bound || manualAccepted)) destination = {url, provider: value.provider, project_id: value.project_id};
    if (JSON.stringify(destination) !== JSON.stringify(resource.existing)) result.resources = {...result.resources, project_board: destination ?? null};
  });
}
function render(data) {
  current = data; readers = []; labels = {}; friendlyStatuses = {}; plan = undefined; activePlan = undefined;
  byId("save").disabled = true; byId("adopt").disabled = true; byId("review").hidden = true; byId("preview").hidden = false;
  byId("recovery").hidden = data.status !== "recovery_required";
  if (data.status !== "configuration") {message(data.reason, data.status === "recovery_required"); byId("locked").hidden = data.status === "recovery_required"; byId("settings").hidden = true; return;}
  byId("locked").hidden = true; byId("settings").hidden = false; byId("groups").hidden = false; byId("groups").replaceChildren(); byId("advanced-fields").replaceChildren();
  const advanced = byId("advanced-fields");
  const project = section("Project"); renderResources(project);
  renderSync(section("Project board"), advanced);
  const workflow = section("Workflow"); const activation = checkbox(workflow, "activation", "Use FlightCheck by default for coding work", data.values.activation === "default-for-coding"); help(activation, "Leave off to opt in for each task.");
  readers.push(result => {const value = activation.checked ? "default-for-coding" : "opt-in"; if (value !== data.values.activation) result.activation = value;});
  renderChecks(workflow); simple(workflow, "preview", "UI preview instructions", "textarea");
  const checkout = section("Checkout & Cleanup"), policy = data.values.checkout_policy;
  const mode = field(checkout, "checkout-mode", "Checkout choice", policy.mode, "text", [["native-choice", "Native choice (default)"], ["worktree-required", "Require a separate worktree"]]);
  const fallback = checkbox(checkout, "checkout-fallback", "Allow Git fallback when native checkout creation is unavailable", policy.git_fallback);
  const prefix = field(checkout, "checkout-prefix", "Branch prefix", policy.branch_prefix || "");
  const protectedBranches = field(checkout, "protected_branches", "Additional protected branches", data.values.protected_branches.filter(branch => branch !== data.values.default_branch).join(", ")); help(protectedBranches, "Default branch " + data.values.default_branch + " is always protected. Add other shared branches, separated by commas.");
  readers.push(result => {const value = {...policy, mode: mode.value, git_fallback: fallback.checked}; if (prefix.value.trim()) value.branch_prefix = prefix.value.trim(); else if (policy.branch_prefix) value.branch_prefix = null; if (JSON.stringify(value) !== JSON.stringify(policy)) result.checkout_policy = value; const branches = [...new Set(protectedBranches.value.split(",").map(s => s.trim()).filter(Boolean).concat(data.values.default_branch))].sort(); if (JSON.stringify(branches) !== JSON.stringify(data.values.protected_branches)) result.protected_branches = branches;});
  checkout.append(node("h3", "Future cleanup authority"));
  const cleanup = {};
  for (const [key, label] of [["local_branches", "Verified merged local branches"], ["remote_branches", "Verified merged actual remote branches"], ["temporary_worktrees", "Verified merged temporary worktrees"]]) cleanup[key] = checkbox(checkout, "cleanup-" + key, label, data.values.cleanup_policy[key]);
  checkout.append(node("p", "Each flight captures exact cleanup grants. Mandatory preservation and checkout protections always apply."));
  readers.push(result => {const value = {...data.values.cleanup_policy}; for (const [key, control] of Object.entries(cleanup)) value[key] = control.checked; if (JSON.stringify(value) !== JSON.stringify(data.values.cleanup_policy)) result.cleanup_policy = value;});
  const delivery = section("Evidence & Delivery"); simple(delivery, "evidence_dir", "Private evidence location"); help(byId("field-evidence_dir"), "Proof from checks and reviews; operational log lookup is in Project."); simple(delivery, "nit_tracker", "Minor follow-ups"); help(byId("field-nit_tracker"), "Nonblocking review follow-ups; project work belongs in the tracker.");
  simple(delivery, "review_client", "Review client", "text", [["", "Choose a client"], ["Codex", "Codex"], ["Claude", "Claude"]]);
  simple(delivery, "delivery", "Delivery policy", "text", [["Reviewed pull request; merge after required approval", "Pull request and approved merge"], ["Prepare review only; no provider writes", "Prepare review only"]]);
  simple(advanced, "reviewer_access", "Reviewer access", "textarea"); simple(advanced, "policy_reference", "Flight policy");
  advanced.append(node("p", "Flight policy governs development and delivery; the style guide covers coding conventions. Runtime requirements describe needed tools; the pinned executable is shown under Details."));
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
  byId("repository").textContent = "Default branch: " + data.values.default_branch + ". Checkout: " + data.repository.checkout + " · Git identity: " + data.repository.git_common_dir;
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
  rememberContext(); message("Review changes before saving.");
}
async function reload() {render(await api("read"));}
function changes() {const result = {}; for (const reader of readers) reader(result); if (!Object.keys(result).length) throw new Error("Change a value before reviewing"); return result;}
function invalidate() {plan = undefined; activePlan = undefined; byId("save").disabled = true; byId("adopt").disabled = true;}
function human(value, key) {
  if (value === undefined || value === null || value === "") return "Not set";
  if (typeof value === "boolean") return value ? "Enabled" : "Off";
  if (Array.isArray(value)) return value.map(item => typeof item === "object" && item.command ? item.name + ": " + commandText(item.command) + " (" + item.phase + ")" : human(item, key)).join("; ") || "None";
  if (typeof value === "object") return Object.entries(value).filter(([name]) => !name.endsWith("reference")).map(([name, item]) => (labels[name] || states[name] || name.replace(/_/g, " ")) + ": " + human(item, name)).join("; ") || "None";
  return friendlyStatuses[value] || states[value] || ({"default-for-coding": "On for coding work", "opt-in": "Opt in per task", "native-choice": "Native choice", "worktree-required": "Require a separate worktree", "disabled": "Off", "advisory": "Report and continue", "required": "Block if unavailable"})[value] || String(value);
}
function showPreview(result) {
  const effects = byId("effects"); effects.replaceChildren(); const list = node("ul");
  function difference(before, after, path) {
    if (equal(before, after) || path.at(-1).endsWith("reference")) return;
    const key = path.at(-1);
    if (["schema", "provider", "project_id", "field_id", "membership"].includes(key) && path[0] === "status_sync") return;
    if (before && after && typeof before === "object" && typeof after === "object" && !Array.isArray(before) && !Array.isArray(after)) {
      for (const name of new Set([...Object.keys(before), ...Object.keys(after)])) difference(before[name], after[name], [...path, name]); return;
    }
    const item = node("li"), caption = labels["resource-" + key] || labels[key] || states[key] || key.replace(/_/g, " ");
    const display = value => path.includes("options") && value ? friendlyStatuses[value] || "Saved status mapping" : human(value, key);
    item.append(node("b", caption + ": "), node("span", display(before) + " → " + display(after))); list.append(item);
  }
  for (const [key, change] of Object.entries(result.changes)) difference(change.before, change.after, [key]);
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
action("forget-settings", async () => {forgetContext(); capability = undefined; byId("settings").hidden = true; byId("locked").hidden = false; message("Settings navigation session cleared. Use the authorized launcher to edit again.");});
if (capability && context.task === taskFromPath && [context.project, context.task, context.session].every(Boolean)) reload().catch(error => message(error.message, true));
else message("Read-only card view. Start an explicitly authorized local Settings session to edit private configuration.");
