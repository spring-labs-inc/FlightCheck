"""Separate confirmed configuration, observation provenance and owned transport outages."""

import json
import os
import socket
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import test_card_startup as startup
import test_route_discovery as fixture


class RouteConfigurationTests(unittest.TestCase):
    project = fixture.RouteDiscoveryTests.project
    prepared = fixture.RouteDiscoveryTests.prepared
    checked = fixture.RouteDiscoveryTests.checked
    args = fixture.RouteDiscoveryTests.args
    fake_ssh = startup.StartupTests.fake_ssh
    stop_forwarders = startup.StartupTests.stop_forwarders

    def setup_route(self):
        case = self.project(); self.root, self.checkout, self.env = case
        self.env.update(CODEX_THREAD_ID="controller", SSH_CONNECTION="synthetic-worker")
        for session in ("controller", "pm", "later"):
            self.assertEqual(self.hook("UserPromptSubmit", session), {})
        initial = self.prepared(case)
        self.fake_ssh()
        connector = fixture.load("connect")
        self.case = case
        directory, = (self.root / "state").glob("*/tasks/first")
        remote_port = json.loads((directory / "endpoint.json").read_text())["port"]
        return initial, connector, directory, remote_port

    def hook(self, kind, session="controller", message=""):
        return json.loads(subprocess.check_output(
            [sys.executable, "-B", "status-card/maintainer.py", "hook"],
            input=json.dumps({"hook_event_name": kind, "cwd": str(self.checkout), "session_id": session,
                              "turn_id": "configuration", "last_assistant_message": message}),
            cwd=self.checkout, env=self.env, text=True, timeout=20))

    def free_port(self):
        with socket.socket() as free:
            free.bind(("127.0.0.1", 0)); return free.getsockname()[1]

    def selected(self, local_port):
        return self.args(checkout=str(self.checkout), remote_state_dir=str(self.root / "state"),
                         remote_python=sys.executable, local_port=local_port, reconcile_route=True)

    def await_card(self, connector, local_port, candidate, remote_port):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            card = connector.maintainer.current_card("first", local_port, candidate, remote_port)
            if card:
                return card
            time.sleep(.05)
        self.fail("Fixture forward did not serve the exact task and candidate")

    def native(self, connector, published, url, local_port, remote_port):
        snapshot = self.await_card(connector, local_port, published["candidate"], remote_port)
        path = self.root / "native.json"
        path.write_text(json.dumps({"schema": 1, "context": published["context"], "observed_at": time.time(),
                                   "tabs": [{"id": "actual-forward", "visible": True, "url": url,
                                             "endpoint_reached": True, "snapshot": snapshot}]}))
        path.chmod(0o600)
        return self.prepared(self.case, extra=["--browser-observation", str(path)], expected=0)

    def test_owned_stop_preserves_metadata_without_same_url_resurrection(self):
        for kind in ("native", "declared"):
            for same_url in (True, False):
                with self.subTest(kind=kind, same_url=same_url):
                    initial, connector, directory, remote_port = self.setup_route()
                    prior_port = self.free_port(); local_port = prior_port if same_url else self.free_port()
                    args = self.selected(local_port)
                    with patch.dict(os.environ, self.connector_env):
                        connection = connector.connection_directory(args)
                        prior = connector.start_forward(args, connection, prior_port, remote_port)
                    self.addCleanup(connector.stop_child, prior)
                    prior_url = connector.maintainer.card_url("first", prior_port)
                    self.await_card(connector, prior_port, initial["candidate"], remote_port)
                    prior_state = (self.native(connector, initial, prior_url, prior_port, remote_port) if kind == "native" else
                                   self.prepared(self.case, extra=["--user-url", prior_url], expected=0))
                    self.checked(self.case, prior_state)
                    self.assertEqual(self.hook("Stop", message=prior_state["footer"]), {})
                    before = json.loads((directory / "reply-route.json").read_text())
                    if same_url:
                        connector.stop_child(prior)
                        deadline = time.monotonic() + 3
                        while not connector.available(prior_port):
                            self.assertLess(time.monotonic(), deadline); time.sleep(.05)
                    children = []; before_stop = []
                    real_start = connector.start_forward; real_write = connector.maintainer.write_json
                    def start(*values):
                        child = real_start(*values); children.append(child)
                        self.addCleanup(connector.stop_child, child)
                        terminate = child.terminate
                        def observed_terminate():
                            before_stop.append(json.loads((directory / "reply-route.json").read_text()))
                            terminate()
                        child.terminate = observed_terminate
                        return child
                    def write(path, value):
                        if path.name == "connection.json":
                            raise OSError("Injected post-confirmation persistence failure")
                        return real_write(path, value)
                    with patch.dict(os.environ, self.connector_env), patch.object(connector, "start_forward", side_effect=start), \
                            patch.object(connector.maintainer, "write_json", side_effect=write):
                        with self.assertRaisesRegex(OSError, "Injected post-confirmation"):
                            connector.establish(args, connection)
                    self.assertEqual(len(children), 1); self.assertIsNotNone(children[0].poll())
                    with self.subTest(boundary="negative-before-owned-stop", kind=kind, same_url=same_url):
                        self.assertEqual(bool(before_stop[-1].get("route_unverified")), same_url)
                    # Publication itself must not resurrect a known outage.
                    with self.subTest(boundary="ordinary-no-url-prepare", kind=kind, same_url=same_url):
                        self.prepared(self.case, expected=1 if same_url else 0)
                    with self.subTest(boundary="reply-check", kind=kind, same_url=same_url):
                        self.checked(self.case, prior_state, expected=1 if same_url else 0)
                    with self.subTest(boundary="native-stop", kind=kind, same_url=same_url):
                        decision = self.hook("Stop", message=prior_state["footer"])
                        self.assertEqual(decision.get("decision"), "block" if same_url else None)
                    with self.subTest(boundary="metadata", kind=kind, same_url=same_url):
                        after = json.loads((directory / "reply-route.json").read_text())
                        self.assertEqual(after["user_url"], prior_url)
                        self.assertEqual(after.get("route_verification"), before.get("route_verification"))
                        self.assertEqual(after.get("manual_route"), before.get("manual_route"))
                    if not same_url:
                        self.await_card(connector, prior_port, prior_state["candidate"], remote_port)

    def test_borrowed_live_forward_survives_nonowner_persistence_failure(self):
        initial, connector, directory, remote_port = self.setup_route()
        args = self.selected(self.free_port())
        with patch.dict(os.environ, self.connector_env):
            connection = connector.connection_directory(args)
            owner, child = connector.establish(args, connection)
            self.addCleanup(connector.stop_child, child)
            token = json.loads((directory / "reply-route.json").read_text())["connection_owner"]
            real_write = connector.maintainer.write_json
            def fail(path, value):
                if path.name == "connection.json":
                    raise OSError("Injected borrowed persistence failure")
                return real_write(path, value)
            with patch.object(connector.maintainer, "write_json", side_effect=fail), patch.object(connector, "start_forward") as start:
                with self.assertRaisesRegex(OSError, "Injected borrowed"):
                    connector.establish(args, connection, allow_start=False)
                start.assert_not_called()
            self.assertIsNone(child.poll())
            self.assertEqual(json.loads((directory / "reply-route.json").read_text())["connection_owner"], token)
            self.prepared(self.case, expected=0); self.checked(self.case, owner)
            self.assertEqual(self.hook("Stop", message=owner["footer"]), {})
            self.await_card(connector, args.local_port, owner["candidate"], remote_port)
            self.assertTrue(connector.release_forward(args, child))

    def test_manual_configuration_survives_observations_and_known_outage(self):
        initial, connector, directory, remote_port = self.setup_route()
        args = self.selected(self.free_port())
        with patch.dict(os.environ, self.connector_env):
            connection = connector.connection_directory(args)
            owner, child = connector.establish(args, connection)
        self.addCleanup(connector.stop_child, child)
        url = owner["user_url"]
        declared = self.prepared(self.case, extra=["--user-url", url], expected=0)
        self.prepared(self.case, session="pm", extra=["--reconcile-route"], expected=0)
        original_config = json.loads((directory / "reply-route.json").read_text())["manual_route"]
        for provenance in ("native", "connector"):
            if provenance == "native":
                fresh = self.native(connector, declared, url, args.local_port, remote_port)
            else:
                self.await_card(connector, args.local_port, owner["candidate"], remote_port)
                with patch.dict(os.environ, self.connector_env):
                    connector.connection_observation_remote(args, args.connection_confirmation, renew=True)
                fresh = owner
            before = json.loads((directory / "reply-route.json").read_text())
            with self.subTest(provenance=provenance, boundary="pm-configuration-reuse"):
                pm = self.prepared(self.case, session="pm", expected=0)
                self.assertEqual(pm["user_url"], url)
                self.assertEqual(pm["browser_reachability"], "unobserved")
                self.assertEqual(pm["browser_rendering"], "unobserved")
                self.checked(self.case, pm, session="pm")
                self.assertEqual(self.hook("Stop", session="pm", message=pm["footer"]), {})
                after = json.loads((directory / "reply-route.json").read_text())
                self.assertEqual(after["route_verification"], before["route_verification"])
                self.assertEqual(after["context"], before["context"])
                self.assertEqual(after["manual_route"], original_config)
        self.checked(self.case, fresh, session="later", expected=1)
        before = json.loads((directory / "reply-route.json").read_text())
        with self.subTest(boundary="explicit-new-caller-config-only"):
            later = self.prepared(self.case, session="later", extra=["--reconcile-route"], expected=0)
            self.checked(self.case, later, session="later")
            after = json.loads((directory / "reply-route.json").read_text())
            self.assertEqual(after["route_verification"], before["route_verification"])
            self.assertEqual(after["context"], before["context"])
            self.assertEqual(after["manual_route"]["configured_at"], original_config["configured_at"])
        current = json.loads((directory / "reply-route.json").read_text())
        current["route_verification"]["observed_at"] -= 31
        (directory / "reply-route.json").write_text(json.dumps(current))
        (self.checkout / "new-candidate.txt").write_text("New candidate, same confirmed configuration\n")
        with self.subTest(boundary="configuration-without-fresh-observation-inheritance"):
            pm = self.prepared(self.case, session="pm", expected=0)
            self.checked(self.case, pm, session="pm")
            after = json.loads((directory / "reply-route.json").read_text())
            self.assertEqual(after["route_verification"], current["route_verification"])
            self.assertEqual(pm["browser_reachability"], "unobserved")
        with patch.dict(os.environ, self.connector_env):
            self.assertTrue(connector.release_forward(args, child))
        with self.subTest(boundary="outage-publication-retains-configuration"):
            stopped = self.prepared(self.case, session="pm", expected=1)
            self.assertEqual(stopped["user_url"], url)
            saved = json.loads((directory / "reply-route.json").read_text())
            self.assertEqual(saved["manual_route"]["source_context"], original_config["source_context"])
            self.assertEqual(saved["manual_route"]["configured_at"], original_config["configured_at"])
            self.checked(self.case, dict(stopped, footer=owner["footer"]), session="pm", expected=1)
            self.assertEqual(self.hook("Stop", session="pm", message=owner["footer"]).get("decision"), "block")
        # Reuse the retained route with actual successful browser-side probes;
        # no --user-url input or new declaration/configuration is supplied.
        with patch.dict(os.environ, self.connector_env):
            recovered, child2 = connector.establish(args, connection)
        self.addCleanup(connector.stop_child, child2)
        recovered_proof = json.loads((directory / "reply-route.json").read_text())
        with self.subTest(boundary="actual-revalidation-without-url-interview"):
            pm = self.prepared(self.case, session="pm", expected=0)
            self.assertEqual(pm["user_url"], url); self.checked(self.case, pm, session="pm")
            saved = json.loads((directory / "reply-route.json").read_text())
            self.assertEqual(saved["route_verification"], recovered_proof["route_verification"])
            self.assertEqual(saved["context"], recovered_proof["context"])
            self.assertEqual(recovered_proof["context"], owner["context"])
            self.assertEqual(pm["browser_reachability"], "unobserved")
            self.assertEqual(saved["manual_route"]["source_context"], original_config["source_context"])
            self.assertEqual(saved["manual_route"]["configured_at"], original_config["configured_at"])
        with patch.dict(os.environ, self.connector_env):
            connector.release_forward(args, child2)


if __name__ == "__main__":
    unittest.main()
