"""Behavioural test for ga_cli.cli.cmd_update fail-fast behaviour.

When `git pull` fails (network down, merge conflict, dirty tree,
non-fast-forward, etc.), the old code printed the error to stdout and
then ran `pip install -e .` on top of stale or conflicted source. That
silently corrupted the editable install and made the next `ga` command
behave unpredictably.

The fix exits with the git return code when git pull fails, and routes
the error to stderr (where it belongs). This test verifies both:
  1. cmd_update exits non-zero when git pull fails (and does NOT call
     pip install).
  2. cmd_update still calls pip install and exits cleanly when both
     steps succeed.
  3. cmd_update propagates pip-install failure via SystemExit.
"""

from __future__ import annotations

import builtins
import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "ga_cli"))

import importlib.util
_spec = importlib.util.spec_from_file_location(
    "_ga_cli_for_test", os.path.join(REPO_ROOT, "ga_cli", "cli.py"),
)
ga_cli = importlib.util.module_from_spec(_spec)
sys.modules["_ga_cli_for_test"] = ga_cli
_spec.loader.exec_module(ga_cli)  # type: ignore[union-attr]


class _FakeResult:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_cmd_update_exits_when_git_pull_fails(monkeypatch):
    """git pull fails -> cmd_update exits with that code, pip never runs."""
    calls = []

    def fake_run(argv, *a, **kw):
        calls.append(list(argv))
        if argv[:2] == ["git", "pull"]:
            return _FakeResult(128, stdout="", stderr="fatal: not a git repository\n")
        # pip install — should not be reached
        raise AssertionError(f"pip install must not run after failed git pull (called: {argv!r})")

    monkeypatch.setattr(ga_cli.subprocess, "run", fake_run)
    # Don't actually chdir into the project root — avoid touching the real one.
    monkeypatch.setattr(ga_cli.os, "chdir", lambda *_a, **_kw: None)
    # Suppress print noise. Patching the `print` builtin in the
    # importing module is a no-op because `print` resolves via the
    # builtins namespace. Use `builtins.setattr` so the cli module
    # sees the patched value.
    monkeypatch.setattr(builtins, "print", lambda *_a, **_kw: None)

    with pytest.raises(SystemExit) as exc_info:
        ga_cli.cmd_update()
    assert exc_info.value.code == 128, f"expected exit 128 (git pull rc), got {exc_info.value.code!r}"
    # Only git pull was invoked, then exit.
    assert calls == [["git", "pull"]], f"unexpected calls: {calls!r}"


def test_cmd_update_propagates_pip_install_failure(monkeypatch):
    """git pull ok + pip install fails -> cmd_update exits with pip's code."""
    calls = []

    def fake_run(argv, *a, **kw):
        calls.append(list(argv))
        if argv[:2] == ["git", "pull"]:
            return _FakeResult(0, stdout="Already up to date.\n", stderr="")
        return _FakeResult(1, stdout="", stderr="ERROR: Could not find a version\n")

    monkeypatch.setattr(ga_cli.subprocess, "run", fake_run)
    monkeypatch.setattr(ga_cli.os, "chdir", lambda *_a, **_kw: None)
    monkeypatch.setattr(builtins, "print", lambda *_a, **_kw: None)

    with pytest.raises(SystemExit) as exc_info:
        ga_cli.cmd_update()
    assert exc_info.value.code == 1, f"expected exit 1 (pip install rc), got {exc_info.value.code!r}"
    # Both steps were called in order.
    assert [c[:2] for c in calls] == [
        ["git", "pull"],
        [sys.executable, "-m"],
    ], f"unexpected call order: {calls!r}"


def test_cmd_update_succeeds_when_both_steps_ok(monkeypatch):
    """git pull + pip install both ok -> cmd_update returns normally with rc=0."""
    calls = []

    def fake_run(argv, *a, **kw):
        calls.append(list(argv))
        if argv[:2] == ["git", "pull"]:
            return _FakeResult(0, stdout="Already up to date.\n", stderr="")
        return _FakeResult(0, stdout="Successfully installed ga\n", stderr="")

    monkeypatch.setattr(ga_cli.subprocess, "run", fake_run)
    monkeypatch.setattr(ga_cli.os, "chdir", lambda *_a, **_kw: None)
    monkeypatch.setattr(builtins, "print", lambda *_a, **_kw: None)

    # cmd_update returns implicitly (no return statement) on success.
    rc = ga_cli.cmd_update()
    assert rc is None, f"on success cmd_update should return None, got {rc!r}"
    assert [c[:2] for c in calls] == [
        ["git", "pull"],
        [sys.executable, "-m"],
    ], f"unexpected call order: {calls!r}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
