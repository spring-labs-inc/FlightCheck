"""Late adapter failures use real disposable worker publication and reply state."""

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_route_discovery as fixture


class RouteFailureTests(unittest.TestCase):
    project = fixture.RouteDiscoveryTests.project
    prepared = fixture.RouteDiscoveryTests.prepared
    observed = fixture.RouteDiscoveryTests.observed
    checked = fixture.RouteDiscoveryTests.checked
    tab = fixture.RouteDiscoveryTests.tab
    args = fixture.RouteDiscoveryTests.args

    def test_verified_endpoint_existing_tab_witness(self):
        tabs = fixture.load("task_tab")
        endpoint = self.tab()
        for snapshot in (None, dict(endpoint["snapshot"], candidate="a" * 64)):
            with self.subTest(snapshot=snapshot):
                existing = dict(endpoint, id="already-open", visible=True, snapshot=snapshot)
                result = tabs.discover("second", "b" * 64,
                                       {"tabs": [existing], "endpoints": [endpoint], "can_open": True}, 44001)
                self.assertEqual(result["action"], "fallback")
                self.assertEqual(result["browser_visibility"], "unobserved")
                self.assertEqual(result["browser_rendering"], "unobserved")

    def test_connector_late_confirmation_failure_witness(self):
        for failure in ("candidate-change", "final-probe"):
            for prior in (False, True):
                with self.subTest(failure=failure, prior=prior):
                    case = self.project(); root, checkout, env = case
                    env.update(CODEX_THREAD_ID="controller", SSH_CONNECTION="synthetic-worker")
                    def hook(kind, message=""):
                        payload = {"hook_event_name": kind, "cwd": str(checkout), "session_id": "controller",
                                   "turn_id": "late-confirmation", "last_assistant_message": message}
                        return json.loads(subprocess.check_output(
                            [sys.executable, "-B", "status-card/maintainer.py", "hook"],
                            input=json.dumps(payload), cwd=checkout, env=env, text=True, timeout=20))
                    self.assertEqual(hook("UserPromptSubmit"), {})
                    initial = self.prepared(case)
                    path, observation, directory = self.observed(case, initial)
                    if prior:
                        initial = self.prepared(case, extra=["--browser-observation", str(path)], expected=0)
                    before = json.loads((directory / "reply-route.json").read_text())
                    number = json.loads((directory / "endpoint.json").read_text())["port"]
                    binary = root / "bin"; binary.mkdir()
                    script = binary / "ssh"
                    script.write_text("#!" + sys.executable + "\nimport os,subprocess,sys\n"
                                      "env=dict(os.environ);env.pop('CODEX_THREAD_ID',None)\n"
                                      "r=subprocess.run(['/bin/sh','-c',sys.argv[-1]],env=env);sys.exit(r.returncode)\n")
                    script.chmod(0o755)
                    connector = fixture.load("connect")
                    args = self.args(checkout=str(checkout), remote_state_dir=str(root / "state"),
                                     remote_python=sys.executable, local_port=number)
                    real_prepare = connector.prepare_remote; real_card = connector.maintainer.current_card
                    probes = []
                    def browser_probe(*values):
                        probes.append(values)
                        return None if failure == "final-probe" and len(probes) == 2 else real_card(*values)
                    def remote_prepare(selected, url=None, **kwargs):
                        if url and failure == "candidate-change":
                            (checkout / "candidate-changed.txt").write_text("Changed during final confirmation\n")
                        return real_prepare(selected, url, **kwargs)
                    with patch.dict(os.environ, dict(env, PATH=str(binary) + os.pathsep + env.get("PATH", ""),
                                                      FLIGHTCHECK_STATE_DIR=str(root / "browser-state"))), \
                            patch.object(connector, "prepare_remote", side_effect=remote_prepare), \
                            patch.object(connector.maintainer, "current_card", side_effect=browser_probe), \
                            patch.object(connector, "start_forward") as start:
                        connection = connector.connection_directory(args)
                        connector.maintainer.write_json(connection / "connection.json",
                                                        {"local_port": number, "remote_port": number})
                        with self.assertRaises(ValueError):
                            connector.establish(args, connection)
                        start.assert_not_called()
                    after = json.loads((directory / "reply-route.json").read_text())
                    self.assertEqual(after.get("route_verification"), before.get("route_verification"))
                    allowed = prior and failure == "final-probe"
                    resumed = self.prepared(case, expected=0 if allowed else 1)
                    rejected = "FlightCheck: [&lt; status /&gt;](" + initial["host_url"] + ")"
                    self.checked(case, dict(resumed, footer=rejected), expected=1)
                    self.assertEqual(hook("Stop", rejected).get("decision"), "block")
                    if allowed:
                        self.checked(case, initial)
                        self.assertEqual(hook("Stop", initial["footer"]), {})
                    else:
                        decision = hook("Stop", initial["footer"])
                        self.assertEqual(decision.get("decision"), "block")
                        self.assertNotIn("http", resumed["footer"])


if __name__ == "__main__":
    unittest.main()
