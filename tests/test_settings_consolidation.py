"""Focused counterexamples for one Settings decision and scoped navigation."""
import copy
import json
import unittest
from unittest.mock import patch

import test_settings as fixtures


class SettingsConsolidationTests(unittest.TestCase):
    config_fixture = fixtures.SettingsTests.config_fixture
    config_module = fixtures.SettingsTests.config_module
    config_git = fixtures.SettingsTests.config_git
    config_cli = fixtures.SettingsTests.config_cli
    service = fixtures.SettingsTests.service
    save = fixtures.SettingsTests.save

    def test_optional_clear_is_missing_not_unavailable(self):
        with self.config_fixture() as (_, root, engine, installed, cli, supplied):
            service = self.service(engine, root)
            self.save(service, {'resources': {'documentation': 'docs/index.md', 'logs': {'unavailable': 'Access denied by owner'}}})
            self.save(service, {'resources': {'documentation': None}})
            snapshot = service.read()
            self.assertNotIn('documentation', snapshot['values']['resources'])
            self.assertNotIn('resources.documentation', snapshot['values']['_flightcheck']['fields'])
            self.assertEqual(snapshot['values']['resources']['logs'], {'unavailable': 'Access denied by owner'})
            self.assertEqual(self.config_cli('read', root)['values'], snapshot['values'])
            self.save(service, {'checkout_policy': {'branch_prefix': 'task/'}})
            self.save(service, {'checkout_policy': {'branch_prefix': None}})
            self.assertNotIn('branch_prefix', service.read()['values']['checkout_policy'])

    def test_readonly_board_names_and_ambiguous_discovery(self):
        with self.config_fixture() as (_, root, engine, installed, cli, supplied):
            service = self.service(engine, root)
            before = (root / engine.CONFIG).read_bytes()
            policy = copy.deepcopy(service.read()['values']['status_sync'])
            calls = []
            fields = [{'id': 'FIELD', 'name': 'Status', 'options': [{'id': 'OPT-A', 'name': 'Queued'}, {'id': 'OPT-B', 'name': 'Building'}]}]
            result = {'project': {'id': 'PROJECT', 'title': 'Team delivery', 'url': 'https://github.com/orgs/example/projects/7', 'closed': False, 'fields': {'nodes': fields, 'pageInfo': {'hasNextPage': False}}}}
            class Provider:
                def query(self, query, variables, *, mutation=False):
                    calls.append((query, variables, mutation))
                    return copy.deepcopy(result)
            with patch.object(service, 'board_provider', return_value=Provider()):
                data = service.board_discover({'url': result['project']['url'], 'authorize_read': True})
                self.assertEqual(data['title'], 'Team delivery')
                self.assertEqual(data['field']['options'][0], {'id': 'OPT-A', 'name': 'Queued'})
                self.assertTrue(calls); self.assertTrue(all(not mutation and 'mutation' not in query for query, _, mutation in calls))
                self.assertEqual((root / engine.CONFIG).read_bytes(), before)
                self.assertEqual(service.read()['values']['status_sync'], policy)
                with self.assertRaisesRegex(ValueError, 'explicit read'):
                    service.board_discover({'url': result['project']['url']})
                with self.assertRaises(ValueError):
                    service.board_discover({'url': 'https://evil.example/orgs/example/projects/7', 'authorize_read': True})
                result['project']['fields']['nodes'].append({'id': 'OTHER', 'name': 'Status', 'options': fields[0]['options']})
                with self.assertRaisesRegex(ValueError, 'ambiguous'):
                    service.board_discover({'url': result['project']['url'], 'authorize_read': True})
                result['project']['fields']['pageInfo']['hasNextPage'] = True
                with self.assertRaisesRegex(ValueError, 'incomplete'):
                    service.board_discover({'url': result['project']['url'], 'authorize_read': True})
            self.assertEqual((root / engine.CONFIG).read_bytes(), before)


if __name__ == '__main__': unittest.main()
