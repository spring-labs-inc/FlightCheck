// Execute the actual card script's rendering and scheduled polling with a DOM fixture.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
class Node {
  constructor() { this.textContent = ''; this.children = []; this.dataset = {}; this.hidden = false; }
  append(...items) { this.children.push(...items); }
  prepend(...items) { this.children.unshift(...items); }
  replaceChildren(...items) { this.children = items; }
  setAttribute(name, value) { this[name] = value; }
  addEventListener() {}
}
const nodes = new Map();
const byId = id => { if (!nodes.has(id)) nodes.set(id, new Node()); return nodes.get(id); };
const observations = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
let next = 0, poll;
const context = vm.createContext({
  document: { getElementById: byId, createElement: () => new Node() },
  location: { pathname: '/task/test-change/', port: '31337' }, URL, Intl, AbortController,
  setTimeout: (fn, delay) => { if (delay === 5000) poll = fn; return delay; },
  clearTimeout: () => {},
  fetch: async () => {
    const row = observations[next++];
    if (row.disconnect) throw Error('Disconnected');
    return { ok: row.ok, json: async () => row.data };
  }
});
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), context);
(async () => {
  for (let i = 0; i < observations.length; i++) {
    // Drain promises started by the script and each scheduled refresh.
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(next, i + 1);
    assert.equal(typeof poll, 'function');
    assert.equal(byId('verdict').textContent, 'Pending');
    if (i === 0 || i === 5) {
      assert.equal(byId('rendering').textContent, 'Snapshot rendered');
      assert.equal(byId('task-details').hidden, false);
      assert.equal(byId('stages').children.length, 9);
      const state = byId('checks').children[0].children[1].textContent;
      assert.equal(state, i === 5 ? 'Stale' : 'Pending');
    } else {
      assert.equal(byId('task-details').hidden, true);
      assert.equal(byId('rendering').textContent, 'Current snapshot unavailable');
      assert.equal(byId('publication').textContent, i === 4 ? 'Publication unconfirmed' : 'Snapshot unavailable');
    }
    if (i + 1 < observations.length) await poll();
  }
  process.stdout.write(JSON.stringify({ observations: next }));
})().catch(error => { console.error(error); process.exitCode = 1; });
