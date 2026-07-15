"""Unit tests for aitask.tags — dual-track tag assembly + category nudge
(task #1 — tags.py previously had zero coverage).

Round-trips build_task_description output back through parse.extract_* to
prove the writer and readers agree on the on-disk markdown shape.
"""
from __future__ import annotations

from aitask import parse, tags


# ── check_category (#198 soft nudge) ────────────────────────────────────────

def test_check_category_valid():
    assert tags.check_category("[shots/feat] title") is None


def test_check_category_valid_with_id_prefix():
    assert tags.check_category("#5 [shots/feat] title") is None


def test_check_category_type_alias_accepted():
    # fix→bug, ui→ux, doc→docs are aliased before the vocabulary check
    assert tags.check_category("[core/fix] x") is None
    assert tags.check_category("[core/ui] x") is None
    assert tags.check_category("[core/doc] x") is None


def test_check_category_missing_bracket():
    w = tags.check_category("no bracket here")
    assert w is not None and "缺漏" in w


def test_check_category_area_only():
    w = tags.check_category("[shots] title")
    assert w is not None and "缺 type" in w


def test_check_category_unknown_type():
    w = tags.check_category("[shots/frobnicate] title")
    assert w is not None and "不在固定字彙" in w


# ── build_task_description ───────────────────────────────────────────────────

def test_build_task_description_structure():
    out = tags.build_task_description(
        complexity="M",
        hours="3",
        tags={"關聯任務": "#10 #11", "關鍵檔案": "src/foo.py"},
        body="Do the thing.",
    )
    assert "複雜度: M" in out
    assert "預估工時: ~3h （樂觀估計）" in out
    assert "## AI 標籤" in out
    assert "**關聯任務：** #10 #11" in out      # link tag → bold-prefix
    assert "- 關鍵檔案: src/foo.py" in out       # info tag → list item
    assert "## 內容" in out
    assert out.rstrip().endswith("Do the thing.")


def test_build_task_description_roundtrips_through_parse():
    out = tags.build_task_description(
        complexity="M",
        hours="3",
        tags={"關聯任務": "#10 #11", "關鍵檔案": "src/foo.py"},
        body="",
    )
    assert parse.extract_info_tags(out).get("關鍵檔案") == ["src/foo.py"]
    refs = parse.extract_refs(out)
    assert len(refs) == 1
    assert refs[0].kind == "關聯任務" and refs[0].ids == [10, 11]


def test_build_task_description_no_tags_omits_section():
    out = tags.build_task_description("S", "1", tags=None, body="x")
    assert "## AI 標籤" not in out
    assert "複雜度: S" in out
    assert "## 內容" in out


def test_build_task_description_legacy_alias():
    # 相關 task → canonical 關聯任務 link tag
    out = tags.build_task_description("S", "1", tags={"相關 task": "#5"}, body="")
    assert "**關聯任務：** #5" in out


def test_build_task_description_skips_empty_values():
    out = tags.build_task_description(
        "S", "1", tags={"關鍵檔案": "", "驗證指令": "pytest"}, body="",
    )
    assert "關鍵檔案" not in out
    assert "- 驗證指令: pytest" in out


# ── small title/description helpers ─────────────────────────────────────────

def test_title_with_id_prefix():
    assert tags.title_with_id_prefix(7, "[a/feat] hi") == "#7 [a/feat] hi"


def test_description_with_first_line_title():
    assert tags.description_with_first_line_title("#7 hi", "body") == "#7 hi\n\nbody"
