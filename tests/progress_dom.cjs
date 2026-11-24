// Deterministic DOM contract: parse the shipped HTML, execute the shipped JS.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
class Node {
  constructor(tag = '') { this.tagName = tag; this.children = []; this.dataset = {}; this.attributes = {}; this.events = {}; this.hidden = false; this._text = ''; }
  get textContent() { return this._text + this.children.map(item => typeof item === 'string' ? item : item.textContent).join(''); }
  set textContent(value) { this._text = String(value); this.children = []; }
  append(...items) { this.children.push(...items); }
  prepend(...items) { this.children.unshift(...items); }
  replaceChildren(...items) { this._text = ''; this.children = items; }
  setAttribute(name, value) { this.attributes[name] = String(value); if (name === 'id') this.id = value; if (name === 'hidden') this.hidden = true; }
  addEventListener(name, fn) { (this.events[name] ??= []).push(fn); }
  dispatch(name) { for (const fn of this.events[name] ?? []) fn(); }
}
function fixture(html) {
  const root = new Node('document'), stack = [root], ids = new Map();
  const voids = new Set(['meta', 'link', 'br', 'hr', 'input', 'img']);
  for (const token of html.match(/<[^>]+>|[^<]+/g)) {
    if (token.startsWith('</')) { stack.pop(); continue; }
    if (token.startsWith('<!')) continue;
    if (!token.startsWith('<')) { stack.at(-1).append(token); continue; }
    const tag = token.match(/^<([\w-]+)/)[1], node = new Node(tag);
    for (const match of token.matchAll(/\s([\w-]+)(?:="([^"]*)")?/g)) node.setAttribute(match[1], match[2] ?? '');
    if (node.id) ids.set(node.id, node);
    stack.at(-1).append(node);
    if (!voids.has(tag)) stack.push(node);
  }
  root.getElementById = id => ids.get(id) ?? null;
  root.createElement = tag => new Node(tag);
  root.visibilityState = 'visible';
  return root;
}
const stages = ['Plan', 'Implement', 'Cheap Tests', 'Interactive UI Approval', 'Independent Code Review', 'Authoritative Gates', 'Skeptical Evidence Review', 'Final Verdict', 'PR & Merge'];
function snapshot(overrides = {}) {
  const timestamp = '2026-01-01T00:00:00Z';
  return {snapshot:'live',task:'test-change',title:'Live task',summary:'Implementing',candidate:'candidate-one',publicationPort:31337,
    verdict:'APPROVE',verdict_candidate:'candidate-one',
    stages:Object.fromEntries(stages.map(name => [name, name === 'Implement' ? 'current' : 'pending'])),
    links:[{kind:'issue',label:'Issue #108',title:'Freshness repair',url:'https://github.com/example/project/issues/108',flight:'test-change'}],
    issue_stages:{'test-change':{stage:'Implement',shared:false}},checks:[],ci:[],history:[],
    activities:[{id:'worker',name:'Browser worker',kind:'worker',state:'running',candidate:'candidate-one'}],
    freshness:{activity_at:timestamp,published_at:timestamp,publisher_heartbeat_at:timestamp,owner_expires_at:'2026-01-01T00:02:00Z',revision:1,state:'active',
      activity_age_seconds:120,publication_age_seconds:0,heartbeat_age_seconds:0,owner_remaining_seconds:120},...overrides};
}
async function harness(script, html) {
  const document = fixture(html), window = new Node('window');
  let now = 0, timerId = 0, requests = 0, aborted = 0, revision = 0;
  const timers = new Map(), queue = [];
  function setTimeout(fn, delay) { const id = ++timerId; timers.set(id,{at:now+delay,fn}); return id; }
  async function drain() { for (let i = 0; i < 16; i++) await Promise.resolve(); }
  const context = vm.createContext({document,window,location:{pathname:'/task/test-change/',port:'31337'},URL,Intl,AbortController,
    performance:{now:() => now},setTimeout,clearTimeout:id=>timers.delete(id),
    fetch:async (url, options) => {
      requests++; assert.equal(url,'status.json'); assert.equal(options.cache,'no-store');
      options.signal.addEventListener('abort',()=>aborted++);
      const row=queue.shift(); if (!row) throw Error('No queued response');
      if (row.disconnect) throw Error('Disconnected');
      if (row.hang) return new Promise(()=>{});
      if (row.data?.freshness && !row.fixedRevision) row.data.freshness.revision = ++revision;
      return {ok:row.ok!==false,json:()=>row.bodyHang ? new Promise(resolve=>{row.releaseBody=resolve}) : Promise.resolve(row.data)};
    }});
  const api={document,window,queue,timers,byId:id=>document.getElementById(id),
    get requests(){return requests},get aborted(){return aborted},
    async start(data){queue.push({data});vm.runInContext(script,context);await drain()},
    flush:drain,
    async sleep(ms){now+=ms;const ready=[...timers].filter(([,timer])=>timer.at<=now);for(const [id,timer] of ready){timers.delete(id);timer.fn()}await drain()},
    async advance(ms){const end=now+ms;while(true){const pending=[...timers].filter(([,timer])=>timer.at<=end).sort((a,b)=>a[1].at-b[1].at)[0];if(!pending)break;now=pending[1].at;timers.delete(pending[0]);pending[1].fn();await drain()}now=end;await drain()},
    async event(name,visibility){if(visibility)document.visibilityState=visibility;(name==='visibilitychange'?document:window).dispatch(name);await drain()}};
  return api;
}
async function run(script,html,css) {
  const h=await harness(script,html);
  await h.start(snapshot());
  // Existing behavior baseline must fail on retained content, before consulting new UI IDs.
  assert.equal(h.byId('task-details').hidden,false);
  assert.equal(h.byId('stages').children.length,9);
  function findTag(node, tag) {
    if (node.tagName === tag) return node;
    for (const child of node.children.filter(item => typeof item !== 'string')) {
      const match = findTag(child, tag);
      if (match) return match;
    }
  }
  function contains(parent, target) {
    return parent === target || parent.children.some(child => typeof child !== 'string' && contains(child, target));
  }
  const stageNodes=h.byId('stages').children;
  stages.forEach((name, index) => {
    assert.ok(stageNodes[index].textContent.includes(name), `Workflow stage ${name} keeps its order and label`);
    assert.equal(stageNodes[index].dataset.state, name === 'Implement' ? 'current' : 'pending');
  });
  const issue=h.byId('links').children[0];
  h.queue.push({disconnect:true});await h.advance(5000);
  assert.equal(h.byId('task-details').hidden,false,'Disconnect must preserve last-known workflow stages/work links');
  assert.equal(h.byId('links').children[0],issue);
  assert.equal(h.byId('stages').children,stageNodes);
  assert.equal(h.byId('notice').textContent,'Updates paused · Showing last known status');
  assert.equal(h.byId('notice').hidden,false);
  assert.equal(h.byId('verdict').textContent,'Pending');
  // Preserve the original outage regression as the first baseline discriminator.
  const footer = findTag(h.document, 'footer');
  const main = findTag(h.document, 'main');
  assert.ok(footer, 'Operational diagnostics footer must remain present');
  const diagnostics=h.byId('status-diagnostics');
  assert.equal(diagnostics.tagName,'details');
  assert.equal(Object.hasOwn(diagnostics.attributes,'open'),false,'Diagnostic details start collapsed');
  assert.equal(h.byId('progress-summary').tagName,'summary');
  assert.equal(diagnostics.children.filter(item=>typeof item!=='string')[0],h.byId('progress-summary'));
  assert.ok(contains(footer,diagnostics));
  assert.equal(footer.children.filter(item=>typeof item!=='string').length,1,'Only collapsed details remain in the footer');
  const lines=diagnostics.children.filter(item=>typeof item!=='string')[1];
  assert.deepEqual(lines.children.filter(item=>typeof item!=='string').map(item=>item.id),['connection-status','receipt-status'],'Expanded details contain exactly two concise lines');
  for (const id of ['freshness','activity','publication','forwarding','rendering','timestamps','observation-gap']) {
    assert.equal(h.byId(id),null, `${id} technical markup must not remain in the card`);
  }
  for (const id of ['connection-status','receipt-status']) assert.ok(contains(diagnostics,h.byId(id)));
  assert.equal(h.byId('connection-status').textContent,'Connection: Disconnected · Updates: Unknown');
  assert.equal(h.byId('receipt-status').textContent,'Last received: 5s ago');
  assert.match(css,/\.task-details\s*\{[^}]*margin-top:\s*6px/);
  assert.match(css,/\.work-link-detail\s*\{[^}]*align-items:\s*center/);
  assert.match(css,/\.route-diagnostics p\s*\{[^}]*white-space:\s*normal/);
  const warningRules=[...css.matchAll(/([^{}]+)\{([^}]*)\}/g)].filter(([,selector])=>/notice|route-diagnostics/.test(selector));
  for (const [,selector,rules] of warningRules) assert.doesNotMatch(rules,/text-overflow:\s*ellipsis|line-clamp|overflow:\s*hidden/,`${selector}: essential warnings remain complete`);
  assert.equal(contains(footer, h.byId('notice')), false, 'Concise current-status warning stays above the workflow');
  assert.ok(main.children.indexOf(h.byId('notice')) < main.children.indexOf(h.byId('task-details')));
  assert.ok(main.children.indexOf(footer) > main.children.indexOf(h.byId('task-details')));
  // Repeated unchanged activity is healthy while the producer heartbeat is live.
  h.queue.push({data:snapshot({freshness:{...snapshot().freshness,activity_age_seconds:600,revision:2}})});await h.advance(5000);
  assert.equal(h.byId('connection-status').textContent,'Connection: Connected · Updates: Live');
  assert.equal(h.byId('receipt-status').textContent,'Last received: just now · Reconnected after gap');
  assert.equal(h.byId('verdict').textContent,'APPROVE');
  assert.equal(h.byId('notice').hidden,true);
  assert.equal(h.byId('notice').textContent,'');
  assert.equal(h.byId('progress-summary').textContent,'Last progress 10m ago · Details');
  
  h.queue.push({data:snapshot({freshness:{...snapshot().freshness,activity_age_seconds:605}})});await h.advance(5000);
  assert.equal(h.byId('progress-summary').textContent,'Last progress 10m ago · Details','Healthy polling must not reset meaningful progress age');
  assert.equal(h.byId('notice').hidden,true,'Old progress with a live heartbeat stays healthy');
  assert.equal(h.byId('receipt-status').textContent,'Last received: just now','Ordinary polling omits a gap phrase');
  assert.equal(h.byId('stages').children,stageNodes,'Heartbeat must not rebuild unchanged stages');
  for (const [update,label] of [[{heartbeat_age_seconds:31},'Paused'],[{owner_remaining_seconds:0},'Paused'],
    [{activity_at:'invalid'},'Unknown'],[{heartbeat_age_seconds:-1,publisher_heartbeat_at:'2999-01-01T00:00:00Z'},'Unknown'],[{publisher_heartbeat_at:null},'Unknown'],
    [{published_at:undefined},'Unknown'],[{owner_expires_at:'invalid'},'Unknown']]) {
    h.queue.push({data:snapshot({freshness:{...snapshot().freshness,...update}})});await h.advance(5000);
    assert.equal(h.byId('connection-status').textContent,`Connection: Connected · Updates: ${label}`);assert.equal(h.byId('verdict').textContent,'Pending');
    assert.equal(h.byId('notice').textContent,label==='Unknown' ? 'Update freshness unknown' : 'Updates paused · Showing last known status');
    assert.equal(h.byId('notice').hidden,false);
  }
  h.queue.push({data:snapshot({freshness:undefined})});await h.advance(5000);
  assert.equal(h.byId('connection-status').textContent,'Connection: Connected · Updates: Unknown');assert.equal(h.byId('verdict').textContent,'Pending');
  assert.equal(h.byId('progress-summary').textContent,'Last progress unknown · Details');
  assert.equal(h.byId('notice').textContent,'Update freshness unknown');
  // A different task is rejected; a new candidate on the same task is accepted without old verdict.
  h.queue.push({data:snapshot({task:'wrong-task',candidate:'wrong-candidate'})});await h.advance(5000);
  assert.equal(h.byId('candidate').textContent,'candidate-on');
  assert.equal(h.byId('task-details').hidden,false);assert.equal(h.byId('verdict').textContent,'Pending');
  const changed=snapshot({candidate:'candidate-two',summary:'Changed candidate',freshness:{...snapshot().freshness,revision:3}});
  h.queue.push({data:changed});await h.advance(5000);
  assert.equal(h.byId('candidate').textContent,'candidate-tw');assert.equal(h.byId('summary').textContent,'Changed candidate');
  assert.equal(h.byId('verdict').textContent,'Pending');
  // A response body that never completes is bounded and its late result cannot replace a newer snapshot.
  const delayedBody={bodyHang:true};h.queue.push(delayedBody);await h.advance(5000);const before=h.requests;
  h.queue.push({data:changed});await h.event('online');assert.equal(h.requests,before,'No overlapping refresh');
  await h.advance(4500);assert.equal(h.aborted,1);assert.equal(h.requests,before+1);
  assert.equal(h.byId('summary').textContent,'Changed candidate');
  delayedBody.releaseBody(snapshot({summary:'Late obsolete response'}));await h.flush();
  assert.equal(h.byId('summary').textContent,'Changed candidate','Late timed-out body must not replace current snapshot');
  assert.equal(h.byId('receipt-status').textContent,'Last received: just now · Resumed after gap');
  assert.equal(h.byId('notice').hidden,true);
  // Header hang shares the same complete-request deadline.
  h.queue.push({hang:true});await h.advance(5000);const hanging=h.requests;
  await h.advance(4500);assert.equal(h.requests,hanging);assert.equal(h.aborted,2);assert.equal(h.byId('verdict').textContent,'Pending');
  assert.equal(h.byId('task-details').hidden,false);
  // Hidden tab is immediately unverified, and resume revalidates the latest state without replay/reload.
  await h.event('visibilitychange','hidden');assert.equal(h.byId('verdict').textContent,'Pending');
  const hiddenRequests=h.requests;await h.advance(60000);assert.equal(h.requests,hiddenRequests,'Hidden tab pauses active polling');
  const resumed=snapshot({candidate:'candidate-new',summary:'Latest after observation gap',verdict_candidate:'candidate-new',freshness:{...snapshot().freshness,revision:4}});
  h.queue.push({data:resumed});await h.event('visibilitychange','visible');
  assert.equal(h.byId('candidate').textContent,'candidate-ne');assert.equal(h.byId('summary').textContent,'Latest after observation gap');
  assert.equal(h.byId('receipt-status').textContent,'Last received: just now · Reconnected after gap');
  assert.equal(h.byId('notice').hidden,true);assert.equal(h.byId('verdict').textContent,'APPROVE');
  // Reconnection cannot roll back the route's persisted snapshot revision.
  h.queue.push({data:snapshot({candidate:'rollback',freshness:{...snapshot().freshness,revision:1}}),fixedRevision:true});await h.advance(5000);
  assert.equal(h.byId('candidate').textContent,'candidate-ne');assert.equal(h.byId('verdict').textContent,'Pending');
  // A suspended timer without visibility notification also exposes an observation gap.
  h.queue.push({data:resumed});await h.sleep(60000);
  assert.equal(h.byId('receipt-status').textContent,'Last received: just now · Resumed after gap');
  assert.equal(h.byId('notice').hidden,true);assert.equal(h.byId('verdict').textContent,'APPROVE');
  // Wrong HTTP and malformed snapshots do not erase valid references.
  for(const row of [{ok:false},{data:{snapshot:'minimal'}},{data:snapshot({publicationPort:0})}]){
    h.queue.push(row);await h.advance(5000);assert.equal(h.byId('task-details').hidden,false);assert.equal(h.byId('verdict').textContent,'Pending');
  }
  // Honest terminal cards stop active polling and retain the final recorded candidate/verdict.
  const terminal=snapshot({freshness:{...snapshot().freshness,state:'closed',heartbeat_age_seconds:1000,owner_remaining_seconds:-100},stages:Object.fromEntries(stages.map(name=>[name,'completed']))});
  h.queue.push({data:terminal});await h.advance(5000);assert.equal(h.byId('verdict').textContent,'APPROVE');
  assert.equal(h.byId('connection-status').textContent,'Connection: Connected · Updates: Closed');const closedRequests=h.requests;
  await h.advance(60000);assert.equal(h.requests,closedRequests,'Closed card must stop active polling');
  const empty=await harness(script,html);await empty.start(undefined);
  assert.equal(empty.byId('notice').textContent,'Update freshness unknown','First failure cannot claim a last-known status');
  assert.equal(empty.byId('notice').hidden,false);
  assert.equal(empty.byId('task-details').hidden,true);
  empty.queue.push({data:snapshot()});await empty.event('pageshow');
  assert.equal(empty.byId('receipt-status').textContent,'Last received: just now','Initial pageshow without a prior receipt is not a reconnection gap');
  process.stdout.write(JSON.stringify({contract:'freshness-disconnect-resume-identity',requests:h.requests}));
}
async function runMetadata(script, html) {
  const css=fs.readFileSync(process.argv[3].replace(/task\.html$/,'card.css'),'utf8');
  const epic={kind:'epic',label:'#110',url:'https://github.com/example/project/issues/110',
    title:'[Epic] Sequence 3 roadmap: evidence efficiency, reliability, checkout lifecycle, and remaining enhancements',
    description:'Full source summary for the expanded Epic.',metadata:{state:'ready'}};
  const issue={kind:'issue',label:'#118',url:'https://github.com/example/project/issues/118',title:'Issue title',metadata:{state:'empty'}};
  const pr={kind:'pr',label:'#119',url:'https://github.com/example/project/pull/119',title:'PR title',metadata:{state:'empty'}};
  // Source activity order cannot put an issue or PR above the Epic.
  const e=await harness(script,html);await e.start(snapshot({links:[issue,pr,epic]}));
  assert.deepEqual(e.byId('links').children.map(row=>row.textContent.split(' ')[0]),['Epic','Issue','PR']);
  assert.match(css,/\.work-links li\.work-link-epic\s*\{[^}]*display:\s*block/,'Epic owns the first line; issues and PRs follow below');
  function firstButton(node) { return node.tagName==='button' ? node : node.children.filter(c=>typeof c!=='string').map(firstButton).find(Boolean); }
  let epicButton=firstButton(e.byId('links'));
  assert.ok(epicButton.textContent.length<=55,'Collapsed Epic title is bounded instead of wrapping the badge');
  assert.ok(epicButton.textContent.endsWith('…'),'Long Epic titles end with an ellipsis');
  assert.ok(epicButton.attributes['aria-label'].includes(epic.title),'Accessible name retains the full title');
  assert.match(css,/\.work-link-item--epic\s*\{[^}]*display:\s*inline-flex/);
  assert.match(css,/\.work-link-item--epic\s*\{[^}]*white-space:\s*nowrap/);
  assert.match(css,/\.work-link-item--epic \.work-link-select\s*\{[^}]*text-overflow:\s*ellipsis/);
  assert.equal(e.byId('work-link-detail').hidden,true,'Initially collapsed');
  epicButton.dispatch('click');
  assert.equal(e.byId('work-link-detail').hidden,false);assert.equal(epicButton.attributes['aria-expanded'],'true');
  assert.equal(e.byId('work-link-title').textContent,epic.title,'Expansion keeps the complete title');
  assert.equal(e.byId('work-link-description').textContent,epic.description);
  epicButton.dispatch('click');
  assert.equal(e.byId('work-link-detail').hidden,true);assert.equal(epicButton.attributes['aria-expanded'],'false');
  assert.equal(e.byId('work-link-destination').children.length,0,'Collapse removes the hidden destination');
  epicButton.dispatch('click');
  e.queue.push({data:snapshot({links:[{...epic,description:'Updated safe summary.'}]})});await e.advance(5000);
  epicButton=firstButton(e.byId('links'));
  assert.equal(epicButton.attributes['aria-expanded'],'true','Selected Epic survives metadata refresh');
  assert.equal(e.byId('work-link-description').textContent,'Updated safe summary.');
  epicButton.dispatch('click');assert.equal(e.byId('work-link-detail').hidden,true,'Refreshed Epic still collapses');
  const h = await harness(script, html);
  const row = {kind:'issue',label:'#118',url:'https://github.com/example/project/issues/118',flight:'test-change',
    title:'Safe <script>literal</script> title',description:'Source-grounded summary.',metadata:{state:'ready'}};
  await h.start(snapshot({links:[row]}));
  function button(node) { return node.tagName==='button' ? node : node.children.filter(c=>typeof c!=='string').map(button).find(Boolean); }
  button(h.byId('links')).dispatch('click');
  assert.equal(h.byId('work-link-title').textContent,row.title,'Untrusted text remains textContent');
  assert.equal(h.byId('work-link-title').children.length,0);
  assert.equal(h.byId('work-link-description').textContent,row.description);
  const open=h.byId('work-link-destination').children[0];
  assert.equal(open.target,'_blank');assert.ok(open.rel.includes('noopener'));assert.ok(open.rel.includes('noreferrer'));
  for (const [state,reason,expected] of [
    ['not_loaded','Details not loaded.','Details not loaded.'],
    ['loading','Loading details…','Loading details…'],
    ['unavailable','Details unavailable: provider access denied.','Details unavailable: provider access denied.'],
    ['empty','No description published.','No description published.'],
    ['stale','Last known details; refresh is due.','Last known details · Last known details; refresh is due. Source-grounded summary.']]) {
    h.queue.push({data:snapshot({links:[{...row,metadata:{state,reason}}]})});await h.advance(5000);
    assert.equal(h.byId('work-link-detail').hidden,false,'Selection survives metadata refresh');
    assert.equal(h.byId('work-link-description').textContent,expected);
    assert.equal(h.byId('stages').children.length,9);
  }
  h.queue.push({disconnect:true});await h.advance(5000);
  assert.equal(h.byId('work-link-detail').hidden,false,'Transport outage preserves selected safe details');
  assert.equal(h.byId('notice').textContent,'Updates paused · Showing last known status');
  process.stdout.write(JSON.stringify({contract:'metadata-availability-selection-safety',requests:h.requests}));
}
if(require.main===module) {
  const script=fs.readFileSync(process.argv[2],'utf8'),html=fs.readFileSync(process.argv[3],'utf8');
  const job=process.argv.includes('--metadata') ? runMetadata(script,html) : run(script,html,fs.readFileSync(process.argv[3].replace(/task\.html$/,'card.css'),'utf8'));
  job.catch(error=>{console.error(error);process.exitCode=1});
}
module.exports={fixture,harness,snapshot};
