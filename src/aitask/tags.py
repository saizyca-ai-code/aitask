"""Dual-track tag conventions for task descriptions.

Ports the helpers from the original `.claude/commands/aitask.md` Python
template into a reusable module so CLI / MCP / direct lib callers all use
the same tagging rules (see CLAUDE.md decision #5 / dev7 #41 for the
雙軌資訊架構 rationale).

Two tag families:
  * Link tags (bold-prefix `**key：** value`):
    關聯任務 / 關聯文件 / 阻擋 / 被阻擋
    — RefChips.jsx / refs.py parsers expect these.
  * Info tags (list item `- key: value`):
    關鍵檔案 / 驗證指令 / 踩雷紀錄 / 下次留意 / 完成於 / 下次接手 / 等
    — purely AI-scan oriented, no parser.

Legacy aliases (incoming): `相關 task`/`相關 doc`/`相關 document` are
normalised to the canonical Chinese keys. Outgoing tag rendering always
uses canonical names.
"""
from __future__ import annotations

import re
from typing import Optional

# ── Task category `[area/type]` convention (#198) ───────────────────────────
# Fixed `type` vocabulary (mirrors conventional commits); drives the insights
# timeline category colouring. See CLAUDE.md / AICONTEXT.md「類別標籤」章節.
TASK_TYPES = frozenset({"feat", "bug", "ux", "perf", "refactor", "docs", "chore"})
_TYPE_ALIASES = {"ui": "ux", "fix": "bug", "doc": "docs"}
_CATEGORY_RE = re.compile(r"^\s*(?:#\d+\s+)?\[([^\]]+)\]")
_CATEGORY_HINT = ("建議格式 [area/type]，type ∈ "
                  "{feat, bug, ux, perf, refactor, docs, chore}")


def check_category(title: str) -> Optional[str]:
    """Soft nudge (#198): return a one-line warning if a task title's `[類別]`
    isn't the `[area/type]` convention, else None. Cross-tool guard — surfaced
    by CLI `new` + MCP `aitask_new_task` so any AI creating tasks via aitask
    gets reminded. Advisory only; never blocks creation."""
    m = _CATEGORY_RE.match(title or "")
    if not m:
        return f"⚠ 類別標籤缺漏（標題開頭沒有 [類別]）。{_CATEGORY_HINT}"
    cat = m.group(1).strip()
    if "/" not in cat:
        return f"⚠ 類別 [{cat}] 缺 type（只有 area）。{_CATEGORY_HINT}"
    typ = cat.split("/", 1)[1].strip().lower()
    typ = _TYPE_ALIASES.get(typ, typ)
    if typ not in TASK_TYPES:
        return f"⚠ 類別 [{cat}] 的 type「{typ}」不在固定字彙。{_CATEGORY_HINT}"
    return None


LINK_TAGS = frozenset({"關聯任務", "關聯文件", "阻擋", "被阻擋"})

LINK_ALIAS = {
    "相關 task": "關聯任務",
    "相關 doc": "關聯文件",
    "相關 document": "關聯文件",
}


def build_task_description(
    complexity: str,
    hours: str,
    tags: Optional[dict[str, str]] = None,
    body: str = "",
) -> str:
    """Compose the canonical task description body.

    Output structure:
        複雜度: {complexity}
        預估工時: ~{hours} （樂觀估計）

        ## AI 標籤
        **關聯任務：** #N #N        (link tags via bold-prefix)
        - 關鍵檔案: ...              (info tags via list)

        ## 內容

        {body}

    Args:
        complexity: 'S' / 'M' / 'L' / 'XL'
        hours: e.g. '3' or '6-8' (caller-supplied, no leading ~)
        tags: dict of tag_name → value. Empty values skipped.
              Link-tag keys (or legacy aliases) get bold-prefix rendering.
              Other keys render as list items.
        body: free-form markdown for the ## 內容 section.

    Returns:
        Multi-line string ready to POST as description.
    """
    parts = [
        f"複雜度: {complexity}",
        f"預估工時: ~{hours}h （樂觀估計）",
        "",
    ]
    if tags:
        link_lines: list[str] = []
        info_lines: list[str] = []
        for k, v in tags.items():
            if not v:
                continue
            canonical = LINK_ALIAS.get(k, k)
            if canonical in LINK_TAGS:
                link_lines.append(f"**{canonical}：** {v}")
            else:
                info_lines.append(f"- {k}: {v}")
        if link_lines or info_lines:
            parts.append("## AI 標籤")
            parts.extend(link_lines)
            parts.extend(info_lines)
            parts.append("")
    parts.extend(["## 內容", "", body])
    return "\n".join(parts)


def title_with_id_prefix(task_id: int, raw_title: str) -> str:
    """`#NN <raw_title>` — the canonical task title format per CLAUDE.md.
    Used as second-step PATCH after backend assigns the id."""
    return f"#{task_id} {raw_title}"


def description_with_first_line_title(final_title: str, body: str) -> str:
    """Prepend the title as the first line of description (防 UI 截斷後對齊
    校驗). Body starts after blank line.

    See CLAUDE.md「標題 / 描述同步 convention」for rationale.
    """
    return f"{final_title}\n\n{body}"
