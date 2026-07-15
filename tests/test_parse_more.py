"""Extra coverage for aitask.parse pure functions not exercised by
test_aitask_parse.py (task #1 — expand suite beyond the moved phase tests).

Targets the parsers the CLI actually leans on for `get` / `grep` / `refs` /
digest output: log/handoff/ref/info-tag extraction + build_digest.
"""
from __future__ import annotations

from aitask import parse


# ── extract_logs / last_log_date ────────────────────────────────────────────

_DESC_WITH_LOGS = (
    "body intro\n\n"
    "---\n[2026-07-10] first note\n\n"
    "---\n[2026-07-11] second note"
)


def test_extract_logs_orders_entries():
    logs = parse.extract_logs(_DESC_WITH_LOGS)
    assert [(l.date, l.body) for l in logs] == [
        ("2026-07-10", "first note"),
        ("2026-07-11", "second note"),
    ]


def test_extract_logs_empty():
    assert parse.extract_logs("") == []
    assert parse.extract_logs(None) == []


def test_last_log_date():
    assert parse.last_log_date(_DESC_WITH_LOGS) == "2026-07-11"
    assert parse.last_log_date("") is None


# ── extract_handoff ─────────────────────────────────────────────────────────

def test_extract_handoff_last_wins():
    desc = (
        "body\n\n**下次接手：** do step one\n\n"
        "---\n[2026-07-11] **下次接手：** do step two"
    )
    h = parse.extract_handoff(desc)
    assert h is not None
    assert h.kind == "下次接手"
    assert h.note == "do step two"


def test_extract_handoff_done_marker():
    h = parse.extract_handoff("**完成於：** commit abc1234")
    assert h is not None and h.kind == "完成於"


def test_extract_handoff_none():
    assert parse.extract_handoff("no markers here") is None
    assert parse.extract_handoff("") is None


# ── extract_refs ────────────────────────────────────────────────────────────

def test_extract_refs_multiple():
    desc = "**關聯任務：** #10 #11\n**關聯文件：** #20"
    refs = parse.extract_refs(desc)
    assert [(r.kind, r.ids) for r in refs] == [
        ("關聯任務", [10, 11]),
        ("關聯文件", [20]),
    ]


def test_extract_refs_empty():
    assert parse.extract_refs("") == []
    assert parse.extract_refs("no refs") == []


# ── extract_weak_refs ───────────────────────────────────────────────────────

def test_extract_weak_refs_prose_and_title():
    title = "[shots/feat] rework (#116/#117 follow-up)"
    desc = "承 #50 的後續，另 #99 補強"
    assert parse.extract_weak_refs(title, desc) == [50, 99, 116, 117]


def test_extract_weak_refs_empty():
    assert parse.extract_weak_refs("", "") == []


# ── trap markers ────────────────────────────────────────────────────────────

def test_trap_refs_and_marker():
    desc = "## 內容\n- 踩雷紀錄: 見 decision #42，別再犯\n\n---\n[2026-07-10] note"
    assert parse.extract_trap_refs(desc) == [42]
    assert parse.has_trap_marker(desc) is True


def test_trap_marker_absent():
    assert parse.has_trap_marker("no trap tag") is False
    assert parse.extract_trap_refs("- 踩雷紀錄: no ids here") == []


# ── extract_info_tags ───────────────────────────────────────────────────────

def test_extract_info_tags_repeat_keys_body_only():
    desc = (
        "## AI 標籤\n"
        "- 關鍵檔案: src/foo.py\n"
        "- 關鍵檔案: src/bar.py\n"
        "- 驗證指令: pytest -q\n"
        "\n## 內容\n\nbody\n\n"
        "---\n[2026-07-10] - 關鍵檔案: should_not_capture.py"
    )
    tags = parse.extract_info_tags(desc)
    assert tags == {
        "關鍵檔案": ["src/foo.py", "src/bar.py"],
        "驗證指令": ["pytest -q"],
    }


def test_extract_info_tags_empty():
    assert parse.extract_info_tags("") == {}


# ── extract_summary ─────────────────────────────────────────────────────────

def test_extract_summary_skips_meta_and_headings():
    desc = (
        "#42 [shots/feat] title\n\n"
        "複雜度: M\n預估工時: ~3h\n\n"
        "## 內容\n\n"
        "This is the real summary paragraph.\n\nSecond paragraph."
    )
    assert parse.extract_summary(desc) == "This is the real summary paragraph."


def test_extract_summary_truncates():
    out = parse.extract_summary("## 內容\n\n" + "x" * 300, max_chars=50)
    assert out.endswith("...")
    assert len(out) == 53  # 50 chars + "..."


# ── snippet_around ──────────────────────────────────────────────────────────

def test_snippet_around_ellipsis_both_sides():
    text = "0123456789ABCDEFGHIJ"
    assert parse.snippet_around(text, 10, 12, ctx=3) == "...789ABCDE..."


def test_snippet_around_collapses_newlines():
    assert parse.snippet_around("ab\ncd", 0, 5, ctx=0) == "ab cd"


def test_snippet_around_empty():
    assert parse.snippet_around("", 0, 0) == ""


# ── build_digest ────────────────────────────────────────────────────────────

def test_build_digest_task_sections():
    item = {
        "id": 42,
        "title": "#42 [shots/feat] build the widget",
        "status": "in_progress",
        "description": (
            "複雜度: M\n預估工時: ~3h （樂觀估計）\n\n"
            "## AI 標籤\n"
            "**關聯任務：** #10 #11\n"
            "- 關鍵檔案: src/widget.py\n\n"
            "## 內容\n\nBuild the widget end to end.\n\n"
            "---\n[2026-07-14] commit abc1234 scaffolded\n\n"
            "---\n[2026-07-15] **下次接手：** wire up the API"
        ),
    }
    d = parse.build_digest(item, kind="task")
    assert "#42" in d
    assert "[in_progress]" in d
    assert "build the widget" in d
    assert "M / ~3h" in d
    assert "關聯任務: #10 #11" in d
    assert "src/widget.py" in d
    assert "abc1234" in d
    assert "下次接手" in d and "wire up the API" in d
