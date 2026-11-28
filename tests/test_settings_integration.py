"""Current common Save reaches active work without changing accepted sync authority."""
import copy
import json
import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

from checkout_guard_cases import CheckoutCases, PRODUCT
import test_settings as fixtures
from test_status_sync import FakeProvider


class SettingsIntegrationTests(CheckoutCases, unittest.TestCase):
    config_fixture = fixtures.SettingsTests.config_fixture
    config_module = fixtures.SettingsTests.config_module
    config_git = fixtures.SettingsTests.config_git
    config_cli = fixtures.SettingsTests.config_cli

    def test_integrated_sync_settings_contract(self):
        with self.fixture(), self.config_fixture() as (_, root, engine, installed, cli, supplied):
            from flightcheck_cli.settings import Settings
            self.root = root
            self.git(root, 'remote', 'add', 'origin', 'https://github.com/fixture/repo.git')
            self.git(root, 'switch', '-c', 'codex/settings-integration')
            self.base = self.git(root, 'rev-parse', 'HEAD')
            self.registry = self.associations.Registry(cli.configuration_registry(engine, root))
            def service():
                return Settings(engine, root, registry=self.registry.directory, reference='Explicit fixture project editing authority')
            owner = service()
            initial = owner.read()
            policy = {"schema":1,"mode":"advisory","provider":"github-projects-v2","project_id":"fixture-project","field_id":"fixture-status","membership":"existing-only",
                      "options":{key:"fixture-"+key for key in ("todo","ready","in_progress","review","done")}}
            plan = owner.preview({'changes': {'status_sync':policy, 'default_branch':'trunk'}, 'expected_revision':initial['revision']})
            owner.apply({'plan_id':plan['plan_id']})
            peer = self.area / 'peer'
            self.git(root, 'worktree', 'add', '-q', '-b', 'codex/settings-peer', str(peer), self.base)
            shutil.copytree(root / '.flightcheck', peer / '.flightcheck')
            records = {}
            for path, flight in [(root, 'settings-main'), (peer, 'settings-peer')]:
                record = self.record(path, flight)
                record['issues'] = [80]
                record['status_sync'] = {'history':['retained fixture decision'], 'pending':{'attempts':2, 'owner_reference':'Existing scoped retry'}, 'work':[{'issue':80,'role':'implementation' if flight=='settings-main' else 'roadmap','scope':'full','reference':'Explicit synthetic scoped issue ownership'}]}
                record['grants']['tracker_status'] = {'schema':1, 'authority':'owner', 'reference':'Existing exact-revision grant',
                    'repository':record['repository']['id'], 'provider':policy['provider'], 'project_id':policy['project_id'],
                    'field_id':policy['field_id'], 'issues':[80], 'configuration_revision':record['configuration']['revision']}
                self.adopt(path, record=record, decision={"adopt_existing":True, "dependent_flight":True, "reference":"Owner explicitly adopts only these owned synthetic installer/worktree bytes"})
                records[flight] = self.registry.get(flight)
            sync = self.module('status_sync')
            provider = FakeProvider(sync, policy)
            provider.state[80] = {**provider.state[11], 'repository':'fixture/repo', 'issue':80, 'item_id':'fixture-item-80'}
            def synchronize(kind, **extra):
                with patch.dict(os.environ, CODEX_THREAD_ID='session-1'):
                    return sync.synchronize(self.registry, 'settings-main', {'kind':kind, 'issues':[80], 'reference':'Actual synthetic '+kind, **extra}, checkout=root, provider=provider, pause=lambda _:None)
            self.assertEqual(synchronize('start')['state'], 'synchronized')
            self.assertEqual(provider.state[80]['option_id'],policy['options']['in_progress'])
            records['settings-main'] = self.registry.get('settings-main')
            # Manual Status plus Sequence/Priority decisions occur while the
            # unrelated resource Save is awaiting its execution boundary.
            provider.manual(80, policy['options']['ready'])
            provider.fields.update(Sequence='Owner sequence during Save', Priority='Owner priority during Save')
            manual = copy.deepcopy(provider.state[80]); fields = copy.deepcopy(provider.fields)
            before = owner.read()
            a = owner.preview({'changes':{'resources':{'documentation':'docs'}}, 'expected_revision':before['revision']})
            concurrent = service()
            b = concurrent.preview({'changes':{'preview':'Concurrent unsaved choice'}, 'expected_revision':before['revision']})
            saved = owner.apply({'plan_id':a['plan_id']})
            self.assertEqual(set(saved['adoption']['queued']), set(records))
            queued = self.registry.read()
            with self.assertRaisesRegex(ValueError, 'Stale|stale'):
                concurrent.apply({'plan_id':b['plan_id']})
            self.assertEqual(self.registry.read(), queued, 'A stale later Save cannot erase committed adoption intents')
            schema = cli.configuration_model(engine, root).sync_schema()
            for path, flight in [(root,'settings-main'), (peer,'settings-peer')]:
                original = records[flight]
                self.assertEqual(self.guard.verify(path,self.registry,flight,policy=self.policy)['configuration_revision'], original['configuration']['revision'])
                self.assertEqual(self.registry.get(flight)['configuration'],original['configuration'],'Read-only verify cannot adopt')
                with patch.dict(os.environ, CODEX_THREAD_ID='session-1'):
                    with self.guard.settings_execution(path, {'checkout_binding':{'registry':str(self.registry.directory),'flight':flight}}, adopt=True):
                        pass
                active = self.registry.get(flight)
                self.assertEqual(active['configuration']['revision'],saved['revision'])
                self.assertEqual(active['grants'],original['grants'])
                self.assertEqual(active['status_sync'],original['status_sync'])
                self.assertEqual(active['checkout'],original['checkout'])
                self.assertEqual(active['children'],original['children'])
                self.assertEqual(active['checkout_guard']['generation'],original['checkout_guard']['generation'])
                denied = schema.authorize(active['grants']['tracker_status'],active['repository']['id'],active['configuration'],80)
                self.assertFalse(denied['authorized']);self.assertEqual(denied['reason'],'configuration_changed')
                self.assertIn('status_sync',active['reconfiguration']['required_revalidation'])
                self.assertNotIn('checks',active['reconfiguration']['required_revalidation'],'A documentation pointer does not invalidate unrelated check definitions')
            denied = synchronize('review', ready=True)
            self.assertEqual(denied['outcomes'][0]['reason'],'configuration_changed')
            self.assertEqual(provider.state[80],manual); self.assertEqual(provider.fields,fields)
            active=self.registry.get('settings-main')
            active['grants']['tracker_status']['configuration_revision']=active['configuration']['revision']
            active['grants']['tracker_status']['reference']='Owner separately reconciles exact current status authority'
            active['grant_reference']='Owner separately reconciles exact current status authority'
            self.registry.save(active,expected_revision=self.registry.read()['revision'])
            conflict=synchronize('review',ready=True)
            self.assertEqual(conflict['outcomes'][0]['reason'],'conflict','A new grant cannot erase an observed manual Status decision')
            self.assertEqual(provider.state[80],manual)
            def concurrent_fields():
                provider.fields.update(Sequence='Concurrent owner sequence',Priority='Concurrent owner priority')
            provider.before_write=concurrent_fields
            reviewed=synchronize('review',ready=True,expected={'80':provider.observe(80)},reconciliation_reference='Owner explicitly accepts this observed manual Status for Review')
            self.assertEqual(reviewed['state'],'synchronized')
            self.assertEqual(provider.state[80]['option_id'],policy['options']['review'])
            self.assertEqual(provider.fields['Sequence'],'Concurrent owner sequence')
            self.assertEqual(provider.fields['Priority'],'Concurrent owner priority')
            count=len(provider.mutations)
            blocked=synchronize('accepted_completion',completion={'accepted':True,'full_scope':True,'reference':'Acceptance cannot substitute for actual completed delivery'})
            self.assertEqual(blocked['outcomes'][0]['reason'],'completion_unverified')
            self.assertEqual(len(provider.mutations),count)
            self.assertNotEqual(provider.state[80]['option_id'],policy['options']['done'])
            self.assertEqual(provider.closures,[]);self.assertEqual(provider.membership_writes,[])
            self.assertEqual(self.registry.get('settings-main')['status_sync']['history'],['retained fixture decision'])
            records['settings-main']=self.registry.get('settings-main')
            # The explicitly authorized common CLI path finds the same existing
            # project Registry without a user-supplied flight/task identifier.
            current = cli.configuration_model(engine,root).snapshot(root)
            c,_ = cli.configuration_plan(engine,root,{'resources':{'style_guide':'docs/style.md'}},current['revision'],'Owner CLI project update')
            published = cli.configuration_apply(engine,root,c)
            self.assertEqual(set(published['adoption']['queued']),set(records))
            canonical = (root/engine.CONFIG).read_bytes()
            d,_ = cli.configuration_plan(engine,root,{'preview':'Save interrupted during Registry publication'},published['revision'],'Owner interrupted project Save')
            target = cli.sha(cli.encoded(d['configuration']))
            helper_path = root/'.flightcheck/scripts/flight_associations.py'
            helper = cli.load_installer(helper_path);load = cli.load_installer;save = helper.Registry.save;attempts=[]
            def interrupted(registry, record, expected_revision=None):
                if record.get('pending_configuration',{}).get('revision')==target:
                    attempts.append(record['flight'])
                    if len(attempts)==2:raise ValueError('Fixture Registry interruption')
                return save(registry,record,expected_revision=expected_revision)
            with patch.object(cli,'load_installer',side_effect=lambda path:helper if Path(path)==helper_path else load(path)), patch.object(helper.Registry,'save',interrupted):
                with self.assertRaisesRegex(ValueError,'Registry interruption'):
                    cli.configuration_apply(engine,root,d)
            self.assertEqual(len(attempts),2)
            self.assertEqual((root/engine.CONFIG).read_bytes(),canonical,'Partial intent registration must prevent canonical publication')
            for path,flight in [(root,'settings-main'),(peer,'settings-peer')]:
                with patch.dict(os.environ,CODEX_THREAD_ID='session-1'):
                    with self.guard.settings_execution(path,{'checkout_binding':{'registry':str(self.registry.directory),'flight':flight}},adopt=True):
                        pass
                active=self.registry.get(flight)
                self.assertEqual(active['configuration']['revision'],published['revision'],'The prior committed intent remains recoverable behind an unpublished replacement')
                self.assertEqual(active['grants'],records[flight]['grants'])
                self.assertEqual(active['status_sync'],records[flight]['status_sync'])
            self.assertNotIn('mutation',self.provider_log.read_text(),'Only existing checkout-policy observations were requested')
