"""Focused real-client event flow with a small DOM fixture, not rendering proof."""
import copy
import http.server
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import threading
import unittest
from html.parser import HTMLParser
from unittest.mock import patch

import test_settings as fixtures


CLIENT = r'''
const fs = require("fs"), vm = require("vm"), readline = require("readline"), assert = require("assert/strict");
(async () => {
  const lines = readline.createInterface({input: process.stdin})[Symbol.asyncIterator]();
  const setup = JSON.parse((await lines.next()).value), ids = new Map(), all = [];
  let active;
  const root = {parent: null};
  class Element {
    constructor(tag) {this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {}; this.handlers = {}; this.attrs = {}; this.value = ""; this.disabled = false; this.checked = false; this.hidden = false; all.push(this);}
    set textContent(value) {this._text = String(value); this.children = [];} get textContent() {return (this._text || "") + this.children.map(child => child.textContent).join("");}
    set id(value) {this._id = value; ids.set(value, this);} get id() {return this._id;}
    append(...items) {for (const item of items) {this.children.push(item); item.parent = this;}}
    replaceChildren(...items) {for (const old of this.children) old.parent = null; this.children = []; this.append(...items);}
    setAttribute(key, value) {this.attrs[key] = String(value);}
    addEventListener(name, action) {(this.handlers[name] ||= []).push(action);}
    focus() {active = this;}
    showModal() {this.open = true;} close() {this.open = false;}
    async emit(name) {if (name === "click") assert.equal(this.disabled, false); for (const fn of this.handlers[name] || []) await fn({preventDefault() {}});}
  }
  for (const [id, spec] of Object.entries(setup.elements)) {const e = new Element(spec.tag); e.id = id; e.parent = root; e.disabled = "disabled" in spec.attrs; e.hidden = "hidden" in spec.attrs; e.attrs = spec.attrs;}
  const doc = {getElementById: id => {const e = ids.get(id); let p = e; while (p && p !== root) p = p.parent; return p === root ? e : null;}, createElement: tag => new Element(tag), querySelectorAll: () => all.filter(e => {let p = e; while (p && p !== root) p = p.parent; return p === root && e.dataset.key;})};
  const fragment = new URLSearchParams({cap: setup.token, ...setup.context}).toString();
  const navigations = [];
  const location = {hash: "#" + fragment, pathname: new URL(setup.base).pathname, assign: target => navigations.push(new URL(target, setup.base).href)};
  const storage = new Map();
  const sandbox = {document: doc, location, URL, URLSearchParams, Set, Date, sessionStorage: {getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key)}, history: {replaceState() {}}, fetch: (path, options) => fetch(new URL(path, setup.base), {...options, headers: {...options.headers, Origin: new URL(setup.base).origin}})};
  vm.runInNewContext(fs.readFileSync(setup.script, "utf8"), sandbox, {filename: setup.script});
  for (let n = 0; n < 200 && !ids.has("field-review_client"); n++) await new Promise(resolve => setTimeout(resolve, 10));
  assert(ids.has("field-review_client"), doc.getElementById("message").textContent);
  assert.equal(doc.getElementById("groups").children.length, 5);
  for (const name of ["preview", "save", "reload", "recover", "audit", "reconfigure", "adopt"]) assert.equal(doc.getElementById(name).tagName, "BUTTON");
  assert.equal(doc.getElementById("reference"), null);
  assert.equal(doc.getElementById("recovery").hidden, true);
  assert.equal(doc.getElementById("field-activation").type, "checkbox");
  for (const key of ["check-phase-0", "checkout-mode", "review_client", "delivery"]) assert.equal(doc.getElementById("field-" + key).tagName, "SELECT");
  for (const key of ["issue_tracker", "project_board", "style_guide", "documentation", "runbook", "logs"]) assert.equal(doc.getElementById("field-resource-" + key).tagName, "INPUT");
  assert.equal(doc.getElementById("field-resource-issue_tracker")._settingsValue.children[1].children[0].tagName, "A");
  for (const key of ["style_guide", "documentation", "runbook", "logs"]) assert.equal(doc.getElementById("browse-resource-" + key).textContent, "Browse");
  doc.getElementById("field-resource-style_guide").value = "https://example.invalid/old-style";
  await doc.getElementById("field-resource-style_guide").emit("input");
  assert.equal(doc.getElementById("browse-resource-style_guide").textContent, "Browse");
  await doc.getElementById("browse-resource-style_guide").emit("click"); await doc.getElementById("browse-cancel").emit("click");
  assert.equal(doc.getElementById("field-resource-style_guide").value, "https://example.invalid/old-style");
  const styleBefore = doc.getElementById("field-resource-style_guide").value;
  await doc.getElementById("browse-resource-style_guide").emit("click");
  assert.equal(doc.getElementById("resource-browser").open, true);
  const docsButton = doc.getElementById("browse-list").children.find(e => e.textContent === "docs/"); assert(docsButton); await docsButton.emit("click");
  const styleButton = doc.getElementById("browse-list").children.find(e => e.textContent === "style.md"); assert(styleButton); await styleButton.emit("click");
  assert.equal(doc.getElementById("field-resource-style_guide").value, "docs/style.md"); assert.equal(doc.getElementById("resource-browser").open, false);
  await doc.getElementById("browse-resource-documentation").emit("click");
  await doc.getElementById("browse-list").children.find(e => e.textContent === "docs/").emit("click");
  await doc.getElementById("browse-select").emit("click"); assert.equal(doc.getElementById("field-resource-documentation").value, "docs");
  const runbookBefore = doc.getElementById("field-resource-runbook").value;
  await doc.getElementById("browse-resource-runbook").emit("click"); await doc.getElementById("browse-cancel").emit("click"); assert.equal(doc.getElementById("field-resource-runbook").value, runbookBefore);
  doc.getElementById("field-review_client").value = "Claude";
  await doc.getElementById("settings").emit("submit");
  assert.equal(doc.getElementById("save").disabled, false, doc.getElementById("message").textContent);
  assert.match(doc.getElementById("effects").textContent, /Claude/);
  assert.equal(active.id, "effects");
  console.log("ready-for-concurrent-edit");
  await lines.next();
  await doc.getElementById("save").emit("click");
  assert.equal(navigations.length, 0);
  assert.equal(doc.getElementById("field-review_client").value, "Claude");
  assert.equal(doc.getElementById("message").attrs.role, "alert");
  assert.match(doc.getElementById("message").textContent, /stale/i);
  assert.equal(active.id, "message");
  assert.equal(doc.getElementById("save").disabled, true);
  await doc.getElementById("reload").emit("click");
  assert.equal(doc.getElementById("field-review_client").value, "Concurrent owner choice");
  doc.getElementById("field-review_client").value = "Codex";
  await doc.getElementById("settings").emit("submit");
  {const before = navigations.length; await doc.getElementById("save").emit("click"); assert.equal(navigations.length, before + 1); assert.equal(navigations.at(-1), new URL("../", setup.base).href); await doc.getElementById("reload").emit("click");}

  assert.equal(doc.getElementById("field-review_client").value, "Codex");
  // Exercise the native typed controls through the actual HTTP update path.
  doc.getElementById("field-resource-style_guide").value = "docs/style.md";
  doc.getElementById("field-activation").checked = true;
  doc.getElementById("field-check-command-0").value = "python3 -B -m unittest 'tests with spaces'";
  doc.getElementById("field-check-phase-0").value = "authoritative";
  doc.getElementById("field-checkout-mode").value = "worktree-required";
  doc.getElementById("field-checkout-fallback").checked = true;
  doc.getElementById("field-cleanup-local_branches").checked = true;
  doc.getElementById("field-resource-project_board").value = "https://github.com/orgs/example/projects/7";
  await doc.getElementById("field-resource-project_board").emit("input");
  await doc.getElementById("discover-board").emit("click");
  assert.match(doc.getElementById("board-name").textContent, /Team delivery/);
  assert.equal(doc.getElementById("board-manual").hidden, true);
  doc.getElementById("field-sync-enabled").checked = true;
  await doc.getElementById("field-sync-enabled").emit("change");
  assert.equal(doc.getElementById("sync-mappings").hidden, false);
  assert.equal(doc.getElementById("field-sync-todo").tagName, "SELECT");
  assert.equal(doc.getElementById("field-sync-todo").children[1].textContent, "Queued");
  for (const state of ["todo", "ready", "in_progress", "review", "done"]) doc.getElementById("field-sync-" + state).value = "OPTION_" + state;
  doc.getElementById("field-sync-todo").value = "OPTION_ready";
  doc.getElementById("field-sync-ready").value = "OPTION_todo";
  await doc.getElementById("settings").emit("submit");
  assert.equal(doc.getElementById("save").disabled, false, doc.getElementById("message").textContent);
  assert.equal(doc.getElementById("groups").hidden, true);
  assert.match(doc.getElementById("effects").textContent, /docs\/style.md/);
  assert(!doc.getElementById("change-summary").textContent.includes("SYNTHETIC_PROJECT"));
  assert(!doc.getElementById("change-summary").textContent.includes("OPTION_"));
  await doc.getElementById("cancel").emit("click");
  assert.equal(doc.getElementById("groups").hidden, false);
  assert.equal(doc.getElementById("save").disabled, true);
  await doc.getElementById("settings").emit("submit");
  {const before = navigations.length; await doc.getElementById("save").emit("click"); assert.equal(navigations.length, before + 1); assert.equal(navigations.at(-1), new URL("../", setup.base).href); await doc.getElementById("reload").emit("click");}

  assert.equal(doc.getElementById("field-activation").checked, true);
  assert.equal(doc.getElementById("field-sync-todo").value, "OPTION_ready");
    // Hide mappings without dropping the configured values or required policy.
  doc.getElementById("field-sync-mode").value = "required";
  doc.getElementById("field-sync-enabled").checked = false;
  await doc.getElementById("field-sync-enabled").emit("change");
  assert.equal(doc.getElementById("sync-mappings").hidden, true);
  await doc.getElementById("settings").emit("submit");
  {const before = navigations.length; await doc.getElementById("save").emit("click"); assert.equal(navigations.length, before + 1); assert.equal(navigations.at(-1), new URL("../", setup.base).href); await doc.getElementById("reload").emit("click");}
  // Changing the board while off must not let a later reload bind the old IDs.
  doc.getElementById("field-resource-project_board").value = "https://github.com/orgs/example/projects/8";
  await doc.getElementById("field-resource-project_board").emit("input");
  await doc.getElementById("settings").emit("submit");
  {const before = navigations.length; await doc.getElementById("save").emit("click"); assert.equal(navigations.length, before + 1); assert.equal(navigations.at(-1), new URL("../", setup.base).href); await doc.getElementById("reload").emit("click");}
  // An unrelated later save must not silently bind the new URL to the old IDs.
  doc.getElementById("field-resource-documentation").value = "docs/new-guide.md";
  await doc.getElementById("settings").emit("submit");
  {const before = navigations.length; await doc.getElementById("save").emit("click"); assert.equal(navigations.length, before + 1); assert.equal(navigations.at(-1), new URL("../", setup.base).href); await doc.getElementById("reload").emit("click");}
  doc.getElementById("field-sync-enabled").checked = true;
  await doc.getElementById("field-sync-enabled").emit("change");
  await doc.getElementById("settings").emit("submit");
  assert.equal(doc.getElementById("save").disabled, true);
  assert.match(doc.getElementById("message").textContent, /connection for this board/);
  // Confirm an existing manual connection without inventing a changed ID.
  await doc.getElementById("confirm-board").emit("click");
  await doc.getElementById("settings").emit("submit");
  assert.equal(doc.getElementById("save").disabled, false, doc.getElementById("message").textContent);
  await doc.getElementById("reload").emit("click");

  console.log(JSON.stringify({groups: 5, typedFormSave: true, cancelPreview: true, conflictFocused: true, staleSaveRefused: true, concurrentChoicePreserved: true, explicitFreshSave: true}));
  process.exit(0);
})().catch(error => {console.error(error.stack); process.exit(1);});
'''


NAVIGATION_CLIENT = r'''
const fs = require("fs"), vm = require("vm"), assert = require("assert/strict");
(async () => {
 const setup = JSON.parse(fs.readFileSync(0, "utf8")), storage = new Map();
 const source = fs.readFileSync(setup.script, "utf8");
 async function load(fragment, cache = storage, pathname = new URL(setup.base).pathname) {
  const ids = new Map(), root = {};
  class Element {
   constructor(tag) {this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {}; this.handlers = {}; this.attrs = {}; this.value = ""; this.checked = false; this.disabled = false; this.hidden = false;}
   set id(value) {this._id = value; ids.set(value, this);} get id() {return this._id;}
   set textContent(value) {this._text = String(value); this.children = [];} get textContent() {return (this._text || "") + this.children.map(e => e.textContent).join("");}
   append(...items) {this.children.push(...items);} replaceChildren(...items) {this.children = items;}
   setAttribute(k, v) {this.attrs[k] = v;} addEventListener(k, fn) {(this.handlers[k] ||= []).push(fn);} focus() {}
   showModal() {this.open = true;} close() {this.open = false;}
   async emit(k) {for (const fn of this.handlers[k] || []) await fn({preventDefault() {}});}
  }
  for (const [id, spec] of Object.entries(setup.elements)) {const e = new Element(spec.tag); e.id = id; e.attrs = spec.attrs; e.hidden = "hidden" in spec.attrs; e.disabled = "disabled" in spec.attrs;}
  const navigations = [];
  const sandbox = {URL, URLSearchParams, Date, Set, location: {hash: fragment, pathname, assign: target => navigations.push(new URL(target, setup.base).href)}, history: {replaceState() {}}, sessionStorage: {getItem: k => cache.get(k) || null, setItem: (k, v) => cache.set(k, v), removeItem: k => cache.delete(k)}, document: {getElementById: id => ids.get(id), createElement: t => new Element(t)}, fetch: (path, options) => fetch(new URL(path, setup.base), {...options, headers: {...options.headers, Origin: new URL(setup.base).origin}})};
  vm.runInNewContext(source, sandbox);
  for (let n = 0; n < 100 && ids.get("message").textContent === ""; n++) await new Promise(r => setTimeout(r, 10));
  for (let n = 0; n < 100 && fragment && !ids.has("field-review_client"); n++) await new Promise(r => setTimeout(r, 10));
  ids.navigations = navigations; return ids;
 }
 const fragment = "#" + new URLSearchParams({cap: setup.token, ...setup.context});
 let ids = await load(fragment); assert(ids.has("field-review_client"));
 assert.equal(storage.size, 1);
 const returnURL = new URL(ids.get("task-status-link").attrs.href, setup.base);
 const task = await fetch(returnURL); assert.equal(task.status, 200);
 const html = await task.text(); assert.match(html, /<footer[\s\S]*id="settings-link"[\s\S]*\[ Settings \][\s\S]*<\/footer>/);
 assert(!/<header[\s\S]*id="settings-link"[\s\S]*<\/header>/.test(html));
 assert.equal(ids.get("task-status-link").attrs.href, "../");
 assert(!html.includes(setup.token));
 const href = html.match(/id="settings-link" href="([^"]+)"/)[1];
 assert.equal(new URL(href, returnURL).href, setup.base);
 ids = await load("");
 for (let n=0;n<100 && !ids.has("field-review_client");n++) await new Promise(r=>setTimeout(r,10));
 assert(ids.has("field-review_client"), ids.get("message").textContent);
 ids.get("field-review_client").value = "Claude"; await ids.get("settings").emit("submit"); assert.equal(ids.get("save").disabled, false, ids.get("message").textContent); await ids.get("save").emit("click");
 assert.deepEqual(ids.navigations, [returnURL.href]);
 const publicTab = await load("", new Map()); assert.equal(publicTab.has("field-review_client"), false); assert.match(publicTab.get("message").textContent, /Read-only/);
 const wrongTask = await load("", storage, "/task/another-flight/settings/"); assert.equal(wrongTask.has("field-review_client"), false);
 const key = [...storage.keys()][0], wrong = JSON.parse(storage.get(key)); wrong.context.project = "wrong-project"; storage.set(key, JSON.stringify(wrong));
 const wrongProject = await load("");
 for(let n=0;n<100 && storage.has(key);n++) await new Promise(r=>setTimeout(r,10));
 assert.equal(storage.has(key), false); assert.equal(wrongProject.has("field-review_client"), false);
 console.log(JSON.stringify({taskHeaderToAuthorizedSettings: true, settingsToTaskStatus: true, roundTripSave: true, publicCardLocked: true, crossTaskLocked: true, crossProject403Cleared: true, capabilityNotInPublicPage: true}));
})().catch(e=>{console.error(e.stack);process.exit(1)});
'''


class SettingsUIEventsTests(unittest.TestCase):
    config_fixture = fixtures.SettingsTests.config_fixture
    config_module = fixtures.SettingsTests.config_module
    config_git = fixtures.SettingsTests.config_git
    config_cli = fixtures.SettingsTests.config_cli
    service = fixtures.SettingsTests.service
    save = fixtures.SettingsTests.save

    def test_keyboard_preview_stale_conflict_and_fresh_save(self):
        class Surface(HTMLParser):
            def __init__(self): super().__init__(); self.elements = {}
            def handle_starttag(self, tag, attrs):
                values = dict(attrs)
                if 'id' in values: self.elements[values['id']] = {'tag': tag, 'attrs': values}
        with self.config_fixture() as (area, root, engine, installed, cli, supplied):
            from flightcheck_cli.settings import Handler
            surface = Surface(); surface.feed((fixtures.PRODUCT / 'status-card/settings.html').read_text())
            service = self.service(engine, root)
            docs = root / "docs"; docs.mkdir(); (docs / "style.md").write_text("Synthetic style guide")
            class Provider:
                def query(self, query, variables):
                    return {'project': {'id': 'SYNTHETIC_PROJECT', 'title': 'Team delivery', 'url': 'https://github.com/orgs/example/projects/7', 'closed': False,
                            'fields': {'pageInfo': {'hasNextPage': False}, 'nodes': [{'id': 'SYNTHETIC_STATUS', 'name': 'Status', 'options': [{'id': 'OPTION_' + key, 'name': name} for key, name in [('todo', 'Queued'), ('ready', 'Ready'), ('in_progress', 'Building'), ('review', 'Review'), ('done', 'Complete')]]}]}}}
            with patch.object(service, 'board_provider', return_value=Provider()), http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
                server.settings, server.route, server.assets = service, '/task/settings-flight/settings/', fixtures.PRODUCT / 'status-card'
                thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
                process = subprocess.Popen([shutil.which('node'), '-e', CLIENT], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    setup = {'base': 'http://127.0.0.1:' + str(server.server_port) + server.route, 'token': service.token, 'context': service.context, 'elements': surface.elements, 'script': str(fixtures.PRODUCT / 'status-card/settings.js')}
                    process.stdin.write(json.dumps(setup) + '\n'); process.stdin.flush()
                    ready, _, _ = select.select([process.stdout], [], [], 15)
                    self.assertTrue(ready, 'Client did not reach its public preview checkpoint')
                    line = process.stdout.readline().strip()
                    if line != 'ready-for-concurrent-edit':
                        _, error = process.communicate(timeout=10); self.fail('Client preview failed: ' + line + error)
                    other = self.service(engine, root)
                    self.save(other, {'review_client': 'Concurrent owner choice'})
                    process.stdin.write('continue\n'); process.stdin.flush()
                    output, error = process.communicate(timeout=20)
                    self.assertEqual(process.returncode, 0, output + error)
                    result = json.loads(output.strip())
                    self.assertTrue(result['staleSaveRefused']); self.assertTrue(result['conflictFocused']); self.assertTrue(result['concurrentChoicePreserved']); self.assertTrue(result['explicitFreshSave'])
                    values = cli.configuration_model(engine, root).snapshot(root)['values']
                    self.assertEqual(values['review_client'], 'Codex')
                    self.assertEqual(values['resources']['style_guide'], 'docs/style.md')
                    self.assertEqual(values['checks'][0]['command'], ['python3', '-B', '-m', 'unittest', 'tests with spaces'])
                    self.assertEqual(values['checks'][0]['phase'], 'authoritative')
                    self.assertEqual(values['activation'], 'default-for-coding')
                    self.assertIn('#settings-', values['activation_reference'])
                    self.assertTrue(values['cleanup_policy']['local_branches'])
                    self.assertFalse(values['cleanup_policy']['remote_branches'])
                    self.assertEqual(values['checkout_policy']['mode'], 'worktree-required')
                    self.assertIn('#settings-', values['checkout_policy']['fallback_reference'])
                    self.assertEqual(values['status_sync']['mode'], 'disabled')
                    self.assertEqual(values['status_sync']['options']['todo'], 'OPTION_ready')
                finally:
                    if process.poll() is None: process.kill(); process.communicate()
                    server.shutdown(); thread.join()

    def test_authorized_task_navigation_round_trip(self):
        class Surface(HTMLParser):
            def __init__(self): super().__init__(); self.elements = {}
            def handle_starttag(self, tag, attrs):
                values = dict(attrs)
                if 'id' in values: self.elements[values['id']] = {'tag': tag, 'attrs': values}
        with self.config_fixture() as (_, root, engine, installed, cli, supplied):
            from flightcheck_cli.settings import Handler
            class NavigationHandler(Handler):
                def do_GET(self):
                    if self.path == '/task/settings-flight/':
                        self.send(200, (fixtures.PRODUCT / 'status-card/task.html').read_bytes(), 'text/html; charset=utf-8')
                    else:
                        super().do_GET()
            surface = Surface(); surface.feed((fixtures.PRODUCT / 'status-card/settings.html').read_text())
            service = self.service(engine, root)
            with http.server.ThreadingHTTPServer(('127.0.0.1', 0), NavigationHandler) as server:
                server.settings, server.route, server.assets = service, '/task/settings-flight/settings/', fixtures.PRODUCT / 'status-card'
                thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
                try:
                    setup = {'base': 'http://127.0.0.1:' + str(server.server_port) + server.route, 'token': service.token, 'context': service.context, 'elements': surface.elements, 'script': str(fixtures.PRODUCT / 'status-card/settings.js')}
                    process = subprocess.run([shutil.which('node'), '-e', NAVIGATION_CLIENT], input=json.dumps(setup), capture_output=True, text=True, timeout=20)
                    self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                    self.assertTrue(all(json.loads(process.stdout).values()))
                    self.assertEqual(service.read()['values']['review_client'], 'Claude')
                finally:
                    server.shutdown(); thread.join()


if __name__ == '__main__': unittest.main()
