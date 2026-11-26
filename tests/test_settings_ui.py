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
    async emit(name) {if (name === "click") assert.equal(this.disabled, false); for (const fn of this.handlers[name] || []) await fn({preventDefault() {}});}
  }
  for (const [id, spec] of Object.entries(setup.elements)) {const e = new Element(spec.tag); e.id = id; e.parent = root; e.disabled = "disabled" in spec.attrs; e.hidden = "hidden" in spec.attrs; e.attrs = spec.attrs;}
  const doc = {getElementById: id => ids.get(id) || null, createElement: tag => new Element(tag), querySelectorAll: () => all.filter(e => {let p = e; while (p && p !== root) p = p.parent; return p === root && e.dataset.key;})};
  const fragment = new URLSearchParams({cap: setup.token, ...setup.context}).toString();
  const location = {hash: "#" + fragment, pathname: new URL(setup.base).pathname};
  const sandbox = {document: doc, location, URL, URLSearchParams, Set, history: {replaceState() {}}, fetch: (path, options) => fetch(new URL(path, setup.base), {...options, headers: {...options.headers, Origin: new URL(setup.base).origin}})};
  vm.runInNewContext(fs.readFileSync(setup.script, "utf8"), sandbox, {filename: setup.script});
  for (let n = 0; n < 200 && !ids.has("field-review_client"); n++) await new Promise(resolve => setTimeout(resolve, 10));
  assert(ids.has("field-review_client"), doc.getElementById("message").textContent);
  assert.equal(doc.getElementById("groups").children.length, 4);
  for (const name of ["preview", "save", "reload", "recover", "audit", "reconfigure", "adopt"]) assert.equal(doc.getElementById(name).tagName, "BUTTON");
  assert.equal(doc.getElementById("reference"), null);
  assert.equal(doc.getElementById("recovery").hidden, true);
  assert.equal(doc.getElementById("field-activation").type, "checkbox");
  for (const key of ["check-phase-0", "checkout-mode", "sync-board", "sync-todo", "review_client", "delivery"]) assert.equal(doc.getElementById("field-" + key).tagName, "SELECT");
  for (const key of ["issue_tracker", "project_board", "style_guide", "documentation", "runbook", "logs"]) assert.equal(doc.getElementById("field-resource-" + key).tagName, "INPUT");
  doc.getElementById("field-review_client").value = "Claude";
  await doc.getElementById("settings").emit("submit");
  assert.equal(doc.getElementById("save").disabled, false);
  assert.match(doc.getElementById("effects").textContent, /Claude/);
  assert.equal(active.id, "effects");
  console.log("ready-for-concurrent-edit");
  await lines.next();
  await doc.getElementById("save").emit("click");
  assert.equal(doc.getElementById("message").attrs.role, "alert");
  assert.match(doc.getElementById("message").textContent, /stale/i);
  assert.equal(active.id, "message");
  assert.equal(doc.getElementById("save").disabled, true);
  await doc.getElementById("reload").emit("click");
  assert.equal(doc.getElementById("field-review_client").value, "Concurrent owner choice");
  doc.getElementById("field-review_client").value = "Codex";
  await doc.getElementById("settings").emit("submit");
  await doc.getElementById("save").emit("click");
  assert.match(doc.getElementById("message").textContent, /Saved future defaults/);
  assert.equal(doc.getElementById("field-review_client").value, "Codex");
  // Exercise the native typed controls through the actual HTTP update path.
  doc.getElementById("field-resource-style_guide").value = "docs/style.md";
  doc.getElementById("field-activation").checked = true;
  doc.getElementById("field-check-command-0").value = "python3 -B -m unittest 'tests with spaces'";
  doc.getElementById("field-check-phase-0").value = "authoritative";
  doc.getElementById("field-checkout-mode").value = "worktree-required";
  doc.getElementById("field-checkout-fallback").checked = true;
  doc.getElementById("field-cleanup-local_branches").checked = true;
  doc.getElementById("field-sync-project-id").value = "SYNTHETIC_PROJECT";
  doc.getElementById("field-sync-field-id").value = "SYNTHETIC_STATUS";
  for (const state of ["todo", "ready", "in_progress", "review", "done"]) doc.getElementById("field-sync-option-" + state).value = "OPTION_" + state;
  await doc.getElementById("configure-board").emit("click");
  doc.getElementById("field-sync-enabled").checked = true;
  await doc.getElementById("field-sync-enabled").emit("change");
  doc.getElementById("field-sync-todo").value = "OPTION_ready";
  doc.getElementById("field-sync-ready").value = "OPTION_todo";
  await doc.getElementById("settings").emit("submit");
  assert.equal(doc.getElementById("save").disabled, false, doc.getElementById("message").textContent);
  assert.equal(doc.getElementById("groups").hidden, true);
  assert.match(doc.getElementById("effects").textContent, /docs\/style.md/);
  await doc.getElementById("cancel").emit("click");
  assert.equal(doc.getElementById("groups").hidden, false);
  assert.equal(doc.getElementById("save").disabled, true);
  await doc.getElementById("settings").emit("submit");
  await doc.getElementById("save").emit("click");
  assert.match(doc.getElementById("message").textContent, /Saved future defaults/);
  assert.equal(doc.getElementById("field-activation").checked, true);
  assert.equal(doc.getElementById("field-sync-todo").value, "OPTION_ready");
  console.log(JSON.stringify({groups: 4, typedFormSave: true, cancelPreview: true, conflictFocused: true, staleSaveRefused: true, concurrentChoicePreserved: true, explicitFreshSave: true}));
  process.exit(0);
})().catch(error => {console.error(error.stack); process.exit(1);});
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
            with http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
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
                    self.assertEqual(values['status_sync']['mode'], 'advisory')
                    self.assertEqual(values['status_sync']['options']['todo'], 'OPTION_ready')
                finally:
                    if process.poll() is None: process.kill(); process.communicate()
                    server.shutdown(); thread.join()


if __name__ == '__main__': unittest.main()
