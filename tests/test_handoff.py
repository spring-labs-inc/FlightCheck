"""Upstream entry point for the vendored runtime-contract tests."""

from pathlib import Path
import runpy

_runtime = Path(__file__).resolve().parents[1] / "examples/existing-project/tests/test_handoff.py"
globals().update({key: value for key, value in runpy.run_path(str(_runtime), run_name=__name__).items()
                  if not key.startswith("__")})
