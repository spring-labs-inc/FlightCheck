"""Real GitHub-adapter dispatch/readback boundary; isolated runner and Registry."""
import copy
import json
import subprocess
import unittest

import test_status_sync as witness


class StatusSyncReadbackTests(unittest.TestCase):
    fixture = witness.StatusSynchronizationTests.fixture
    flight_git = witness.StatusSynchronizationTests.flight_git
    flight_repo = witness.StatusSynchronizationTests.flight_repo
    flight_checkout = witness.StatusSynchronizationTests.flight_checkout
    event = witness.StatusSynchronizationTests.event

    def adapter_fixture(self, f, *, fail_before_dispatch=False):
        registry, sync, policy = f[3], f[5], f[4].policy
        live = {'option': policy['options']['todo'], 'updated': 'initial-todo',
                'Priority': 'Initial owner priority', 'Sequence': 'Owner sequence',
                'outage': False, 'mapping_reads': 0, 'failed_reads': 0,
                'mutations': [], 'intent_at_dispatch': None}
        def runner(argv, **kwargs):
            self.assertEqual(argv, ['gh', 'api', 'graphql', '--input', '-'])
            request = json.loads(kwargs['input'])
            query, variables = request['query'], request['variables']
            if 'mutation(' in query:
                self.assertIn('updateProjectV2ItemFieldValue', query)
                self.assertEqual(variables['project'], policy['project_id'])
                self.assertEqual(variables['field'], policy['field_id'])
                self.assertEqual(variables['item'], 'existing-item-11')
                live['intent_at_dispatch'] = copy.deepcopy(registry.get('owned-flight')['status_sync']['pending']['11'])
                live['mutations'].append(copy.deepcopy(request))
                live.update(option=variables['option'], updated='applied-' + str(len(live['mutations'])), outage=True)
                data = {'updateProjectV2ItemFieldValue': {'projectV2Item': {'id': 'existing-item-11'}}}
            elif live['outage']:
                live['failed_reads'] += 1
                return subprocess.CompletedProcess(argv, 1, '', 'Fixture post-dispatch read unavailable')
            elif 'field:node' in query:
                live['mapping_reads'] += 1
                if fail_before_dispatch and live['mapping_reads'] == 2:
                    live['failed_reads'] += 1
                    return subprocess.CompletedProcess(argv, 1, '', 'Fixture pre-dispatch read unavailable')
                data = {'project': {'id': policy['project_id'], 'closed': False, 'viewerCanUpdate': True},
                        'field': {'id': policy['field_id'], 'project': {'id': policy['project_id']},
                                  'options': [{'id': x} for x in policy['options'].values()]}}
            elif 'projectItems(' in query:
                self.assertEqual(variables['number'], 11)
                data = {'repository': {'nameWithOwner': 'owner/repository', 'issue': {'number': 11,
                        'state': 'OPEN', 'stateReason': None, 'projectItems': {'pageInfo': {'hasNextPage': False},
                        'nodes': [{'id': 'existing-item-11', 'isArchived': False, 'project': {'id': policy['project_id']}}]}}}}
            elif 'fieldValues(' in query:
                data = {'node': {'id': 'existing-item-11', 'project': {'id': policy['project_id']},
                        'fieldValues': {'pageInfo': {'hasNextPage': False}, 'nodes': [
                        {'field': {'id': policy['field_id']}, 'optionId': live['option'], 'updatedAt': live['updated']}]}}}
            elif 'workflows(' in query:
                data = {'node': {'id': policy['project_id'], 'workflows': {'pageInfo': {'hasNextPage': False},
                        'nodes': [{'id': 'observed-owner-workflow', 'name': 'Fixture metadata', 'enabled': True}]}}}
            else:
                self.fail(query)
            return subprocess.CompletedProcess(argv, 0, json.dumps({'data': data}), '')
        return sync.GitHubProjects('owner/repository', policy, runner=runner), live

    def execute(self, f, adapter, event):
        return f[5].synchronize(f[3], 'owned-flight', event, checkout=f[2], provider=adapter,
                                verifier=lambda *args: {'status': 'verified'}, pause=lambda delay: None)

    def test_acknowledged_mutation_readback_outage_retains_intent(self):
        with self.fixture() as f:
            adapter, live = self.adapter_fixture(f)
            exact_event = json.dumps(self.event(), sort_keys=True).encode()
            first = self.execute(f, adapter, json.loads(exact_event))
            original = copy.deepcopy(live['intent_at_dispatch'])
            self.assertIsInstance(original, dict, 'Actual public operation must persist intent before dispatch')
            self.assertEqual(original['attempts'], 1)
            self.assertEqual(original['before']['option_id'], f[4].policy['options']['todo'])
            self.assertEqual(original['before']['status_updated_at'], 'initial-todo')
            with self.subTest(observable='unverified_post_dispatch_outcome'):
                self.assertEqual(first['state'], 'unsynchronized')
                self.assertEqual(first['outcomes'][0]['reason'], 'ambiguous')
                self.assertEqual(len(live['mutations']), 1)
                self.assertGreaterEqual(live['failed_reads'], 2, 'Immediate readback and same-event reconciliation both unavailable')
            with self.subTest(observable='persisted_unknown_intent'):
                self.assertEqual(f[3].get('owned-flight')['status_sync']['pending'].get('11'), original)
            # The maintainer makes a new explicit field decision during the outage.
            live.update(option=f[4].policy['options']['todo'], updated='manual-owner-todo',
                        Priority='Owner priority after outage', outage=False)
            repeated = self.execute(f, adapter, json.loads(exact_event))
            with self.subTest(observable='replay_preserves_manual_status'):
                self.assertEqual(repeated['state'], 'unsynchronized', repeated)
                self.assertEqual(repeated['outcomes'][0]['reason'], 'conflict')
                self.assertEqual(live['option'], f[4].policy['options']['todo'])
                self.assertEqual(live['updated'], 'manual-owner-todo')
            with self.subTest(observable='no_extra_mutation_or_budget_loss'):
                self.assertEqual(len(live['mutations']), 1)
                self.assertEqual(f[3].get('owned-flight')['status_sync']['pending'].get('11'), original)
            with self.subTest(observable='unrelated_fields_preserved'):
                self.assertEqual(live['Priority'], 'Owner priority after outage')
                self.assertEqual(live['Sequence'], 'Owner sequence')
        # Definitively pre-dispatch read failure is not a dispatched write with
        # unknown outcome. Exercise the adapter's fresh pre-mutation observation.
        with self.fixture() as f:
            adapter, live = self.adapter_fixture(f, fail_before_dispatch=True)
            result = self.execute(f, adapter, self.event())
            self.assertEqual(result['state'], 'unsynchronized')
            self.assertEqual(result['outcomes'][0]['reason'], 'provider_unavailable')
            self.assertEqual(live['mapping_reads'], 2)
            self.assertEqual(live['mutations'], [])
            self.assertIsNone(live['intent_at_dispatch'])
            self.assertEqual(f[3].get('owned-flight')['status_sync']['pending'], {})
            self.assertEqual(live['option'], f[4].policy['options']['todo'])
            self.assertEqual(live['Priority'], 'Initial owner priority')
