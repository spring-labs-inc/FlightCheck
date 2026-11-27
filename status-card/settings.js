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
let current, plan, readers = [], labels = {};
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
  const url = validDestination(value); if (!url) return;
  const row = node("p", label + " "), arrow = node("a", "↗"); arrow.href = url;
  arrow.target = "_blank"; arrow.rel = "noopener noreferrer"; arrow.setAttribute("aria-label", "Open " + label); row.append(arrow); parent.append(row);
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
  if (type === "checkbox") {row.className += " settings-toggle"; row.append(control, caption);} else {const value = node("div"); value.className = "settings-value"; value.append(control); control._settingsValue = value; row.append(caption, value);}
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
function validDestination(value) {
  try {const url = new URL(value); return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password ? url.href : null;} catch (_) {return null;}
}
let picker;
function closePicker() {byId("resource-browser").close(); const target = picker?.input; picker = undefined; target?.focus();}
function pickerSelection(path) {
  picker.selection = path;
  byId("browse-selection").textContent = path ? "Selected: " + (path === "." ? "Project folder" : path) : "No selection";
  byId("browse-select").disabled = !path; byId("browse-clear").disabled = !path;
  for (const row of byId("browse-list").children) row.setAttribute("aria-pressed", row.dataset.path === path ? "true" : "false");
}
async function showFolder(path, initial = false) {
  const activePicker = picker;
  const data = await api("browse", initial ? {field: activePicker.field, start: true, current: activePicker.input.value} : {field: activePicker.field, path});
  if (picker !== activePicker) return;
  picker.directory = data.directory; picker.parent = data.parent;
  const breadcrumb = byId("browse-directory"); breadcrumb.replaceChildren();
  const parts = data.directory ? data.directory.split("/") : [];
  for (let index = -1; index < parts.length; index++) {
    if (index >= 0) breadcrumb.append(node("span", "/"));
    const target = parts.slice(0, index + 1).join("/");
    const item = node("button", index === -1 ? "Project" : parts[index]); item.type = "button";
    item.addEventListener("click", async () => {try {await showFolder(target);} catch (error) {byId("browse-message").textContent = error.message;}}); breadcrumb.append(item);
  }
  byId("browse-message").textContent = data.truncated ? "Showing a limited list. Enter the path directly if needed." : "";
  byId("browse-up").disabled = data.parent === null;
  const list = byId("browse-list"); list.replaceChildren();
  for (const entry of data.entries) {
    if (entry.kind === "file" && data.kind === "directory") continue;
    const button = node("button", entry.name + (entry.kind === "directory" ? "/" : "")); button.type = "button"; button.dataset.path = entry.path;
    button.addEventListener("click", async () => {try {if (entry.kind === "directory") await showFolder(entry.path); else pickerSelection(entry.path);} catch (error) {byId("browse-message").textContent = error.message;}}); list.append(button);
  }
  if (!list.children.length) list.append(node("p", "No matching files or folders."));
  pickerSelection(data.selection || (data.kind === "file" ? null : data.directory || "."));
}
async function choosePath(path) {
  const activePicker = picker;
  const data = await api("browse", {field: activePicker.field, path, select: true});
  if (picker !== activePicker) return;
  const input = activePicker.input; input.value = data.selected; input._refreshLocation?.(); input._resourceUpdate?.(); invalidate(); closePicker();
}
function locationActions(input, field, kind, alwaysBrowse = false) {
  const actions = node("span"); actions.className = "location-actions"; input._settingsValue.append(actions);
  function refresh() {
    actions.replaceChildren(); const url = validDestination(input.value.trim());
    if (!alwaysBrowse && (url || !kind)) {
      const open = node("a", "↗"); open.setAttribute("aria-label", "Open " + labels[input.dataset.key]); open.title = "Open destination"; open.target = "_blank"; open.rel = "noopener noreferrer";
      if (url) open.href = url; else {open.setAttribute("aria-disabled", "true"); open.title = "Enter a credential-free HTTP or HTTPS URL";}
      actions.append(open);
    } else {
      const browse = node("button", "Browse"); browse.type = "button"; browse.id = "browse-" + input.dataset.key;
      browse.setAttribute("aria-label", "Browse for " + labels[input.dataset.key]);
      browse.addEventListener("click", async () => {
        picker = {input, field}; byId("resource-browser-title").textContent = "Choose " + labels[input.dataset.key]; byId("resource-browser").showModal(); byId("browse-list").replaceChildren(); byId("browse-message").textContent = "Opening project folder…";
        try {const active = picker; await showFolder("", true); if (picker === active) byId("browse-cancel").focus();} catch (error) {byId("browse-message").textContent = error.message;}
      }); actions.append(browse);
    }
  }
  input._refreshLocation = refresh; input.addEventListener("input", refresh); refresh();
}
function resourceControl(parent, key, label) {
  const existing = current.values.resources?.[key];
  const value = typeof existing === "string" ? existing : existing?.url || "";
  const input = field(parent, "resource-" + key, label, value); input.placeholder = "Not configured";
  const kind = ({style_guide: "file", documentation: "directory", runbook: "file", logs: "any"})[key] || (["issue_tracker", "project_board"].includes(key) ? null : "any");
  locationActions(input, "resources." + key, kind, ["style_guide", "documentation", "runbook", "logs"].includes(key));
  let clearUnavailable = false;
  const status = node("span"); status.className = "settings-hint"; input._settingsRow.append(status);
  let clear;
  if (existing?.unavailable) {
    clear = node("button", "Clear saved problem"); clear.type = "button"; clear.className = "clear-problem";
    clear.addEventListener("click", () => {clearUnavailable = true; update(); invalidate();}); input._settingsRow.append(clear);
  }
  function update() {
    const problem = !input.value.trim() && existing?.unavailable && !clearUnavailable;
    status.textContent = problem ? "Previously unavailable: " + existing.unavailable + ". Clear saved problem removes this note on Save; the location remains not configured." : clearUnavailable && !input.value.trim() ? "Not configured · saved problem will be cleared on Save." : "";
    status.className = "settings-hint" + (problem ? " problem-text" : "");
    if (clear) clear.hidden = !problem;
  }
  input._resourceUpdate = update; input.addEventListener("input", update); update();
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
  current = data; readers = []; labels = {}; friendlyStatuses = {}; plan = undefined;
  byId("save").disabled = true; byId("review").hidden = true; byId("preview").hidden = false;
  byId("recovery").hidden = data.status !== "recovery_required";
  if (data.status !== "configuration") {message(data.reason, data.status === "recovery_required"); byId("locked").hidden = data.status === "recovery_required"; byId("settings").hidden = true; return;}
  if (data.authorization_scope !== "project") {byId("settings").hidden = true; byId("locked").hidden = false; message("Authorize project Settings to apply changes to current and future work."); return;}
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
  checkout.append(node("h3", "Automatic cleanup"));
  const cleanup = {};
  for (const [key, label] of [["local_branches", "Verified merged local branches"], ["remote_branches", "Verified merged actual remote branches"], ["temporary_worktrees", "Verified merged temporary worktrees"]]) cleanup[key] = checkbox(checkout, "cleanup-" + key, label, data.values.cleanup_policy[key]);
  checkout.append(node("p", "Each flight captures exact cleanup grants. Mandatory preservation and checkout protections always apply."));
  readers.push(result => {const value = {...data.values.cleanup_policy}; for (const [key, control] of Object.entries(cleanup)) value[key] = control.checked; if (JSON.stringify(value) !== JSON.stringify(data.values.cleanup_policy)) result.cleanup_policy = value;});
  const delivery = section("Evidence & Delivery"); simple(delivery, "evidence_dir", "Private evidence location"); help(byId("field-evidence_dir"), "Private host path for check/review proof; enter its existing path directly. Project browsing is for project resources."); delivery.append(node("p", "Minor follow-ups use the main tracker unless overridden in Advanced."));
  simple(delivery, "review_client", "Review client", "text", [["", "Choose a client"], ["Codex", "Codex"], ["Claude", "Claude"]]);
  simple(delivery, "delivery", "Delivery policy", "text", [["Reviewed pull request; merge after required approval", "Pull request and approved merge"], ["Prepare review only; no provider writes", "Prepare review only"]]);
  const customNits = checkbox(advanced, "nit-override", "Use a separate minor-follow-up location", data.values.nit_tracker !== null && data.values.nit_tracker !== undefined);
  const nitLocation = field(advanced, "nit_tracker", "Minor-follow-up override", data.values.nit_tracker || "");
  locationActions(nitLocation, "nit_tracker", "any");
  function nitVisibility() {nitLocation._settingsRow.hidden = !customNits.checked;}
  customNits.addEventListener("change", nitVisibility); nitVisibility();
  readers.push(result => {const value = customNits.checked ? nitLocation.value.trim() : null; if (customNits.checked && !value) throw new Error("Choose a minor-follow-up override or use the main tracker"); if (value !== data.values.nit_tracker) result.nit_tracker = value;});
  simple(advanced, "reviewer_access", "Reviewer access", "textarea"); simple(advanced, "policy_reference", "Workflow instructions"); locationActions(byId("field-policy_reference"), "policy_reference", "file");
  advanced.append(node("p", "Workflow instructions governs development and delivery; the style guide covers coding conventions. Runtime requirements describe needed tools; the pinned executable is shown under Details."));
  const runtimes = field(advanced, "required_runtimes", "Required runtimes", (data.values.required_runtimes || []).join("\n"), "textarea"); help(runtimes, "One existing runtime requirement per line. Settings does not install or execute runtimes.");
  readers.push(result => {const value = runtimes.value.split("\n").map(row => row.trim()).filter(Boolean); if (JSON.stringify(value) !== JSON.stringify(data.values.required_runtimes || [])) result.required_runtimes = value;});
  byId("capabilities").textContent = "Runtime validation: " + data.runtime.status + ". Configuration decisions and validation are retained internally.";
  byId("provenance").replaceChildren();
  for (const [key, meta] of Object.entries(data.values._flightcheck?.fields || {})) {const detail = node("p", key + ": " + meta.source + " · " + meta.scope + " · " + (meta.confirmed ? "confirmed" : "suggestion") + " · validation: " + meta.last_validation.status + " (" + meta.last_validation.validator + ")"); byId("provenance").append(detail);}
  const suggestions = Object.entries(data.values._flightcheck?.fields || {}).filter(([key, meta]) => !meta.confirmed && (key.startsWith("resources.") || ["activation", "checks", "preview", "checkout_policy", "cleanup_policy", "status_sync", "required_runtimes", "evidence_dir", "review_client", "reviewer_access", "delivery", "nit_tracker", "policy_reference"].includes(key))).map(([key]) => key);
  if (suggestions.length) {
    const confirm = checkbox(byId("provenance"), "confirm-suggestions", "Confirm displayed suggestions", false);
    readers.push(result => {if (confirm.checked) for (const key of suggestions) {if (key.startsWith("resources.")) {const name = key.slice(10); result.resources = {[name]: data.values.resources[name], ...result.resources};} else if (!(key in result)) result[key] = data.values[key];}});
  }
  rememberContext(); message("Review changes before saving.");
}
async function reload() {render(await api("read"));}
function changes() {const result = {}; for (const reader of readers) reader(result); if (!Object.keys(result).length) throw new Error("Change a value before reviewing"); return result;}
function invalidate() {plan = undefined; byId("save").disabled = true;}
function human(value, key) {
  if (value === undefined || value === null || value === "") return "Not set";
  if (typeof value === "boolean") return value ? "Enabled" : "Off";
  if (Array.isArray(value)) return value.map(item => typeof item === "object" && item.command ? item.name + ": " + commandText(item.command) + " (" + item.phase + ")" : human(item, key)).join("; ") || "None";
  if (typeof value === "object") return Object.entries(value).filter(([name]) => !name.endsWith("reference")).map(([name, item]) => (labels[name] || states[name] || name.replace(/_/g, " ")) + ": " + human(item, name)).join("; ") || "None";
  return friendlyStatuses[value] || states[value] || ({"default-for-coding": "On for coding work", "opt-in": "Opt in per task", "native-choice": "Native choice", "worktree-required": "Require a separate worktree", "disabled": "Off", "advisory": "Report and continue", "required": "Block if unavailable"})[value] || String(value);
}
function showPreview(result) {
  const effects = byId("effects"); effects.replaceChildren(); const list = node("ul"); list.id = "change-summary";
  function difference(before, after, path) {
    if (equal(before, after) || path.at(-1).endsWith("reference")) return;
    const key = path.at(-1);
    if (path[0] === "resources" && key === "project_board") {
      const location = value => typeof value === "string" ? value : value?.url || (value?.unavailable ? "Unavailable" : "Not configured");
      const item = node("li"); item.append(node("b", "Board: "), node("span", location(before) === location(after) ? "Connection confirmed or updated" : location(before) + " → " + location(after))); list.append(item); return;
    }
    if (["schema", "provider", "project_id", "field_id", "membership"].includes(key) && path[0] === "status_sync") return;
    if (before && after && typeof before === "object" && typeof after === "object" && !Array.isArray(before) && !Array.isArray(after)) {
      for (const name of new Set([...Object.keys(before), ...Object.keys(after)])) difference(before[name], after[name], [...path, name]); return;
    }
    const item = node("li"), caption = labels["resource-" + key] || labels[key] || states[key] || key.replace(/_/g, " ");
    const display = value => path.includes("options") && value ? friendlyStatuses[value] || "Saved status mapping" : human(value, key);
    item.append(node("b", caption + ": "), node("span", display(before) + " → " + display(after))); list.append(item);
  }
  for (const [key, change] of Object.entries(result.changes)) difference(change.before, change.after, [key]);
  effects.append(list);
  for (const text of result.effects.deferred || []) effects.append(node("p", text));
  byId("groups").hidden = true; byId("review").hidden = false; byId("preview").hidden = true; byId("save").disabled = false; effects.focus();
}
function action(id, fn) {byId(id).addEventListener("click", async () => {try {await fn();} catch (error) {invalidate(); message(error.message + ". Reload current values and preview again.", true); byId("message").focus();}});}
byId("settings").addEventListener("submit", async event => {event.preventDefault(); try {const result = await api("preview", {changes: changes(), expected_revision: current.revision}); plan = result.plan_id; showPreview(result); message("Changes ready to save.");} catch (error) {invalidate(); message(error.message, true); byId("message").focus();}});
byId("settings").addEventListener("input", invalidate);
byId("settings").addEventListener("change", invalidate);
action("save", async () => {await api("apply", {plan_id: plan}); location.assign("../");});
action("cancel", async () => {byId("review").hidden = true; byId("groups").hidden = false; byId("preview").hidden = false; invalidate(); byId("preview").focus();});
action("browse-up", async () => {try {await showFolder(picker.parent);} catch (error) {byId("browse-message").textContent = error.message;}});
action("browse-select", async () => {try {await choosePath(picker.selection);} catch (error) {byId("browse-message").textContent = error.message;}});
action("browse-clear", async () => {pickerSelection(null);});
action("browse-cancel", closePicker);
byId("resource-browser").addEventListener("cancel", event => {event.preventDefault(); closePicker();});
action("reload", reload); action("recover", async () => {await api("recover", {}); await reload();});
action("audit", async () => {
  const report = await api("audit", {remote: byId("audit-remote").checked}); byId("audit-report").textContent = JSON.stringify(report, null, 2); byId("audit-destinations").replaceChildren();
  const seen = new Set(); function links(value, path) {if (typeof value === "string" && !seen.has(value)) {seen.add(value); destination(byId("audit-destinations"), path, value);} else if (value && typeof value === "object") for (const [key, item] of Object.entries(value)) links(item, path + "." + key);}
  links(report, "Audit destination"); byId("audit-report").focus();
});
action("forget-settings", async () => {forgetContext(); capability = undefined; byId("settings").hidden = true; byId("locked").hidden = false; message("Settings navigation session cleared. Use the authorized launcher to edit again.");});
if (capability && context.task === taskFromPath && [context.project, context.task, context.session].every(Boolean)) reload().catch(error => message(error.message, true));
else message("Read-only view. Authorize Settings for this project to edit its configuration.");
