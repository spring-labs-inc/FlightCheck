"""Disposable native Git fixtures for lifecycle and read-only audit witnesses.

No fixture touches the contributor checkout's refs, Registry or worktrees. The
transport shim redirects only fixture network commands to a real bare remote;
Git still performs its actual compare-and-swap and removal operations.
"""
import contextlib
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from unittest.mock import patch

from checkout_guard_cases import CheckoutCases, PRODUCT


class LifecycleCases(CheckoutCases):
    def feature(self, name):
        path = PRODUCT / "workflow/scripts" / (name + ".py")
        self.assertTrue(path.is_file(), "Required lifecycle/audit behavior is absent: " + name)
        return self.module(name)

    def run_git(self, root, *args, expected=0, env=None):
        result = subprocess.run(["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(root), *args],
                                env=env or self.env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result.stdout.strip()

    def object_exists(self, oid):
        return subprocess.run(["git", "-C", str(self.root), "cat-file", "-e", oid + "^{commit}"],
                              env=self.env, capture_output=True).returncode == 0

    def transport(self):
        self.remote = self.area / "actual-remote.git"
        self.real_git = shutil.which("git", path=self.env["PATH"])
        subprocess.run([self.real_git, "clone", "--bare", "--quiet", str(self.root), str(self.remote)],
                       env=self.env, check=True, capture_output=True)
        self.git_calls = self.area / "git-calls.jsonl"
        shim = self.area / "tools/git"
        shim.write_text("#!" + sys.executable + "\n" +
            "import json,os,subprocess,sys\nfrom pathlib import Path\n" +
            "a=sys.argv[1:]\n" +
            "with Path(" + repr(str(self.git_calls)) + ").open('a') as f:f.write(json.dumps({'args':a,'readonly':bool(os.environ.get('FC_AUDIT_READONLY'))})+'\\n')\n" +
            "i=0\nwhile i<len(a):\n" +
            " if a[i] in ('-C','-c','--git-dir','--work-tree'):i+=2;continue\n" +
            " if a[i].startswith('-'):i+=1;continue\n" +
            " break\n" +
            "op=a[i] if i<len(a) else ''\nrest=a[i+1:]\n" +
            "if op=='ls-remote' and os.environ.get('FC_REMOTE_UNAVAILABLE'):\n" +
            " print('Fixture remote observation unavailable',file=sys.stderr);sys.exit(75)\n" +
            "if os.environ.get('FC_AUDIT_READONLY'):\n" +
            " allowed={'rev-parse','for-each-ref','rev-list','diff','log','show','show-ref','merge-base','cat-file','ls-tree','ls-remote'}\n" +
            " allowed_op=op in allowed\n" +
            " if op=='worktree':allowed_op=bool(rest) and rest[0]=='list'\n" +
            " if op=='remote':allowed_op=bool(rest) and rest[0] in ('-v','--verbose','get-url')\n" +
            " if op=='config':allowed_op=any(x in rest for x in ('--get','--get-all','--get-regexp','--list','--get-urlmatch'))\n" +
            " if op=='symbolic-ref':allowed_op=len([x for x in rest if not x.startswith('-')])==1\n" +
            " if op=='status':allowed_op=True\n" +
            " if not allowed_op or any(x=='--output' or x.startswith('--output=') for x in rest):\n" +
            "  print('AUDIT_MUTATION_DENIED:'+op,file=sys.stderr);sys.exit(91)\n" +
            "if op in ('ls-remote','push'):\n" +
            " a=[" + repr(str(self.remote)) + " if x in ('origin','https://github.com/fixture/repo.git') else x for x in a]\n" +
            "raise SystemExit(subprocess.call([" + repr(self.real_git) + ",*a]))\n")
        shim.chmod(0o700)
        self.git(self.root, "remote", "set-url", "origin", "https://github.com/fixture/repo.git")

    def prepare_base(self):
        (self.root / "tool.sh").write_text("#!/bin/sh\nprintf 'old\\n'\n")
        (self.root / "tool.sh").chmod(0o644)
        (self.root / "obsolete.txt").write_text("source deletion must survive\n")
        (self.root / ".gitignore").write_text(".flightcheck/\nignored-private/\n.env\n")
        self.git(self.root, "add", ".")
        self.git(self.root, "commit", "-qm", "Lifecycle fixture base")
        self.base = self.git(self.root, "rev-parse", "HEAD")
        self.git(self.root, "update-ref", "refs/remotes/origin/trunk", self.base)

    def inventory(self, *, kinds=("worktree", "local_branch", "remote_branch")):
        rows = [{"kind": "worktree", "identity": str(self.source),
                 "owned_ignored_prefixes": [".flightcheck/project.json"]},
                {"kind": "local_branch", "identity": "refs/heads/" + self.topic},
                {"kind": "remote_branch", "identity": "refs/heads/" + self.topic, "remote": "origin"}]
        return [row for row in rows if row["kind"] in kinds]

    def preservation(self, *, extra=()):
        files = []
        copies = self.area / "preserved-assets"
        copies.mkdir(mode=0o700, exist_ok=True)
        for i, name in enumerate([".flightcheck/project.json", *extra]):
            source = self.source / name
            target = copies / ("copy-" + str(i))
            shutil.copyfile(source, target)
            mode = stat.S_IMODE(source.stat().st_mode)
            target.chmod(mode)
            files.append({"path": name, "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                          "mode": mode, "copy": str(target)})
        producer = copies / "producer.json"
        value = {"schema": 1, "kind": "generated-private-assets", "flight": "fixture",
                 "checkout": str(self.source), "reference": "Fixture-controlled configuration creation",
                 "source": "CheckoutCases.configure writes the exact known private configuration",
                 "files": [{k: row[k] for k in ("path", "sha256", "mode")} for row in files]}
        producer.write_text(json.dumps(value, sort_keys=True) + "\n")
        producer.chmod(0o600)
        return {"flight": "fixture", "checkout": str(self.source),
                "producer": {"reference": str(producer), "sha256": hashlib.sha256(producer.read_bytes()).hexdigest()},
                "files": files}

    @contextlib.contextmanager
    def world(self, mode="merge", *, grant=True, integrated=True, kinds=("worktree", "local_branch", "remote_branch")):
        with self.fixture():
            self.life = self.feature("flight_lifecycle")
            self.prepare_base()
            self.transport()
            self.topic = "flight81-topic"
            self.source = self.worktree(self.area / "flight81", self.topic)
            self.owner_reference = "Owner grants only the exact disposable fixture inventory"
            inventory = self.inventory(kinds=kinds)
            record = self.record(self.source)
            record["issues"], record["pull_requests"] = [81], [181]
            record["checkout"]["kind"] = "disposable-temporary"
            record["grants"]["cleanup"] = ([{"authority": "owner", "reference": self.owner_reference,
                                               "inventory": copy.deepcopy(inventory)}] if grant else [])
            self.adopt(self.source, record)
            if grant:
                self.life.register_cleanup(self.root, self.registry, "fixture", inventory=inventory,
                                           reference=self.owner_reference)
            self.saved_assets = self.preservation()
            self.client_state = {"client": "codex", "available": True, "safely_left": True}
            (self.source / "tool.sh").write_text("#!/bin/sh\nprintf 'new source bytes\\n'\n")
            (self.source / "tool.sh").chmod(0o755)
            (self.source / "feature-one.txt").write_text("first source change\n")
            self.git(self.source, "add", ".")
            self.git(self.source, "commit", "-qm", "Source bytes and executable mode")
            first = self.git(self.source, "rev-parse", "HEAD")
            (self.source / "obsolete.txt").unlink()
            (self.source / "feature-two.txt").write_text("second source change\n")
            self.git(self.source, "add", "-A")
            self.git(self.source, "commit", "-qm", "Source deletion and second change")
            self.head = self.git(self.source, "rev-parse", "HEAD")
            self.git(self.source, "push", "--quiet", "origin", "HEAD:refs/heads/" + self.topic)
            self.git(self.root, "update-ref", "refs/remotes/origin/" + self.topic, self.head)
            (self.root / "target-only.txt").write_text("independent target work\n")
            self.git(self.root, "add", ".")
            self.git(self.root, "commit", "-qm", "Independent target change")
            if integrated:
                if mode == "merge":
                    self.git(self.root, "merge", "--no-ff", "--no-edit", self.topic)
                elif mode == "squash":
                    self.git(self.root, "merge", "--squash", self.topic)
                    self.git(self.root, "commit", "-qm", "Actual squash integration")
                elif mode == "rebase":
                    self.git(self.root, "cherry-pick", first, self.head)
                else:
                    self.fail("Unknown fixture integration mode")
            self.merge = self.git(self.root, "rev-parse", "HEAD")
            self.git(self.root, "push", "--quiet", "origin", "refs/heads/trunk:refs/heads/trunk")
            self.git(self.root, "update-ref", "refs/remotes/origin/trunk", self.merge)
            self.delivery = {"repository": "fixture/repo", "merged": integrated, "source_base": self.base,
                             "head": self.head, "merge_commit": self.merge, "target": "trunk",
                             "method": mode, "pull_request": 181}
            yield

    def plan(self, **kwargs):
        return self.life.plan(self.root, self.registry, "fixture", delivery=self.delivery, policy=self.policy,
                              client_state=self.client_state, preservation=self.saved_assets, **kwargs)

    def apply(self, plan, **kwargs):
        return self.life.apply(self.root, self.registry, "fixture", plan, delivery=self.delivery,
                               policy=self.policy, client_state=self.client_state,
                               preservation=self.saved_assets, **kwargs)

    def row(self, report, kind):
        rows = [row for row in report["artifacts"] if row["kind"] == kind]
        self.assertEqual(len(rows), 1, report)
        return rows[0]

    def blocked(self, report):
        self.assertIs(report["complete"], False, report)
        self.assertTrue(report["blockers"] or any(row.get("blockers") for row in report["artifacts"]), report)

    def snapshot(self, paths=None):
        paths = paths or [self.root, self.source, self.remote, self.registry.directory]
        result = {}
        for root in paths:
            root = Path(root)
            if not root.exists():
                result[str(root)] = None
                continue
            for p in [root, *root.rglob("*")]:
                info = p.lstat()
                if p.is_symlink():
                    content = ("link", os.readlink(p))
                elif p.is_file():
                    content = hashlib.sha256(p.read_bytes()).hexdigest()
                else:
                    content = "directory"
                result[str(p)] = (stat.S_IMODE(info.st_mode), info.st_size if p.is_file() else None,
                                  info.st_mtime_ns, content)
        return result

    def remote_tip(self, ref=None):
        ref = ref or "refs/heads/" + self.topic
        z = subprocess.run([self.real_git, "--git-dir", str(self.remote), "rev-parse", "--verify", ref],
                           env=self.env, capture_output=True, text=True)
        return z.stdout.strip() if z.returncode == 0 else None

    def remove_native(self, request):
        self.assertEqual(request["client"], "codex")
        self.assertEqual(Path(request["path"]), self.source)
        self.git(self.root, "worktree", "remove", str(self.source))
        return {"client": "codex", "path": str(self.source), "operation_id": request["operation_id"], "success": True}

    def artifact_state(self, report, kind):
        return self.row(report, kind)["state"]

    def advance_remote(self):
        actor = self.area / "remote-actor"
        subprocess.run([self.real_git, "clone", "--quiet", str(self.remote), str(actor)],
                       env=self.env, capture_output=True, check=True)
        self.git(actor, "config", "user.name", "Fixture other actor")
        self.git(actor, "config", "user.email", "fixture@example.invalid")
        self.git(actor, "config", "core.hooksPath", os.devnull)
        self.git(actor, "config", "commit.gpgsign", "false")
        self.git(actor, "switch", "-q", "-c", self.topic, "origin/" + self.topic)
        value = self.commit(actor, "new-remote-work.txt")
        self.git(actor, "push", "--quiet", "origin", "HEAD:refs/heads/" + self.topic)
        self.assertFalse(self.object_exists(value), "Fixture remote advancement must require unavailable local objects")
        return value

    def audit(self, **kwargs):
        module = self.feature("repository_audit")
        observations = {str(self.source): {"available": True, "active": False,
                                           "source": "Fixture client observation",
                                           "observed_at": datetime.now(timezone.utc).isoformat()}}
        return module.audit(self.root, self.registry, "fixture/repo", policy=self.policy,
                            client_observations=observations, **kwargs)

    def audit_routes(self, registry=None, *, private_file=None):
        driver = self.area / "audit-entry.py"
        driver.write_text('''import builtins,contextlib,io,os,runpy,sys
from pathlib import Path
product=Path(sys.argv[1]);route=sys.argv[2];secret=Path(sys.argv[3]).resolve() if sys.argv[3] else None
arguments=sys.argv[4:]
def deny_private(original):
 def wrapped(file,*args,**kwargs):
  if secret is not None and not isinstance(file,int):
   try:
    if Path(file).resolve()==secret:raise AssertionError("Audit attempted private content access")
   except TypeError:pass
  return original(file,*args,**kwargs)
 return wrapped
builtins.open=deny_private(builtins.open);io.open=deny_private(io.open);os.open=deny_private(os.open)
sys.path.insert(0,str(product/'workflow/scripts'))
if route=='module':
 import repository_audit
 raise SystemExit(repository_audit.main(arguments))
if route=='source':
 sys.argv=[str(product/'setup/install.py'),'audit',*arguments]
 runpy.run_path(sys.argv[0],run_name='__main__')
else:
 sys.path.insert(0,str(product/'src'))
 from flightcheck_cli import cli
 @contextlib.contextmanager
 def source_installer():
  yield cli.load_installer(product/'setup/install.py'),None,None,None
 cli.installer=source_installer
 raise SystemExit(cli.main(['audit',*arguments]))
''')
        arguments = ["--checkout", str(self.root), "--registry", str(registry or self.registry.directory),
                     "--repository", "fixture/repo"]
        environment = dict(self.env, FC_AUDIT_READONLY="1")
        for route in ("module", "source", "packaged"):
            result = subprocess.run([sys.executable, "-B", str(driver), str(PRODUCT), route,
                                     str(private_file) if private_file else "", *arguments],
                                    cwd=self.root, env=environment, capture_output=True, text=True, timeout=40)
            self.assertEqual(result.returncode, 0, route + ": " + result.stdout + result.stderr)
            value = json.loads(result.stdout)
            self.assertIs(value["read_only"], True)
            self.assertIs(value["cleanup_authorized"], False)
            yield route, value
