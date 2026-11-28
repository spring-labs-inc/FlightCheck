"""Project-resource selection stays private, bounded and non-mutating."""
import http.client
import http.server
import json
import threading
import unittest

import test_settings as fixtures


class SettingsBrowseTests(unittest.TestCase):
    config_fixture = fixtures.SettingsTests.config_fixture
    config_module = fixtures.SettingsTests.config_module
    config_git = fixtures.SettingsTests.config_git
    config_cli = fixtures.SettingsTests.config_cli
    service = fixtures.SettingsTests.service
    save = fixtures.SettingsTests.save

    def test_project_browser_lists_and_selects_without_config_writes(self):
        with self.config_fixture() as (area, root, engine, installed, cli, supplied):
            docs = root / 'docs'; docs.mkdir(); (docs / 'style.md').write_text('Style contents are never returned')
            (docs / 'runbook.md').write_text('Operational contents'); (docs / '.private').write_text('Never list')
            nested = docs / 'guides'; nested.mkdir()
            outside = area / 'outside'; outside.mkdir(); (outside / 'secret').write_text('Secret')
            (docs / 'escape').symlink_to(outside, target_is_directory=True)
            service = self.service(engine, root)
            with self.assertRaisesRegex(ValueError, 'outside the checkout'):
                self.save(service, {'evidence_dir': str(root / 'private-evidence')})
            before = (root / engine.CONFIG).read_bytes()
            data = service.browse({'field': 'resources.style_guide', 'path': 'docs'})
            self.assertEqual(data['directory'], 'docs'); self.assertEqual(data['parent'], '')
            self.assertEqual({v['name'] for v in data['entries']}, {'style.md', 'runbook.md', 'guides'})
            self.assertNotIn('contents', json.dumps(data))
            self.assertEqual(service.browse({'field': 'resources.style_guide', 'path': 'docs/style.md', 'select': True})['selected'], 'docs/style.md')
            self.assertEqual(service.browse({'field': 'resources.documentation', 'path': 'docs', 'select': True})['selected'], 'docs')
            self.assertEqual(service.browse({'field': 'resources.logs', 'path': 'docs/runbook.md', 'select': True})['selected'], 'docs/runbook.md')
            for path in ['../outside', str(outside), '.git', 'docs/.private', 'docs/escape']:
                with self.subTest(path=path), self.assertRaises((OSError, ValueError)):
                    service.browse({'field': 'resources.logs', 'path': path})
            for field, path in [('resources.documentation', 'docs/style.md'), ('resources.style_guide', 'docs'), ('evidence_dir', 'docs'), ('checks', 'docs')]:
                with self.subTest(field=field), self.assertRaises(ValueError):
                    service.browse({'field': field, 'path': path, 'select': True})
            self.assertEqual((root / engine.CONFIG).read_bytes(), before)

    def test_project_browser_requires_exact_settings_authorization(self):
        with self.config_fixture() as (_, root, engine, installed, cli, supplied):
            from flightcheck_cli.settings import Handler
            (root / 'docs').mkdir(); service = self.service(engine, root)
            with http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
                server.settings, server.route, server.assets = service, '/task/settings-flight/settings/', fixtures.PRODUCT / 'status-card'
                thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
                def post(headers):
                    connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
                    connection.request('POST', server.route + 'api/browse', json.dumps({'field': 'resources.documentation', 'path': ''}), headers)
                    response = connection.getresponse(); data = response.read(); connection.close(); return response.status, data
                try:
                    headers = {'Authorization': 'Bearer ' + service.token, **{'X-FlightCheck-' + k.title():v for k,v in service.context.items()}}
                    self.assertEqual(post(headers)[0], 200)
                    self.assertEqual(post({})[0], 403)
                    for key in ['Project', 'Task', 'Session']:
                        wrong = {**headers, 'X-FlightCheck-' + key:'another'}; self.assertEqual(post(wrong)[0], 403)
                    self.assertEqual(post({**headers, 'Origin':'https://unrelated.invalid'})[0], 403)
                finally:
                    server.shutdown(); thread.join()


if __name__ == '__main__': unittest.main()
