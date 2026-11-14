"""Native unittest evidence with separate product and test-overlay fingerprints."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest

BASE = Path(__file__).resolve().parent
PRODUCT = Path(os.environ.get("EXAMPLE_PRODUCT_ROOT", str(BASE))).resolve()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def specification():
    return {name: sha(BASE / name) for name in ("test_contract.py", "run_gate.py")}


if sys.argv[1:] == ["fingerprint"]:
    print(json.dumps({"product_root": str(PRODUCT), "product_sha256": sha(PRODUCT / "product.py"),
                      "test_overlay": specification(), "python": sys.version}, sort_keys=True))
    raise SystemExit(0)
if sys.argv[1:] != ["run"]:
    raise SystemExit("Use run or fingerprint")

spec = importlib.util.spec_from_file_location("product", PRODUCT / "product.py")
module = importlib.util.module_from_spec(spec)
sys.modules["product"] = module
spec.loader.exec_module(module)


class NativeResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.outcomes = {name: [] for name in ("passed", "skipped", "expected_failures", "failed")}

    def addSuccess(self, test):
        super().addSuccess(test)
        self.outcomes["passed"].append(test.id())

    def addFailure(self, test, error):
        super().addFailure(test, error)
        self.outcomes["failed"].append(test.id())

    def addError(self, test, error):
        super().addError(test, error)
        self.outcomes["failed"].append(test.id())

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.outcomes["skipped"].append(test.id())

    def addExpectedFailure(self, test, error):
        super().addExpectedFailure(test, error)
        self.outcomes["expected_failures"].append(test.id())

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self.outcomes["failed"].append(test.id())


suite = unittest.defaultTestLoader.discover(str(BASE), pattern="test_contract.py")
result = unittest.TextTestRunner(verbosity=2, resultclass=NativeResult).run(suite)
out = Path(os.environ["FLIGHTCHECK_REPORT_DIR"])
(out / "coverage.json").write_text(json.dumps(result.outcomes) + "\n")
(out / "spec.json").write_text(json.dumps(specification(), sort_keys=True) + "\n")
raise SystemExit(0 if result.wasSuccessful() else 1)
