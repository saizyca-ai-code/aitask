"""Unit tests for aitask parser functions (dev8 Phase 3b-v / #147).

Covers pure functions in the `aitask` package's parse module:
- extract_phases — heading + bullet matchers
- task_mentions_phase — word-boundary match safety
- _doc_has_milestone_flag — synthetic + list shape
- derive_task_timespan — min/max of committed_at
- aggregate_phase_summary — end-to-end aggregation

Moved into the aitask package's own repo (task #1 — 斷開 consumer 代管;
previously lived in MSSceneDetect's tests/). Imports the package directly;
pyproject's [tool.pytest.ini_options] `pythonpath = ["src"]` makes these run
with or without an editable install.

Run:
    pytest                                  # from repo root
    pytest tests/test_aitask_parse.py -v
"""
from __future__ import annotations

from aitask import parse


# ── extract_phases ──────────────────────────────────────────────────────────

def test_extract_phases_from_headings():
    body = """
## Plan: dev8

### Phase A — backend
Some text.

### Phase B — frontend
More text.

### Phase C — polish
"""
    assert parse.extract_phases(body) == ["A", "B", "C"]


def test_extract_phases_from_bullets():
    body = """
## Approach

- Phase 1 setup
- Phase 2 implementation
- Phase 3 testing
"""
    assert parse.extract_phases(body) == ["1", "2", "3"]


def test_extract_phases_headings_over_bullets():
    """Headings come first (canonical), bullets reinforce."""
    body = """
### Phase A
- Phase B done first
"""
    out = parse.extract_phases(body)
    assert out == ["A", "B"]


def test_extract_phases_dedup_case_insensitive():
    body = """
### Phase A
- Phase a alt mention
### Phase B
"""
    assert parse.extract_phases(body) == ["A", "B"]


def test_extract_phases_complex_labels():
    body = """
### Phase 3b-i — relations
### Phase 3b-ii — milestone
### Phase 0a — bootstrap
"""
    assert parse.extract_phases(body) == ["3b-i", "3b-ii", "0a"]


def test_extract_phases_empty_body():
    assert parse.extract_phases("") == []
    assert parse.extract_phases(None) == []


def test_extract_phases_no_match():
    """Body without any Phase X headings/bullets."""
    body = """
## Goal
- regular bullet
- another bullet
"""
    assert parse.extract_phases(body) == []


# ── task_mentions_phase ─────────────────────────────────────────────────────

def test_task_mentions_phase_word_boundary():
    """Phase 1 must not match Phase 12 (word boundary)."""
    assert parse.task_mentions_phase("Phase 12 work", "", "1") is False
    assert parse.task_mentions_phase("Phase 1 work", "", "1") is True


def test_task_mentions_phase_in_body():
    """First 500 chars of body are scanned, title too."""
    assert parse.task_mentions_phase("", "Phase A is great", "A") is True


def test_task_mentions_phase_case_insensitive():
    assert parse.task_mentions_phase("phase a", "", "A") is True
    assert parse.task_mentions_phase("PHASE A", "", "A") is True


def test_task_mentions_phase_handles_dash_label():
    """Phase 3b-i with hyphen is handled (regex.escape)."""
    assert parse.task_mentions_phase("doing Phase 3b-i", "", "3b-i") is True


def test_task_mentions_phase_empty_label():
    assert parse.task_mentions_phase("any text", "Phase A", "") is False


# ── _doc_has_milestone_flag ────────────────────────────────────────────────

def test_milestone_flag_synthetic():
    """Pre-annotated _milestone_flag wins (cmd_graph pattern)."""
    assert parse._doc_has_milestone_flag({"_milestone_flag": True}) is True
    assert parse._doc_has_milestone_flag({"_milestone_flag": False}) is False


def test_milestone_flag_list_shape():
    """Direct API consumer shape — list of {field_name, value}."""
    doc = {"field_values": [
        {"field_name": "是否里程碑", "value": "true"},
        {"field_name": "其他", "value": "abc"},
    ]}
    assert parse._doc_has_milestone_flag(doc) is True


def test_milestone_flag_list_shape_falsy():
    doc = {"field_values": [
        {"field_name": "是否里程碑", "value": ""},
        {"field_name": "是否里程碑", "value": False},
    ]}
    assert parse._doc_has_milestone_flag(doc) is False


def test_milestone_flag_missing():
    assert parse._doc_has_milestone_flag({}) is False
    assert parse._doc_has_milestone_flag({"field_values": None}) is False


def test_milestone_flag_dict_shape_not_handled():
    """Dict shape (field_id keyed) needs caller pre-annotation — verify
    we don't accidentally accept it (would be false positive without
    field id mapping)."""
    doc = {"field_values": {"20": "true"}}
    # Without _milestone_flag annotation, dict shape should NOT trigger
    assert parse._doc_has_milestone_flag(doc) is False


# ── derive_task_timespan ───────────────────────────────────────────────────

def test_derive_task_timespan_basic():
    commits = [
        {"task_id": 1, "commit_hash": "a", "committed_at": "2026-05-20T10:00:00"},
        {"task_id": 1, "commit_hash": "b", "committed_at": "2026-05-22T15:00:00"},
        {"task_id": 2, "commit_hash": "c", "committed_at": "2026-05-21T09:00:00"},
    ]
    first, last = parse.derive_task_timespan(1, commits)
    assert first == "2026-05-20T10:00:00"
    assert last == "2026-05-22T15:00:00"


def test_derive_task_timespan_no_commits():
    first, last = parse.derive_task_timespan(99, [])
    assert first is None and last is None


def test_derive_task_timespan_single_commit():
    commits = [
        {"task_id": 5, "commit_hash": "x", "committed_at": "2026-05-25T12:00:00"},
    ]
    first, last = parse.derive_task_timespan(5, commits)
    assert first == "2026-05-25T12:00:00"
    assert last == "2026-05-25T12:00:00"


def test_derive_task_timespan_other_task_ignored():
    """Verify task_id filter works."""
    commits = [
        {"task_id": 1, "commit_hash": "a", "committed_at": "2026-05-20"},
        {"task_id": 99, "commit_hash": "b", "committed_at": "2026-05-25"},
    ]
    first, last = parse.derive_task_timespan(1, commits)
    assert first == "2026-05-20"
    assert last == "2026-05-20"


# ── aggregate_phase_summary ────────────────────────────────────────────────

def test_aggregate_phase_summary_full():
    tasks = [
        {"id": 1, "title": "Phase A backend", "description": "", "status": "done"},
        {"id": 2, "title": "Phase A frontend", "description": "", "status": "done"},
        {"id": 3, "title": "Phase B start", "description": "", "status": "in_progress"},
    ]
    commits = [
        {"task_id": 1, "committed_at": "2026-05-10"},
        {"task_id": 1, "committed_at": "2026-05-12"},
        {"task_id": 2, "committed_at": "2026-05-14"},
    ]
    summary = parse.aggregate_phase_summary("A", tasks, commits)
    assert summary.label == "A"
    assert sorted(summary.task_ids) == [1, 2]
    assert summary.status_counts == {"done": 2}
    assert summary.first_commit_at == "2026-05-10"
    assert summary.last_commit_at == "2026-05-14"
    assert summary.commit_count == 3


def test_aggregate_phase_summary_no_matches():
    tasks = [{"id": 1, "title": "unrelated", "description": "", "status": "done"}]
    summary = parse.aggregate_phase_summary("A", tasks, [])
    assert summary.task_ids == []
    assert summary.commit_count == 0
    assert summary.first_commit_at is None


def test_aggregate_phase_summary_no_commits():
    """Task matches phase but has no commits — still counted with no timespan."""
    tasks = [{"id": 1, "title": "Phase A work", "description": "",
              "status": "pending"}]
    summary = parse.aggregate_phase_summary("A", tasks, [])
    assert summary.task_ids == [1]
    assert summary.status_counts == {"pending": 1}
    assert summary.first_commit_at is None
    assert summary.commit_count == 0
