"""Observable provider/publication contracts; all transport fixtures are local GETs."""
import copy
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
STAGES = ("Plan", "Implement", "Cheap Tests", "Interactive UI Approval", "Independent Code Review",
          "Authoritative Gates", "Skeptical Evidence Review", "Final Verdict", "PR & Merge")


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root.chmod(0o700)
        self.project = self.root / 'project'
        self.project.mkdir()
        subprocess.run(['/usr/bin/git', 'init', '-q', str(self.project)], check=True)
        subprocess.run(['/usr/bin/git', '-C', str(self.project), 'remote', 'add', 'origin',
                        'https://github.com/example/project.git'], check=True)
        self.trace = self.root / 'trace.jsonl'
        self.responses = self.root / 'responses.json'
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        gh = self.bin / 'gh'
        gh.write_text('#!' + sys.executable + "\n" + """import os,sys,json,time
from pathlib import Path
args=sys.argv[1:]
with open(os.environ['METADATA_TRACE'],'a') as f:f.write(json.dumps(args)+'\\n')
assert args[:6]==['api','--hostname','github.com','--method','GET',args[5]]
responses=json.loads(Path(os.environ['METADATA_RESPONSES']).read_text())
row=responses[args[-1]]
time.sleep(row.get('delay',0))
if row.get('error'):
 print(row['error'],file=sys.stderr);sys.exit(1)
print(json.dumps(row.get('response',row)))
""")
        gh.chmod(0o700)
        self.env = patch.dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                              METADATA_TRACE=str(self.trace), METADATA_RESPONSES=str(self.responses),
                              PYTHONDONTWRITEBYTECODE='1')
        self.env.start()
        self.addCleanup(self.env.stop)
        self.rows = {f'repos/example/project/{route}/{number}':
                     {'number': number, 'html_url': f'https://github.com/example/project/{url}/{number}',
                      'title': f'Tracker title {number}', 'body': f'Source summary {number}.', 'state': 'open',
                      'created_at': '2026-01-01T00:00:00Z', 'updated_at': '2026-01-02T00:00:00Z'}
                     for route, url, number in [('issues','issues',1),('issues','issues',2),('pulls','pull',3),('issues','issues',4)]}
        self.rows['repos/example/project'] = {'full_name':'example/project','private':False}
        self.save()

    def save(self):
        self.responses.write_text(json.dumps(self.rows))

    def links(self):
        return [{'kind': kind, 'label': '#'+str(n), 'url': f'https://github.com/example/project/{route}/{n}',
                 **({'flight':'metadata-test'} if kind == 'issue' else {})}
                for kind, route, n in [('epic','issues',1),('issue','issues',2),('pr','pull',3)]]

    def details(self, links=None):
        return {'stages': {name:'current' if name == 'Implement' else 'pending' for name in STAGES},
                'check_plan': [], 'checks_unavailable':'No checks in this isolated transport fixture.',
                'links': self.links() if links is None else links, 'branch':'fixture', 'worktree':'fixture'}

    def publish(self, details=None, candidate='candidate-one', file=None):
        source = self.root / 'details.json'
        source.write_text(json.dumps(details or self.details()))
        target = file or self.root / 'status.json'
        result = subprocess.run([sys.executable,'-B',str(ROOT/'status-card/task_status.py'),
            '--file',str(target),'--mode','flight','--task','metadata-test','--title','Friendly title',
            '--candidate',candidate,'--details',str(source)],cwd=self.project,capture_output=True,text=True,timeout=12)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        return json.loads(target.read_text())

    def calls(self):
        return [json.loads(row) for row in self.trace.read_text().splitlines()] if self.trace.exists() else []

    def helper(self):
        sys.path.insert(0,str(ROOT/'status-card'))
        self.addCleanup(lambda: sys.path.remove(str(ROOT/'status-card')))
        return importlib.import_module('link_metadata')

    def prepare(self, links=None, now=None, **kwargs):
        return self.helper().prepare_links(self.links() if links is None else links,
            self.root/'cache',self.project,'metadata-test','candidate-one',now=now,**kwargs)

    def test_publication(self):
        # This uses the unchanged public CLI on both the pinned original and candidate.
        data = self.publish()
        by_kind = {row['kind']:row for row in data['links']}
        self.assertEqual(by_kind['issue'].get('title'),'Tracker title 2')
        for row in data['links']:
            self.assertEqual(row['description'],f"Source summary {row['label'][1:]}.")
            self.assertTrue(row['metadata']['ready'])
            self.assertEqual(row['metadata']['identity']['url'],row['url'])
            self.assertEqual(row['metadata']['candidate'],data['candidate'])
        self.assertTrue(data['link_details']['ready'])
        links = self.links();links[1].update(label='#4',url='https://github.com/example/project/issues/4')
        updated = self.publish(self.details(links))
        self.assertEqual(next(row for row in updated['links'] if row['kind']=='issue')['title'],'Tracker title 4')
        self.assertEqual(len(self.calls()),6,'Initial repo +three items; changed-item batch rechecks visibility')

    def test_availability(self):
        helper = self.helper();now=time.time()
        bare = helper.normalize(self.links()[0], 'metadata-test', 'candidate-one')
        self.assertEqual(bare['metadata']['state'],'not_loaded')
        loading = helper.bind(self.links()[0],'metadata-test','candidate-one')
        loading['metadata'].update(state='loading',expires_at=helper.iso(now+2))
        self.assertEqual(helper.normalize(loading,now=now)['metadata']['state'],'loading')
        self.assertEqual(helper.normalize(loading,now=now+3)['metadata']['state'],'unavailable')
        self.rows['repos/example/project/issues/2']['body']='';self.save()
        empty=self.prepare(now=now)[1]
        self.assertEqual(empty['metadata']['state'],'empty');self.assertTrue(empty['metadata']['ready'])
        self.rows['repos/example/project/issues/2']={'error':'HTTP 403 host path /private/fixture'};self.save()
        stale=self.prepare(now=now+901)[1]
        self.assertEqual(stale['metadata']['state'],'stale');self.assertFalse(stale['metadata']['ready'])
        self.assertIn('access denied',stale['metadata']['reason'])
        other=self.root/'other';other.mkdir(mode=0o700)
        denied=helper.prepare_links([self.links()[1]],other/'cache',self.project,'other-task','c')[0]
        self.assertEqual(denied['metadata']['state'],'unavailable')
        self.assertNotIn('/private/',json.dumps(denied))
        self.rows['repos/example/project/issues/4']={'delay':10,'response':self.rows['repos/example/project/issues/1']};self.save()
        link=dict(self.links()[1],url='https://github.com/example/project/issues/4',label='#4')
        before=time.monotonic();out=self.prepare([link])[0];elapsed=time.monotonic()-before
        self.assertLess(elapsed,3);self.assertGreater(elapsed,1.5)
        self.assertFalse(out['metadata']['ready']);self.assertIn('timed out',out['metadata']['reason'])

    def test_cache(self):
        helper=self.helper();now=time.time();rows=self.prepare(now=now);count=len(self.calls())
        again=self.prepare(now=now+1);self.assertEqual(rows,again);self.assertEqual(len(self.calls()),count)
        for _ in range(4):
            helper.normalize(rows[1],'metadata-test','candidate-one',now=now+2)
        self.prepare(now=now+901,fetch=False)
        self.assertEqual(len(self.calls()),count,'Reads and heartbeat/cache-only binding never call provider')
        self.rows['repos/example/project/issues/2']={'error':'HTTP 503'};self.save()
        stale=self.prepare(now=now+901)[1]
        self.assertEqual(stale['title'],'Tracker title 2');self.assertEqual(stale['flight'],'metadata-test')
        self.assertEqual(stale['metadata']['state'],'stale');self.assertIn('observed_at',stale['metadata'])
        count=len(self.calls());self.prepare(now=now+902);self.assertEqual(len(self.calls()),count,'Failure backoff')
        self.rows['repos/example/project/issues/2']=dict(self.rows['repos/example/project/issues/1'],number=2,
            html_url=self.links()[1]['url'],title='Recovered title');self.save()
        recovered=self.prepare(now=now+932)[1]
        self.assertEqual(recovered['title'],'Recovered title');self.assertTrue(recovered['metadata']['ready'])
        # Cache corruption is not trusted acceptance; it triggers a bounded fresh observation.
        cache=next((self.root/'cache').glob('item-*.json'));cache.write_text('[]')
        self.prepare(now=now+933)
        self.assertTrue(all(row[:5]==['api','--hostname','github.com','--method','GET'] for row in self.calls()))

    def test_privacy(self):
        helper=self.helper();self.rows['repos/example/project']['private']=True
        self.rows['repos/example/project/issues/2']['body']='Private project planning notes.';self.save()
        rows=self.prepare();text=json.dumps(rows)+''.join(p.read_text() for p in (self.root/'cache').glob('*.json'))
        self.assertNotIn('Private project planning notes.',text);self.assertNotIn('/Users/fixture',text)
        self.assertEqual(rows[1]['metadata']['state'],'unavailable')
        self.assertIn('withheld',rows[1]['metadata']['reason'])
        description,state=helper.summary('Short **public** summary.\n\nLater paragraph.',False)
        self.assertEqual(description,'Short public summary.');self.assertEqual(state,'ready')
        self.assertEqual(helper.summary('token sk-abcdefghijk',False)[1],'unsafe')
        self.assertEqual(helper.summary('Safe first paragraph.\n\nLater /private/not-published',False),
                         ('Safe first paragraph.','ready'))
        self.assertEqual(helper.summary('![image](https://remote.invalid) <script>boom</script>',False)[0],'boom')
        count=len(self.calls())
        self.prepare([dict(self.links()[1],url='https://other.invalid/example/project/issues/2')])
        self.prepare([dict(self.links()[1],url='https://github.com/other/project/issues/2')])
        self.assertEqual(len(self.calls()),count,'No arbitrary host/repository reads')
        self.assertTrue(all(c[3:5]==['--method','GET'] for c in self.calls()))

    def test_visibility_change(self):
        self.prepare([self.links()[0]])
        self.rows['repos/example/project']['private']=True
        self.rows['repos/example/project/issues/4']['body']='Internal project planning details.'
        self.save();row=dict(self.links()[1],label='#4',url='https://github.com/example/project/issues/4')
        result=self.prepare([row])[0]
        cache=''.join(p.read_text()for p in (self.root/'cache').glob('*.json'))
        self.assertNotIn('Internal project planning details.',json.dumps(result)+cache,
                         'A previously public repository cannot authorize sharing newly fetched private bodies')
        self.assertFalse(result['metadata']['ready'])
        self.assertIn('withheld',result['metadata']['reason'])
        self.assertEqual(len(self.calls()),4,'Two acquisitions each recheck repository visibility; cached item reads still avoid GETs')

    def test_binding(self):
        helper=self.helper();rows=self.prepare();row=rows[1]
        wrong=helper.normalize(row,'other-task','candidate-one')
        self.assertFalse(wrong['metadata']['ready']);self.assertNotIn('title',wrong)
        wrong=helper.normalize(row,'metadata-test','candidate-two')
        self.assertEqual(wrong['metadata']['state'],'stale');self.assertFalse(wrong['metadata']['ready'])
        wrong=copy.deepcopy(row);wrong['url']=self.links()[0]['url']
        self.assertFalse(helper.normalize(wrong,'metadata-test','candidate-one')['metadata']['ready'])
        changed=helper.prepare_links(self.links(),self.root/'cache',self.project,'metadata-test','candidate-two',fetch=False)
        self.assertTrue(changed[1]['metadata']['ready']);self.assertEqual(changed[1]['metadata']['candidate'],'candidate-two')
        self.rows['repos/example/project/issues/4']=self.rows['repos/example/project/issues/1'];self.save()
        mismatch=self.prepare([dict(self.links()[1],url='https://github.com/example/project/issues/4',label='#4')])[0]
        self.assertFalse(mismatch['metadata']['ready']);self.assertNotIn('title',mismatch)
        before={'task':'metadata-test','candidate':'old','links':self.links()}
        with self.assertRaisesRegex(ValueError,'Candidate changed'):
            helper.check_publication_base(before,dict(before,candidate='new'),dict(before,candidate='old'),{'links':self.links()})
        with self.assertRaisesRegex(ValueError,'Links changed'):
            helper.check_publication_base(before,dict(before,links=[]),before,{'links':self.links()})

    def test_integration(self):
        helper=self.helper();import progress,task_status
        from unittest.mock import patch
        directory=self.root/'monitor';directory.mkdir(mode=0o700)
        # The monitor publishes ordinary progress while one bounded GET is still running.
        data={'mode':'flight','task':'metadata-test','candidate':'candidate-one','title':'Friendly title'}
        initial=self.details();initial['links']=self.prepare()
        task_status.publish_locked(directory/'status.json',data,initial)
        source=directory/'source.json';original=self.details();source.write_text(json.dumps(original))
        config={'task':'metadata-test','token':'owned','started_at':time.time(),'checkout':str(self.project),
                'details_source':str(source),'source_value':original}
        (directory/'monitor.json').write_text(json.dumps(config))
        source_value=self.details();source_value['links'][1].update(label='#4',url='https://github.com/example/project/issues/4')
        source_value['branch']='meaningful-progress-during-lookup'
        source.write_text(json.dumps(source_value));self.rows['repos/example/project/issues/4']['updated_at']='2026-01-03T00:00:00Z'
        real=self.rows['repos/example/project/issues/4'];self.rows['repos/example/project/issues/4']={'delay':0.3,'response':real};self.save()
        worker=progress.LinkPreparation();before=time.monotonic()
        with patch('maintainer.candidate',return_value='candidate-one'):
            self.assertTrue(progress.monitor_step(directory,'owned',probe=False,metadata=worker))
            self.assertLess(time.monotonic()-before,0.2)
            self.assertEqual(task_status.read_task(directory/'status.json')['branch'],'meaningful-progress-during-lookup')
            worker.thread.join(5);self.assertFalse(worker.thread.is_alive())
            self.assertTrue(progress.monitor_step(directory,'owned',probe=False,metadata=worker))
            result=task_status.read_task(directory/'status.json')
            self.assertEqual(next(r for r in result['links'] if r['kind']=='issue')['title'],'Tracker title 4')
            count=len(self.calls());revision=result['freshness']['revision']
            progress.monitor_step(directory,'owned',probe=False,metadata=worker)
            self.assertEqual(len(self.calls()),count)
            self.assertEqual(task_status.read_task(directory/'status.json')['freshness']['revision'],revision,
                             'Canonical sorting/normalization cannot create artificial progress on every tick')
        self.assertEqual(result['title'],'Friendly title')
        self.assertEqual(list(result['stages']),list(STAGES))

    def monitor_fixture(self, name):
        self.helper();import task_status
        directory=self.root/name;directory.mkdir(mode=0o700)
        data={'mode':'flight','task':'metadata-test','candidate':'candidate-one','title':'Friendly title'}
        details=self.details();task_status.publish(directory/'status.json',data,details,project=self.project)
        source=directory/'source.json';source.write_text(json.dumps(details))
        (directory/'monitor.json').write_text(json.dumps({'task':'metadata-test','token':'owned',
            'started_at':time.time(),'checkout':str(self.project),'details_source':str(source),'source_value':details}))
        return directory,data,details,source

    def render_preserved_selection(self, snapshots, label='#1 ', title='Tracker title 1', description='Source summary 1.', allow_stale=False):
        file=self.root/'snapshots.json';file.write_text(json.dumps(snapshots))
        program="""const fs=require('fs'),assert=require('assert/strict');const {harness,snapshot}=require(process.argv[1]);
(async()=>{const rows=JSON.parse(fs.readFileSync(process.argv[4])),expected=JSON.parse(process.argv[5]);const h=await harness(fs.readFileSync(process.argv[2],'utf8'),fs.readFileSync(process.argv[3],'utf8'));
function buttons(n){return (n.tagName==='button'?[n]:[]).concat(...n.children.filter(c=>typeof c!=='string').map(buttons))}
await h.start(snapshot({links:rows[0].links,candidate:rows[0].candidate,stages:rows[0].stages}));buttons(h.byId('links')).find(b=>b.textContent.includes(expected.label)).dispatch('click');
for(let i=0;i<rows.length;i++){if(i){h.queue.push({data:snapshot({links:rows[i].links,candidate:rows[i].candidate,stages:rows[i].stages})});await h.advance(5000)}
assert.equal(h.byId('work-link-detail').hidden,false);assert.equal(h.byId('work-link-title').textContent,expected.title);assert.equal(h.byId('candidate').textContent,rows[i].candidate.slice(0,12));if(expected.allow_stale)assert.ok(h.byId('work-link-description').textContent.includes(expected.description));else assert.equal(h.byId('work-link-description').textContent,expected.description)}
console.log('preserved selection across pending/failure/recovery')})().catch(e=>{console.error(e);process.exitCode=1})"""
        result=subprocess.run(['node','-e',program,str(ROOT/'tests/progress_dom.cjs'),str(ROOT/'status-card/task.js'),
                               str(ROOT/'status-card/task.html'),str(file),json.dumps({'label':label,'title':title,'description':description,'allow_stale':allow_stale})],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_pending_monitor(self):
        helper=self.helper();import progress,task_status
        directory,data,details,source=self.monitor_fixture('pending-monitor')
        initial=task_status.read_task(directory/'status.json')
        new={'kind':'issue','label':'#4','url':'https://github.com/example/project/issues/4','flight':'metadata-test'}
        changed=copy.deepcopy(details);changed['links'].append(new);changed['branch']='progress-during-provider-outage'
        source.write_text(json.dumps(changed));self.rows['repos/example/project/issues/4']={'delay':0.3,'error':'HTTP 503'};self.save()
        worker=progress.LinkPreparation()
        with patch('maintainer.candidate',return_value='candidate-one'):
            before=time.monotonic();progress.monitor_step(directory,'owned',probe=False,metadata=worker)
            self.addCleanup(worker.thread.join,5)
            self.assertLess(time.monotonic()-before,0.2)
            pending=task_status.read_task(directory/'status.json')
            self.assertEqual(pending['branch'],'progress-during-provider-outage')
            for old in initial['links']:
                current=next(r for r in pending['links'] if r['url']==old['url'])
                self.assertEqual(current.get('title'),old['title'],'Unchanged safe titles survive pending lookup')
                self.assertEqual(current.get('description'),old['description'])
                self.assertEqual(current.get('flight'),old.get('flight'))
            added=next(r for r in pending['links'] if r['label']=='#4')
            self.assertFalse(added['metadata']['ready']);self.assertNotIn('title',added)
            worker.thread.join(5);self.assertFalse(worker.thread.is_alive())
            progress.monitor_step(directory,'owned',probe=False,metadata=worker)
            failed=task_status.read_task(directory/'status.json')
            self.assertEqual(next(r for r in failed['links'] if r['label']=='#4')['metadata']['state'],'unavailable')
            # The failed cache's clock is fixture input; normal publication performs recovery.
            for cache in (directory/'link-metadata').glob('item-*.json'):
                entry=json.loads(cache.read_text())
                if entry.get('failed_at'):entry['failed_at']-=31;cache.write_text(json.dumps(entry))
            self.rows['repos/example/project/issues/4']=dict(self.rows['repos/example/project/issues/2'],number=4,
                html_url=new['url'],title='Recovered added item');self.save()
            task_status.publish(directory/'status.json',data,changed,project=self.project)
            recovered=task_status.read_task(directory/'status.json')
            self.assertTrue(next(r for r in recovered['links'] if r['label']=='#4')['metadata']['ready'])
            count=len(self.calls());progress.monitor_step(directory,'owned',probe=False,metadata=worker)
            self.assertEqual(len(self.calls()),count,'Ordinary monitor tick does not fetch')
        self.render_preserved_selection([initial,pending,failed,recovered])

    def test_monitor_refresh(self):
        helper=self.helper();import progress,task_status
        for consume_first,failed_worker in ((False,False),(True,False),(False,True)):
            with self.subTest(completed_result_previously_applied=consume_first,failed_worker=failed_worker):
                directory,data,details,source=self.monitor_fixture('refresh-'+str(consume_first)+str(failed_worker))
                changed=copy.deepcopy(details);new={'kind':'issue','label':'#4','url':'https://github.com/example/project/issues/4'}
                changed['links'].append(new);source.write_text(json.dumps(changed));worker=progress.LinkPreparation()
                if failed_worker:self.rows['repos/example/project/issues/4']={'error':'HTTP 503'};self.save()
                with patch('maintainer.candidate',return_value='candidate-one'):
                    progress.monitor_step(directory,'owned',probe=False,metadata=worker);worker.thread.join(5)
                    self.assertFalse(worker.thread.is_alive())
                    if consume_first:progress.monitor_step(directory,'owned',probe=False,metadata=worker)
                    for cache in (directory/'link-metadata').glob('item-*.json'):
                        entry=json.loads(cache.read_text())
                        if 'observed_at' in entry:entry['observed_at']-=901
                        if 'failed_at' in entry:entry['failed_at']-=31
                        cache.write_text(json.dumps(entry))
                    self.rows['repos/example/project/issues/4']=dict(self.rows['repos/example/project/issues/2'],number=4,html_url=new['url'],
                        title='Newer explicit observation '+str(consume_first),body='Fresh description survives old worker.',updated_at='2026-01-04T00:00:00Z');self.save()
                    task_status.publish(directory/'status.json',data,changed,project=self.project)
                    refreshed=task_status.read_task(directory/'status.json');count=len(self.calls());snapshots=[refreshed]
                    for _ in range(3):
                        progress.monitor_step(directory,'owned',probe=False,metadata=worker)
                        current=task_status.read_task(directory/'status.json')
                        snapshots.append(current)
                        row=next(r for r in current['links'] if r['label']=='#4')
                        self.assertEqual(row.get('title'),'Newer explicit observation '+str(consume_first))
                        self.assertEqual(row['description'],'Fresh description survives old worker.')
                        self.assertTrue(row['metadata']['ready'])
                    self.assertEqual(len(self.calls()),count,'Completed worker and heartbeat cannot refetch')
                    self.render_preserved_selection(snapshots,label='#4',title='Newer explicit observation '+str(consume_first),
                                                    description='Fresh description survives old worker.')

    def test_deferred_source_change(self):
        self.helper();import progress,task_status
        for transition in (False,True):
            with self.subTest(candidate_transition=transition):
                directory,data,details,source=self.monitor_fixture('deferred-'+str(transition))
                initial=task_status.read_task(directory/'status.json');snapshots=[initial]
                first=copy.deepcopy(details)
                for n in (4,5,6):
                    url=f'https://github.com/example/project/issues/{n}'
                    self.rows[f'repos/example/project/issues/{n}']=dict(self.rows['repos/example/project/issues/2'],
                        number=n,html_url=url,title=f'Tracker title {n}',body=f'Source summary {n}.',delay=1.4)
                    first['links'].append({'kind':'issue','label':'#'+str(n),'url':url,'flight':'metadata-test'})
                self.rows['repos/example/project/issues/7']=dict(self.rows['repos/example/project/issues/2'],number=7,
                    html_url='https://github.com/example/project/issues/7',title='Tracker title 7',body='Source summary 7.')
                self.save();first['branch']='progress-before-deferred-target';source.write_text(json.dumps(first))
                worker=progress.LinkPreparation();current=['candidate-one'];started=time.monotonic()
                with patch('maintainer.candidate',side_effect=lambda _:current[0]):
                    progress.monitor_step(directory,'owned',probe=False,metadata=worker)
                    self.addCleanup(lambda w=worker:w.thread.join(8))
                    snapshots.append(task_status.read_task(directory/'status.json'))
                    # Three <2s item requests span the next real four-second source tick,
                    # while the entire old batch remains inside its existing eight-second budget.
                    time.sleep(4)
                    self.assertTrue(worker.thread.is_alive(),'Exercise a second source change during the active batch')
                    latest=copy.deepcopy(first)
                    for row in latest['links']:
                        if row['label']=='#4':row.update(label='#7',url='https://github.com/example/project/issues/7')
                    latest['branch']='progress-with-deferred-target'
                    if transition:current[0]='candidate-two';latest['stages']['Plan']='completed'
                    source.write_text(json.dumps(latest));before=time.monotonic()
                    progress.monitor_step(directory,'owned',probe=False,metadata=worker)
                    self.assertLess(time.monotonic()-before,0.2,'Pending provider work cannot block ordinary publication')
                    pending=task_status.read_task(directory/'status.json');snapshots.append(pending)
                    self.assertEqual(pending['branch'],'progress-with-deferred-target')
                    self.assertFalse(next(r for r in pending['links']if r['label']=='#7')['metadata']['ready'])
                    worker.thread.join(4);self.assertFalse(worker.thread.is_alive())
                    self.assertLess(time.monotonic()-started,8,'Original batch is bounded')
                    # No source edit or explicit publisher call: the queued latest target must fetch.
                    progress.monitor_step(directory,'owned',probe=False,metadata=worker)
                    snapshots.append(task_status.read_task(directory/'status.json'))
                    worker.thread.join(4);self.assertFalse(worker.thread.is_alive())
                    progress.monitor_step(directory,'owned',probe=False,metadata=worker)
                    final=task_status.read_task(directory/'status.json');snapshots.append(final)
                    row=next(r for r in final['links']if r['label']=='#7')
                    self.assertTrue(row['metadata']['ready'],'Deferred uncached target must acquire without another reply')
                    self.assertEqual(row['title'],'Tracker title 7');self.assertEqual(row['metadata']['candidate'],current[0])
                    self.assertTrue(any(c[-1]=='repos/example/project/issues/7'for c in self.calls()))
                    self.assertNotIn('#4',[r['label']for r in final['links']],'Obsolete worker cannot restore the previous target')
                    for row in final['links']:
                        self.assertEqual(row['metadata']['candidate'],current[0])
                        if row['kind']=='issue':self.assertEqual(row['flight'],'metadata-test')
                    self.assertEqual(list(final['stages']),list(STAGES))
                    count=len(self.calls());activity=final['freshness']['activity_at']
                    heartbeat=progress.seconds(final['freshness']['publisher_heartbeat_at'])
                    progress.monitor_step(directory,'owned',now=heartbeat+9,probe=False,metadata=worker)
                    after=task_status.read_task(directory/'status.json')
                    self.assertNotEqual(after['freshness']['publisher_heartbeat_at'],final['freshness']['publisher_heartbeat_at'])
                    self.assertEqual(after['freshness']['activity_at'],activity)
                    for _ in range(2):progress.monitor_step(directory,'owned',probe=False,metadata=worker)
                    self.assertEqual(len(self.calls()),count,'Later ordinary ticks cannot refetch completed metadata')
                self.render_preserved_selection(snapshots,allow_stale=transition)

    def test_compatibility(self):
        # Original public CLI, including minimal/legacy records, remains usable.
        data=self.publish()
        self.assertEqual(data['title'],'Friendly title')
        self.assertEqual(list(data['stages']),list(STAGES))
        self.assertTrue(data['completeness']['ready'])
        self.assertEqual(next(row for row in data['links'] if row['kind']=='issue')['flight'],'metadata-test')
        node=os.environ.get('FLIGHTCHECK_NODE') or shutil.which('node')
        self.assertIsNotNone(node,'Supported browser harness requires Node')
        result=subprocess.run([node,str(ROOT/'tests/progress_dom.cjs'),str(ROOT/'status-card/task.js'),
                               str(ROOT/'status-card/task.html')],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
