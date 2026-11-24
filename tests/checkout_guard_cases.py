"""Disposable Git witnesses for checkout enforcement; no provider or owner state."""
import contextlib
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

PRODUCT = Path(os.environ.get("FLIGHTCHECK_PRODUCT_ROOT", Path(__file__).resolve().parents[1])).resolve()


class CheckoutCases:
    def module(self, name):
        path = PRODUCT / "workflow/scripts" / (name + ".py")
        spec = importlib.util.spec_from_file_location(name, path)
        value = importlib.util.module_from_spec(spec)
        previous = sys.modules.get(name)
        sys.modules[name] = value
        self.addCleanup(lambda: sys.modules.pop(name, None) if previous is None else sys.modules.__setitem__(name, previous))
        spec.loader.exec_module(value)
        return value

    def git(self, root, *args):
        result = subprocess.run(["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(root), *args],
                                env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout.strip()

    def repo(self, path):
        path.mkdir()
        self.git(path, "init", "-q", "--template=", "-b", "trunk")
        for key, value in (("user.name", "Checkout fixture"), ("user.email", "fixture@example.invalid"),
                           ("core.hooksPath", os.devnull), ("commit.gpgsign", "false")):
            self.git(path, "config", key, value)
        (path / "existing.txt").write_text("owner file\n")
        (path / ".gitignore").write_text(".flightcheck/\n")
        self.git(path, "add", ".")
        self.git(path, "commit", "-qm", "Fixture base")
        self.git(path, "update-ref", "refs/remotes/origin/trunk", "HEAD")
        self.git(path, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
        self.git(path, "remote", "add", "origin", "https://github.com/fixture/repo.git")
        return path

    def worktree(self, path, branch=None):
        args = ["worktree", "add", "-q"] + (["-b", branch] if branch else ["--detach"])
        self.git(self.root, *args, str(path), self.base)
        self.configure(path)
        return path

    def configure(self, path, **changes):
        supplied = {"python": sys.executable, "evidence_dir": str(self.area / "evidence"),
                    "nit_tracker": "private fixture", "policy_reference": "Owner fixture setup",
                    "default_branch": "trunk", "protected_branches": ["release"],
                    "checkout_policy": {"mode": "native-choice", "git_fallback": False},
                    "checks": [{"name": "fixture", "command": [sys.executable, "-B", "-c", "pass"], "phase": "cheap"}]}
        supplied.update(changes)
        value = self.config.normalize(path, supplied, {"default_branch": "trunk"}, origin="setup")
        target = path / self.config.CONFIG
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(self.config.encoded(value))
        target.chmod(0o600)
        return self.config.snapshot(path)

    @contextlib.contextmanager
    def fixture(self, guarded=True):
        with tempfile.TemporaryDirectory(prefix="checkout-guard-") as directory:
            self.area = Path(directory).resolve()
            self.env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                            GIT_TERMINAL_PROMPT="0", PYTHONDONTWRITEBYTECODE="1")
            for name in ("FLIGHTCHECK_CHECKOUT_REGISTRY", "FLIGHTCHECK_REGISTRY", "FLIGHTCHECK_FLIGHT",
                         "FLIGHTCHECK_CLIENT", "FLIGHTCHECK_SESSION", "CODEX_THREAD_ID", "CLAUDE_SESSION_ID"):
                self.env.pop(name, None)
            self.env["FLIGHTCHECK_STATE_DIR"] = str(self.area / "unbound-state")
            tools = self.area / "tools"
            tools.mkdir()
            self.provider_log = self.area / "provider-reads.jsonl"
            stub = tools / "gh"
            self.provider_control = self.area / "provider-control.json"
            self.provider_control.write_text(json.dumps({"classic_patterns": []}))
            stub.write_text("#!" + sys.executable + "\nimport json,sys\nfrom pathlib import Path\n"
                            "a=sys.argv[1:]\n"
                            "p=Path(" + repr(str(self.provider_log)) + ")\n"
                            "with p.open('a') as f:f.write(json.dumps(a)+'\\n')\n"
                            "c=json.loads(Path(" + repr(str(self.provider_control)) + ").read_text())\n"
                            "if 'graphql' in a:\n"
                            " assert '--method' in a and a[a.index('--method')+1]=='POST',a\n"
                            " assert 'owner=fixture' in a and 'name=repo' in a,a\n"
                            " q=next(x for x in a if x.startswith('query='))\n"
                            " assert q.startswith('query=query FlightCheckBranchProtection(') and 'mutation' not in q,q\n"
                            " if c.get('malformed'):v={'data':{'repository':None}}\n"
                            " else:v={'data':{'repository':{'nameWithOwner':'fixture/repo','branchProtectionRules':{'nodes':[{'pattern':x} for x in c['classic_patterns']],'pageInfo':{'hasNextPage':False,'endCursor':None}}}}}\n"
                            "else:\n"
                            " assert a[0]=='api' and a[a.index('--method')+1]=='GET' and a[a.index('--hostname')+1]=='github.com',a\n"
                            " assert a[a.index('--header')+1]=='Accept: application/vnd.github+json',a\n"
                            " e=a[1] if not a[1].startswith('--') else a[-1]\n"
                            " if e=='repos/fixture/repo':v={'full_name':'fixture/repo','default_branch':'trunk'}\n"
                            " elif e=='repos/fixture/repo/branches?per_page=100&page=1':v=[{'name':'trunk','protected':True},{'name':'release','protected':True}]\n"
                            " elif e=='repos/fixture/repo/rulesets?includes_parents=true&per_page=100&page=1':v=[]\n"
                            " else:raise SystemExit('Unexpected provider request: '+e)\n"
                            "print(json.dumps(v))\n")
            stub.chmod(0o700)
            self.env["PATH"] = str(tools) + os.pathsep + self.env.get("PATH", "")
            scripts = str(PRODUCT / "workflow/scripts")
            sys.path.insert(0, scripts)
            self.addCleanup(lambda: sys.path.remove(scripts))
            with patch.dict(os.environ, self.env, clear=True):
                self.associations = self.module("flight_associations")
                self.launch = self.module("launch_detection")
                self.config = self.module("project_config")
                self.guard = self.module("checkout_guard") if guarded else None
                self.root = self.repo(self.area / "repo")
                self.base = self.git(self.root, "rev-parse", "HEAD")
                self.configure(self.root)
                self.registry = self.associations.Registry(self.area / "registry")
                self.policy = {"repository": "fixture/repo", "default_branch": "trunk",
                               "protected_branches": ["trunk", "release"], "source": "injected provider fixture"}
                self.observation = {"client": "codex", "session": "session-1", "available": True,
                                    "selection": "native", "capabilities": {}}
                yield

    def record(self, path, flight="fixture", children=()):
        def checkout(item, kind="preserved-existing"):
            branch = subprocess.run(["git", "-C", str(item), "symbolic-ref", "--quiet", "--short", "HEAD"],
                                    env=self.env, capture_output=True, text=True)
            return {"path": str(item), "kind": kind, "management": "native",
                    "branch": branch.stdout.strip() if branch.returncode == 0 else None,
                    "commit": self.git(item, "rev-parse", "HEAD")}
        return {"schema": 1, "flight": flight, "task": "task-" + flight, "card": "card-" + flight,
                "repository": self.associations.repository_identity(self.root, "fixture/repo"),
                "issues": [82], "pull_requests": [182], "client": {"name": "codex", "sessions": ["session-1"]},
                "checkout": checkout(path), "children": [checkout(c, "disposable-temporary") for c in children],
                "configuration": self.config.snapshot(path), "grants": {"delivery": [], "cleanup": []},
                "lifecycle": {"state": "active", "disposition": "pending"}, "delivery": {"target": "trunk"}}

    def adopt(self, path, record=None, **kwargs):
        return self.guard.adopt(path, self.registry, record or self.record(path), base=kwargs.pop("base", self.base),
                                client_observation=kwargs.pop("client_observation", self.observation),
                                policy=kwargs.pop("policy", self.policy), **kwargs)

    def verify(self, path, flight="fixture", **kwargs):
        return self.guard.verify(path, self.registry, flight, policy=kwargs.pop("policy", self.policy), **kwargs)

    def commit(self, path, name="descendant.txt"):
        (path / name).write_text("flight descendant\n")
        self.git(path, "add", name)
        self.git(path, "commit", "-qm", "Legitimate flight descendant")
        return self.git(path, "rev-parse", "HEAD")

    def preserved_state(self, path):
        common = Path(self.associations.repository_identity(path, "fixture/repo")["git_common_dir"])
        return {"status": self.git(path, "status", "--porcelain=v1", "--untracked-files=all"),
                "index": (Path(self.git(path, "rev-parse", "--absolute-git-dir")) / "index").read_bytes(),
                "refs": self.git(path, "show-ref"),
                "files": {str(p.relative_to(path)): p.read_bytes() for p in path.rglob("*")
                          if p.is_file() and ".git" not in p.relative_to(path).parts}}

    def checkout_commands(self, path):
        args = ["verify", "--checkout", str(path), "--registry", str(self.registry.directory), "--flight", "fixture"]
        dispatch = self.area / "cli-dispatch.py"
        dispatch.write_text("import contextlib,sys\nfrom pathlib import Path\nsys.path.insert(0," + repr(str(PRODUCT / "src")) + ")\n"
                            "from flightcheck_cli import cli\n@contextlib.contextmanager\ndef fixture_source():\n"
                            " yield cli.load_installer(Path(" + repr(str(PRODUCT / "setup/install.py")) + ")),None,None,None\n"
                            "cli.installer=fixture_source\nraise SystemExit(cli.main(sys.argv[1:]))\n")
        return [[sys.executable, "-B", str(PRODUCT / "setup/install.py"), "checkout", *args],
                [sys.executable, "-B", str(dispatch), "checkout", *args]]

    def handoff_gate_status(self, path, receipt):
        gate = self.area / "gate-description.json"
        gate.write_text(json.dumps({"id": "native", "request": receipt["request"]}))
        driver = self.area / "handoff-gate.py"
        driver.write_text("import json,sys\nfrom pathlib import Path\nsys.path.insert(0," + repr(str(PRODUCT / "workflow/scripts")) + ")\n"
                          "import checkout_guard,handoff\n"
                          "context=checkout_guard.guard_context(Path.cwd(),{'checkout_binding':json.loads(sys.argv[3])},phase='review')\n"
                          "print(json.dumps(handoff.gate_status(Path(sys.argv[1]),json.loads(Path(sys.argv[2]).read_text()),'fixture-candidate',False,checkout_context=context)))\n")
        result = subprocess.run([sys.executable, "-B", str(driver), str(self.area / "capture-valid-ran"), str(gate),
                                 json.dumps({"registry": str(self.registry.directory), "flight": "fixture"})],
                                cwd=path, env=self.env, capture_output=True, text=True, timeout=25)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def copy_recorder(self):
        # The documented recorder is a standalone stdlib helper; copy no siblings.
        import shutil
        directory = self.area / "copied-recorder"
        directory.mkdir(exist_ok=True)
        helper = directory / "capture_check.py"
        shutil.copyfile(PRODUCT / "workflow/scripts/capture_check.py", helper)
        self.assertEqual([p.name for p in directory.iterdir()], ["capture_check.py"])
        return helper

    def handoff_checks(self, path, evidence, task, env=None):
        task_file = evidence / "automatic-task.json"
        task_file.write_text(json.dumps(task))
        return subprocess.run([sys.executable, "-B", str(PRODUCT / "workflow/scripts/handoff.py"), "checks",
                               "--task", str(task_file), "--evidence-dir", str(evidence)],
                              cwd=path, env=env or self.env, capture_output=True, text=True, timeout=25)

    def capture(self, path, sentinel, *options, expected=0, helper=None, env=None):
        evidence = self.area / ("capture-" + sentinel.name)
        command = [sys.executable, "-B", str(helper or PRODUCT / "workflow/scripts/capture_check.py"),
                   "--evidence-dir", str(evidence), "--create-evidence-dir", "--candidate", "fixture-candidate",
                   "--scope", "checkout sentinel", *map(str, options), "--", sys.executable, "-B", "-c",
                   "from pathlib import Path;Path(" + repr(str(sentinel)) + ").write_text('executed')"]
        environment = dict(env or self.env)
        if helper is not None:
            environment.pop("PYTHONPATH", None)
            environment["PYTHONNOUSERSITE"] = "1"
        result = subprocess.run(command, cwd=path, env=environment, text=True, capture_output=True, timeout=25)
        if expected == 0:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result, list(evidence.glob("check-*/run.json"))
