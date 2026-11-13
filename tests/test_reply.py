"""Exercise portable controller reply checks against real disposable task cards."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

PRODUCT = Path(os.environ.get("FLIGHTCHECK_PRODUCT_ROOT", Path(__file__).resolve().parents[1]))


class ReplyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.checkout = self.root / "checkout with spaces"
        self.checkout.mkdir()
        shutil.copytree(PRODUCT / "status-card", self.checkout / "status-card")
        self.readme = self.checkout / "README.md"
        self.readme.write_text("Original fixture\n")
        self.state = self.root / "private state"
        self.draft = self.root / "reply.txt"
        self.env = {key: value for key, value in os.environ.items() if key not in
                    ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY", "CODESPACES", "REMOTE_CONTAINERS")}
        self.env.update(FLIGHTCHECK_STATE_DIR=str(self.state), PYTHONDONTWRITEBYTECODE="1")
        self.listeners = set()
        self.addCleanup(self.stop_listeners)
        self.git("init", "-q")
        self.git("add", ".")
        self.git("commit", "-qm", "Disposable reply fixture")

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
             "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", *args],
            cwd=self.checkout, env=self.env, text=True, stderr=subprocess.DEVNULL).strip()

    def stop_listeners(self):
        for pid in self.listeners:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def api(self, command, *args, expected=0, env=None, cwd=None):
        result = subprocess.run([sys.executable, "-B", str(self.checkout / "status-card/reply.py"),
                                 command, "--task", "test-change", *args],
                                cwd=cwd or self.checkout, env=env or self.env,
                                capture_output=True, text=True, timeout=20)
        for p in self.state.glob("*/tasks/*/endpoint.json"):
            self.listeners.add(json.loads(p.read_text())["pid"])
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def directory(self):
        directory, = self.state.glob("*/tasks/test-change")
        return directory

    def snapshot(self):
        return json.loads((self.directory() / "status.json").read_text())

    def endpoint(self):
        return json.loads((self.directory() / "endpoint.json").read_text())

    def check(self, text, phase="update", expected=0, *args):
        self.draft.write_text(text)
        return self.api("check", "--phase", phase, "--reply-file", str(self.draft), *args, expected=expected)

    def wait_stopped(self, port):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=.1):
                    pass
            except OSError:
                return
            time.sleep(.02)
        self.fail("Listener did not stop")

    def test_lifecycle_recovers_and_binds_current_candidate(self):
        first = self.api("prepare", "--title", "Synthetic flight")
        self.assertEqual(first["status"], "published")
        self.assertEqual(first["publication"], "verified")
        self.assertIn("regular browser", first["guidance"])
        self.assertIn(first["user_url"], first["guidance"])
        self.assertEqual(self.snapshot()["candidate"], first["candidate"])
        self.check(first["footer"])
        endpoint = self.endpoint()
        os.kill(endpoint["pid"], signal.SIGTERM)
        self.wait_stopped(endpoint["port"])
        self.readme.write_text("Changed while the listener was stopped\n")
        stale = self.check(first["footer"], "resume", 1)
        self.assertEqual(stale["publication"], "unavailable")
        self.assertEqual(stale["status"], "unavailable")
        recovered = self.api("prepare")
        self.assertEqual(recovered["footer"], first["footer"])
        self.assertNotEqual(recovered["candidate"], first["candidate"])
        self.assertEqual(self.snapshot()["candidate"], recovered["candidate"])
        self.assertEqual(self.snapshot()["verdict"], "Pending")
        self.assertNotEqual(self.endpoint()["pid"], endpoint["pid"])
        self.check(first["footer"], "resume")

        # A live port is insufficient: the snapshot must belong to this task.
        path = self.directory() / "status.json"
        original = path.read_bytes()
        damaged = json.loads(original)
        damaged["task"] = "wrong-task"
        path.write_text(json.dumps(damaged))
        self.assertEqual(self.check(first["footer"], expected=1)["publication"], "unavailable")
        unavailable = self.api("prepare", expected=1)
        self.assertEqual(unavailable["status"], "unavailable")
        self.assertEqual(unavailable["footer"], first["footer"])
        path.write_bytes(original)

        # A busy recorded port must not cause a new URL or kill its new owner.
        endpoint = self.endpoint()
        os.kill(endpoint["pid"], signal.SIGTERM)
        self.wait_stopped(endpoint["port"])
        with socket.socket() as occupied:
            occupied.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            occupied.bind(("127.0.0.1", endpoint["port"]))
            occupied.listen()
            unavailable = self.api("prepare", expected=1)
            self.assertEqual(unavailable["publication"], "unavailable")
            self.assertEqual(unavailable["footer"], first["footer"])
            self.assertEqual(self.endpoint()["port"], endpoint["port"])
            self.assertEqual(occupied.getsockname(), ("127.0.0.1", endpoint["port"]))
        self.assertEqual(self.api("prepare")["footer"], first["footer"])

    def test_every_controller_phase_requires_exact_final_footer(self):
        prepared = self.api("prepare")
        footer = prepared["footer"]
        for phase in ("start", "update", "approval", "blocker", "repair", "resume", "end"):
            with self.subTest(phase=phase):
                self.assertEqual(self.check("Controller update.\n\n" + footer, phase)["status"], "published")
                self.assertEqual(self.check("Missing footer.", phase, 1)["status"], "blocked")
                wrong = footer.replace("/test-change/", "/another-task/")
                self.assertEqual(self.check("Update.\n\n" + wrong, phase, 1)["status"], "blocked")
        for text in ("```\n\n" + footer, "~~~\n\n" + footer, "Update.\n" + footer,
                     footer + "\n\nVerdict: APPROVE", footer + "\nExtra text"):
            self.assertEqual(self.check(text, expected=1)["status"], "blocked")
        self.check("Verdict: Pending\n\n" + footer, "end")
        self.assertEqual(self.check("Verdict: APPROVE\n\n" + footer, "end", 1)["status"], "blocked")
        self.api("prepare", "--verdict", "APPROVE", "--verdict-candidate", prepared["candidate"])
        self.check("Verdict: APPROVE\n\n" + footer, "end")
        # Editing without republishing makes even the right URL insufficient.
        self.readme.write_text("New candidate\n")
        self.assertEqual(self.check(footer, expected=1)["publication"], "unavailable")
        self.assertEqual(self.api("prepare")["footer"], footer)
        self.assertEqual(self.check("Verdict: APPROVE\n\n" + footer, "repair", 1)["status"], "blocked")
        self.check(footer, "repair")

    def test_ordinary_and_reviewer_contexts_are_side_effect_free(self):
        raw = b'{"role":"EVIDENCE","verdict":"APPROVE","coverage":"FlightCheck: /task/test-change/; run prepare"}\n'
        self.draft.write_bytes(raw)
        # No Git executable, no checkout, no state: both commands must bypass
        # before any lifecycle or draft access, regardless of controller-like text.
        env = dict(self.env, PATH="")
        before = sorted(str(p) for p in self.root.rglob("*"))
        for context in ("ordinary", "reviewer"):
            for command in ("prepare", "check"):
                result = self.api(command, "--context", context, "--reply-file", str(self.root / "missing-draft"),
                                  cwd=self.root, env=env)
                self.assertEqual(result, {"status": "bypassed", "context": context})
        self.assertEqual(self.draft.read_bytes(), raw)
        self.assertEqual(json.loads(self.draft.read_text())["role"], "EVIDENCE")
        self.assertFalse(self.state.exists())
        self.assertEqual(sorted(str(p) for p in self.root.rglob("*")), before)

    def test_html_hidden_footer_is_rejected(self):
        prepared = self.api("prepare")
        footer = prepared["footer"]
        for prefix in ("Update.\n\n<!--", "Update.\n\n<details>", "Update.\n\n<pre>",
                       "Update.\n\n<pre/>", "Update.\n\n<details/>"):
            with self.subTest(prefix=prefix):
                self.assertEqual(self.check(prefix + "\n\n" + footer, expected=1)["status"], "blocked")
        for prefix in ("Update.\n\n<!-- closed comment -->", "<details>Earlier details</details>",
                       "Example: `<!--`", "```html\n<!--\n<pre>\n```", "See <https://example.com>."):
            with self.subTest(visible_prefix=prefix):
                self.assertEqual(self.check(prefix + "\n\n" + footer)["status"], "published")

    def test_local_remote_routes_are_explicit_loopback_and_stable(self):
        env = dict(self.env, SSH_CONNECTION="synthetic remote hint")
        remote = self.api("prepare", env=env, expected=1)
        self.assertEqual(remote["execution"], "remote")
        self.assertEqual(remote["publication"], "verified")
        self.assertEqual(remote["status"], "unavailable")
        self.assertIsNone(remote["user_url"])
        self.assertEqual(remote["browser_reachability"], "unobserved")
        self.assertEqual(remote["browser_rendering"], "unobserved")
        self.assertIn("ssh -N -L 127.0.0.1:", remote["guidance"])
        route = urlsplit(remote["host_url"])
        self.assertEqual(route.hostname, "127.0.0.1")
        with socket.socket() as user_listener:
            user_listener.bind(("127.0.0.1", 0))
            user_listener.listen()
            user_listener.settimeout(.1)
            forwarded = f"http://127.0.0.1:{user_listener.getsockname()[1]}/task/test-change/"
            declared = self.api("prepare", "--user-url", forwarded, env=env)
            self.assertEqual(declared["user_url"], forwarded)
            self.assertEqual(declared["host_url"], remote["host_url"])
            self.assertEqual(declared["browser_rendering"], "unobserved")
            self.assertIn(forwarded, declared["guidance"])
            # Root instructions require the maintainer command's exact output;
            # it must agree with the portable guard's declared browser route.
            maintainer_footer = subprocess.check_output(
                [sys.executable, "-B", str(self.checkout / "status-card/maintainer.py"), "card",
                 "--task", "test-change", "--title", "Synthetic remote flight"],
                cwd=self.checkout, env=env, text=True, timeout=20).strip()
            self.assertEqual(maintainer_footer, declared["footer"])
            # A forward declaration never probes the user's loopback from the host.
            with self.assertRaises(socket.timeout):
                user_listener.accept()
            self.assertEqual(self.api("prepare", env=env)["footer"], declared["footer"])
            self.draft.write_text("Remote controller update.\n\n" + declared["footer"])
            self.assertEqual(self.api("check", "--reply-file", str(self.draft), env=env)["publication"], "verified")
            before = (self.directory() / "reply-route.json").read_bytes()
            for invalid in ("http://0.0.0.0:9999/task/test-change/", "http://example.com:9999/task/test-change/",
                            forwarded.replace("test-change", "wrong-task"), forwarded + "?key=value",
                            forwarded.replace("://", "://user:password@"), "https://localhost:9999/task/test-change/",
                            "http://127.0.0.1:9999/task/test-change/"):
                self.api("prepare", "--user-url", invalid, env=env, expected=1)
                self.assertEqual((self.directory() / "reply-route.json").read_bytes(), before)
            changed = self.api("check", "--reply-file", str(self.draft), expected=1)
            self.assertIn("Execution context changed", changed["error"])
        # Inspect the actual server factory boundary, without binding an external interface.
        path = self.checkout / "status-card/serve.py"
        spec = importlib.util.spec_from_file_location("reply_server_fixture", path)
        module = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(path.parent))
        try:
            spec.loader.exec_module(module)
            with patch.object(sys, "argv", [str(path), "--port", "12345"]), \
                    patch.object(module, "ThreadingHTTPServer", side_effect=RuntimeError("bind boundary")) as factory:
                with self.assertRaisesRegex(RuntimeError, "bind boundary"):
                    module.main()
                self.assertEqual(factory.call_args.args[0], ("127.0.0.1", 12345))
        finally:
            sys.path.pop(0)

    def test_stalled_publication_is_bounded_and_unavailable(self):
        server = self.checkout / "status-card/serve.py"
        pid_file = self.root / "stalled.pid"
        server.write_text("import os,time\nfrom pathlib import Path\nPath(" + repr(str(pid_file))
                          + ").write_text(str(os.getpid()))\n"
                          + "print('FlightCheck status card at ',end='',flush=True)\ntime.sleep(60)\n")
        start = time.monotonic()
        result = self.api("prepare", expected=1)
        self.assertLess(time.monotonic() - start, 9)
        self.assertEqual(result["publication"], "unavailable")
        self.assertEqual(result["footer"], "FlightCheck: &lt; status /&gt;")
        self.assertNotIn("Open the live card", result["guidance"])
        with self.assertRaises(ProcessLookupError):
            os.kill(int(pid_file.read_text()), 0)

        # Bound the entire read-only HTTP probe even when bytes keep arriving.
        fixture = self.root / "trickled.py"
        fixture.write_text("import socket,time\ns=socket.socket();s.bind(('127.0.0.1',0));s.listen()\n"
                           "print(s.getsockname()[1],flush=True)\nc,_=s.accept();c.recv(65536)\n"
                           "c.sendall(b'HTTP/1.1 200 OK\\r\\nContent-Length: 999999\\r\\n\\r\\n{')\n"
                           "while True:\n time.sleep(.1)\n c.sendall(b' ')\n")
        process = subprocess.Popen([sys.executable, "-B", str(fixture)], stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, text=True, env=self.env)
        try:
            port = int(process.stdout.readline())
            code = ("import sys,json;sys.path.insert(0," + repr(str(self.checkout / "status-card"))
                    + ");import maintainer;print(json.dumps(maintainer.current_card('test-change',"
                    + str(port) + ",'candidate')))" )
            start = time.monotonic()
            probe = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True,
                                   text=True, env=self.env, timeout=4)
            self.assertLess(time.monotonic() - start, 3.5)
            self.assertEqual(probe.returncode, 0, probe.stderr)
            self.assertIsNone(json.loads(probe.stdout))
        finally:
            process.terminate()
            process.wait(timeout=3)
            process.stdout.close()

    def test_native_stop_guard_uses_prepared_browser_footer(self):
        env = dict(self.env, CODEX_THREAD_ID="synthetic-controller")

        def hook(event, turn, reply=""):
            payload = {"hook_event_name": event, "cwd": str(self.checkout), "session_id": "synthetic-controller",
                       "turn_id": turn, "last_assistant_message": reply, "stop_hook_active": False}
            return json.loads(subprocess.check_output(
                [sys.executable, "-B", str(self.checkout / "status-card/maintainer.py"), "hook"],
                input=json.dumps(payload), cwd=self.checkout, env=env, text=True, timeout=15))

        self.assertEqual(hook("UserPromptSubmit", "initial"), {})
        forwarded = "http://127.0.0.1:31337/task/test-change/"
        prepared = self.api("prepare", "--execution", "remote", "--user-url", forwarded, env=env)
        exact = subprocess.check_output(
            [sys.executable, "-B", str(self.checkout / "status-card/maintainer.py"), "card",
             "--task", "test-change", "--title", "Synthetic native Stop fixture"],
            cwd=self.checkout, env=env, text=True, timeout=15).strip()
        self.assertEqual(exact, prepared["footer"])
        self.assertEqual(hook("Stop", "initial", "Update.\n\n" + exact), {})
        for invalid in ("Missing footer.", exact.replace("test-change", "wrong-task"),
                        "FlightCheck: [&lt; status /&gt;](" + prepared["host_url"] + ")"):
            self.assertEqual(hook("Stop", "initial", invalid)["decision"], "block")
        self.readme.write_text("Candidate changed before native Stop\n")
        self.assertEqual(hook("Stop", "initial", exact)["decision"], "block")
        self.assertEqual(self.api("prepare", "--execution", "remote", env=env)["footer"], exact)
        self.assertEqual(hook("Stop", "initial", exact), {})
        self.assertEqual(hook("UserPromptSubmit", "resume"), {})
        # Portable preparation alone must associate a compatible controller
        # session; no second maintainer invocation should be necessary.
        self.assertEqual(self.api("prepare", "--execution", "remote", env=env)["footer"], exact)
        self.assertEqual(hook("Stop", "resume", exact), {})
        self.assertEqual(hook("Stop", "resume", "Approval pause without footer.")["decision"], "block")
