"""Behavioural test for tuiapp_v2._drain_ask_user_events empty-candidates guard.

Issue #615: when ask_user is called with candidates=[], _drain_ask_user_events
used to mount an empty ChoiceList (only "Type something") and steal keyboard
focus from the text input. Mirrors the v3 fix in dfab299. We verify:

  1. With candidates=[], the drain does NOT append any ChatMessage.
  2. With candidates=['A', 'B'], the drain still appends exactly one
     ChatMessage (regression test — the fix must not break the happy path).
  3. The empty-candidate event is still consumed from the queue (so a
     stale event doesn't trigger the empty-picker bug on a later drain).
"""

from __future__ import annotations

import os
import sys
from queue import Queue

# frontends/ has no __init__.py — add it to sys.path so sibling modules
# (keysym, at_complete, slash_cmds, …) import cleanly.
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "frontends"))
sys.path.insert(0, REPO_ROOT)

import importlib.util
_spec = importlib.util.spec_from_file_location(
    "_tuiapp_v2_for_test",
    os.path.join(REPO_ROOT, "frontends", "tuiapp_v2.py"),
)
t2 = importlib.util.module_from_spec(_spec)
sys.modules["_tuiapp_v2_for_test"] = t2  # dataclass introspects sys.modules
_spec.loader.exec_module(t2)  # type: ignore[union-attr]


class _StubSess:
    """Minimal stand-in for AgentSession — only the attributes the drain touches."""

    def __init__(self, payload):
        self.ask_user_events: Queue = Queue()
        self.messages: list = []
        self.agent_id = 1
        self.agent = None
        if payload is not None:
            self.ask_user_events.put(payload)


class _StubApp:
    """Just enough surface for _drain_ask_user_events — it never calls .query_one."""

    current_id = 1

    def _refresh_messages(self):
        # If called with an empty pick, this is the symptom of the bug.
        raise AssertionError("_refresh_messages must not run for empty candidates")


def _make_app_with_sess(sess):
    """Build an instance whose _drain_ask_user_events we can call directly."""
    app = t2.GenericAgentTUI.__new__(t2.GenericAgentTUI)
    app.sessions = {sess.agent_id: sess}
    app.current_id = sess.agent_id
    # Provide the regex the method uses to detect multi-select phrasing.
    app._MULTI_RE = t2.GenericAgentTUI._MULTI_RE
    # No-op the side-effect that needs a real Textual screen mounted.
    app._refresh_messages = lambda: None
    return app


def test_empty_candidates_no_message_appended():
    sess = _StubSess({"question": "Pick one", "candidates": []})
    app = _make_app_with_sess(sess)
    t2.GenericAgentTUI._drain_ask_user_events(app, sess)
    assert sess.messages == [], f"expected no picker, got {sess.messages!r}"
    # The stale event must still have been consumed (queue empty).
    assert sess.ask_user_events.qsize() == 0, "drain must still consume empty events"


def test_non_empty_candidates_still_appends_picker():
    sess = _StubSess({"question": "Pick one", "candidates": ["A", "B"]})
    app = _make_app_with_sess(sess)
    t2.GenericAgentTUI._drain_ask_user_events(app, sess)
    assert len(sess.messages) == 1, f"expected 1 picker, got {len(sess.messages)}"
    msg = sess.messages[0]
    # Free-text escape hatch should still be appended.
    labels = [label for label, _ in msg.choices]
    assert "Type something" in labels
    assert "A" in labels and "B" in labels


def test_multi_select_marker_with_empty_candidates_still_skipped():
    sess = _StubSess({"question": "[多选] tag a few", "candidates": []})
    app = _make_app_with_sess(sess)
    t2.GenericAgentTUI._drain_ask_user_events(app, sess)
    assert sess.messages == [], "multi-select phrasing must not bypass empty guard"


if __name__ == "__main__":
    test_empty_candidates_no_message_appended()
    print("✓ empty candidates → no picker mounted")
    test_non_empty_candidates_still_appends_picker()
    print("✓ non-empty candidates → picker still mounted")
    test_multi_select_marker_with_empty_candidates_still_skipped()
    print("✓ multi-select phrasing does not bypass empty-candidates guard")
    print("all checks passed")