"""Description parsing helpers for aitask (dev8 #130 Phase 1).

Tasks and documents in AiCodeTask store all state in a single markdown
`description` / `body_md` blob. AI agents reading these pay full-blob
token cost even when they only need recent log entries or the handoff
state. These pure functions extract structured slices on-demand.

Parsers are tolerant of variation — older tasks predate some conventions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional


# Log entry separator written by `append_to_task_description`:
#   `\n\n---\n[YYYY-MM-DD] note text...`
# Capture: date + body (multiline-friendly until next ---\n[ or end).
_LOG_RE = re.compile(
    r"\n---\n\[(\d{4}-\d{2}-\d{2})\][ \t]?(.*?)(?=\n---\n\[|\Z)",
    re.DOTALL,
)

# Handoff / state markers — bold-prefix anywhere on a line. Last occurrence
# wins (log entries can override earlier body state).
# dev8 #141 — milestone tags 完成條件 / 達成總結 are checkpoint state, not
# handoff per-se, but share the same "current state" semantic (last wins).
_HANDOFF_TAGS = ["下次接手", "等", "阻擋", "被阻擋", "完成於",
                 "完成條件", "達成總結"]
_HANDOFF_RE = re.compile(
    r"\*\*(" + "|".join(_HANDOFF_TAGS) + r")[：:]\*\*\s*([^\n]+)",
)

# Forward refs — bold-prefix `**X：** #N #N`
# dev8 #140 Phase 3b-i: 4 new typed tags (承接 / 取代 / 副產物 / 實現 / 子任務)
# join the existing 4 (關聯任務 / 關聯文件 / 阻擋 / 被阻擋).
_FORWARD_REF_TAGS = [
    "關聯任務", "關聯文件", "阻擋", "被阻擋",
    "承接", "取代", "副產物", "實現", "子任務",
]
_FORWARD_REF_RE = re.compile(
    r"\*\*(" + "|".join(_FORWARD_REF_TAGS) + r")[：:]\*\*\s+((?:#\d+(?:\s+#\d+)*))",
)

# Mapping bold-prefix tag → canonical relation_kind in DB.
# Direction: tag-source is the source of the relation, target is the #N.
# 「父子」反向: 子任務: #N #N → parent (source) parent_of children (targets)
# 被阻擋: #N — source is `**被阻擋：**` writer, target is N. So relation
#   is "target blocks source" → store as (target, blocks, source).
# 關聯任務 / 關聯文件 → relates (generic, no direction)
# 阻擋 → source blocks target
# 承接 → source follow_up_of target
# 取代 → source supersedes target
# 副產物 → source discovered_during target
# 實現 → source implements target
# 子任務 → source parent_of each target
TAG_TO_RELATION = {
    "關聯任務": ("relates", "forward"),
    "關聯文件": ("relates", "forward"),
    "阻擋": ("blocks", "forward"),
    "被阻擋": ("blocks", "reverse"),  # store inversed: target blocks source
    "承接": ("follow_up_of", "forward"),
    "取代": ("supersedes", "forward"),
    "副產物": ("discovered_during", "forward"),
    "實現": ("implements", "forward"),
    "子任務": ("parent_of", "forward"),
}

# dev8 #138 follow-up — weak refs: prose patterns that imply relation but
# weren't explicitly tagged. Includes title parenthetical refs like
# `(#116/#117 follow-up)` and inline `承 #N` / `接續 #N` / `承接 #N`.
_WEAK_REF_PATTERNS = [
    # `(#N something)` or `(#N/#N follow-up)`
    re.compile(r"\(\s*#(\d+)(?:[/、,\s]+#(\d+))?\s*[^)]*?(?:follow-up|follow up|後續|延伸|擴張|相關)\s*\)", re.IGNORECASE),
    # `承 #N` / `接續 #N` / `承接 #N` / `延續 #N`
    re.compile(r"(?:承|接續|承接|延續|延伸|基於|擴張)\s*#(\d+)"),
    # `#N follow-up` / `#N 之延伸` / `#N 補強`
    re.compile(r"#(\d+)\s*(?:follow-?up|之延伸|補強|完善)"),
]

# 踩雷 tag → references decision/lesson — extract referenced ids
_TRAP_REF_RE = re.compile(
    r"^[ \t]*-[ \t]+踩雷紀錄[：:][ \t]*(.+?)$",
    re.MULTILINE,
)

# Info tags — whitelist keys from CLAUDE.md convention. Anchored start-of-line
# `- key: value`. Whitelist avoids matching arbitrary prose with colons.
_INFO_TAG_KEYS = ["關鍵檔案", "驗證指令", "驗證", "踩雷紀錄", "下次留意", "標籤", "tag"]
_INFO_TAG_RE = re.compile(
    r"^[ \t]*-[ \t]+(" + "|".join(_INFO_TAG_KEYS) + r")[：:][ \t]*(.+?)$",
    re.MULTILINE,
)

# Numeric ID extraction (#NN)
_HASH_ID_RE = re.compile(r"#(\d+)")


@dataclass
class LogEntry:
    date: str
    body: str


@dataclass
class HandoffState:
    """Current state from `**下次接手：** ... ` / `**等：** ...` / etc.
    Only most-recent (last) occurrence wins — `aitask log` appends, so
    later overrides earlier."""
    kind: str   # 下次接手 / 等 / 阻擋 / 被阻擋 / 完成於
    note: str


@dataclass
class Ref:
    kind: str   # 關聯任務 / 關聯文件 / 阻擋 / 被阻擋
    ids: List[int]


# ── Parsers ────────────────────────────────────────────────────────────────

def extract_logs(description: str) -> List[LogEntry]:
    """Return all log entries (appended via `aitask log`) in order."""
    if not description:
        return []
    out: List[LogEntry] = []
    # Prepend `\n` so the first `---\n[` after `\n\n` matches `\n---\n[`
    normalized = "\n" + description if not description.startswith("\n") else description
    for m in _LOG_RE.finditer(normalized):
        out.append(LogEntry(date=m.group(1), body=m.group(2).strip()))
    return out


def extract_handoff(description: str) -> Optional[HandoffState]:
    """Return the LAST handoff marker in the description (logs override
    earlier). None if no handoff tag present.

    Note: `**完成於：**` is included — it's the "done state" handoff.
    """
    if not description:
        return None
    matches = list(_HANDOFF_RE.finditer(description))
    if not matches:
        return None
    m = matches[-1]
    return HandoffState(kind=m.group(1), note=m.group(2).strip())


def extract_refs(description: str) -> List[Ref]:
    """Return all forward refs: `**X：** #N #N` style."""
    if not description:
        return []
    out: List[Ref] = []
    for m in _FORWARD_REF_RE.finditer(description):
        ids = [int(x) for x in _HASH_ID_RE.findall(m.group(2))]
        if ids:
            out.append(Ref(kind=m.group(1), ids=ids))
    return out


def extract_weak_refs(title: str, description: str) -> List[int]:
    """Return ids implied by prose patterns (NOT bold-prefix tagged).
    Title parenthetical (#N follow-up), `承 #N`, `#N 之延伸` etc.

    These are weaker signal than bold-prefix `**關聯任務：** #N` —
    catches mid-2026 dev tasks that put follow-up info in title only.
    """
    corpus = (title or "") + "\n" + (description or "")
    if not corpus.strip():
        return []
    ids: set[int] = set()
    for pat in _WEAK_REF_PATTERNS:
        for m in pat.finditer(corpus):
            for g in m.groups():
                if g:
                    try:
                        ids.add(int(g))
                    except (ValueError, TypeError):
                        pass
    return sorted(ids)


def extract_trap_refs(description: str) -> List[int]:
    """Extract decision/doc ids from `- 踩雷紀錄: refs decision #N`.

    Returns the referenced ids (which doc explained / triggered the lesson).
    Used by graph mode to mark task as ⚠ trap + edge to source decision.
    """
    if not description:
        return []
    body = description.split("\n---\n[", 1)[0]
    ids: set[int] = set()
    for m in _TRAP_REF_RE.finditer(body):
        for hm in _HASH_ID_RE.finditer(m.group(1)):
            try:
                ids.add(int(hm.group(1)))
            except (ValueError, TypeError):
                pass
    return sorted(ids)


def has_trap_marker(description: str) -> bool:
    """True if description has a `踩雷紀錄` info tag (regardless of refs)."""
    if not description:
        return False
    body = description.split("\n---\n[", 1)[0]
    return bool(_TRAP_REF_RE.search(body))


def extract_info_tags(description: str) -> dict[str, list[str]]:
    """Return `- key: value` info tags. Same key can repeat (e.g.
    `- 關鍵檔案: a` `- 關鍵檔案: b`) → dict value is a list."""
    if not description:
        return {}
    # Only scan the body (before the first log separator), so we don't pick
    # up commit log lines that happen to start with `-`.
    body = description.split("\n---\n[", 1)[0]
    out: dict[str, list[str]] = {}
    for m in _INFO_TAG_RE.finditer(body):
        key = m.group(1).strip()
        # Skip header-like keys (短全形, mostly section labels)
        if "##" in key or "**" in key:
            continue
        out.setdefault(key, []).append(m.group(2).strip())
    return out


def extract_summary(description: str, max_chars: int = 240) -> str:
    """First meaningful paragraph after title — for one-line summary use.

    Strategy: skip the title (first line) + meta (複雜度 / 預估工時) + the
    first `## 內容` heading, then take the first non-empty paragraph.
    Truncate at `max_chars` with trailing `...`.
    """
    if not description:
        return ""
    # Stop at first log separator
    body = description.split("\n---\n[", 1)[0]
    lines = body.split("\n")
    paragraphs: list[str] = []
    cur: list[str] = []
    for line in lines:
        if line.strip() == "":
            if cur:
                paragraphs.append("\n".join(cur))
                cur = []
            continue
        cur.append(line)
    if cur:
        paragraphs.append("\n".join(cur))

    # Filter out paragraphs that are clearly meta / heading
    SKIP_PREFIXES = ("#", "##", "###", "複雜度", "預估工時")
    for p in paragraphs:
        first = p.lstrip().split("\n", 1)[0]
        if first.startswith(SKIP_PREFIXES):
            continue
        # Heuristic: skip pure tag block
        if first.startswith("- ") and "：" in first or first.startswith("**"):
            continue
        text = p.strip()
        if not text:
            continue
        if len(text) > max_chars:
            return text[:max_chars].rstrip() + "..."
        return text
    return ""


# ── Helpers for grep / search ──────────────────────────────────────────────

def snippet_around(text: str, match_start: int, match_end: int,
                   ctx: int = 40) -> str:
    """Return text[max(0, start-ctx) : end+ctx], collapsing newlines to
    space + adding ellipsis if truncated."""
    if not text:
        return ""
    s = max(0, match_start - ctx)
    e = min(len(text), match_end + ctx)
    out = text[s:e].replace("\n", " ")
    if s > 0:
        out = "..." + out
    if e < len(text):
        out = out + "..."
    return out


def last_log_date(description: str) -> Optional[str]:
    """Date of the most recent log entry, or None."""
    logs = extract_logs(description)
    return logs[-1].date if logs else None


# ── Digest (Phase 1.5) ─────────────────────────────────────────────────────

# Match `commit <hex7-40>` token inside log body (the standard prefix
# `aitask log --commit X "note"` produces).
_COMMIT_RE = re.compile(r"\bcommit ([0-9a-f]{7,40})\b")


def build_digest(item: dict, kind: str = "task") -> str:
    """Return a token-efficient summary (~80-150 tokens) of a task or doc.

    Sections (only printed if non-empty):
      - Header: `#<id> [<status>] <title>`
      - Meta:   complexity / hours / module category
      - Refs:   forward bold-prefix refs (related tasks/docs/decisions)
      - Files:  key_files info tags
      - Commits: list of commit hashes mentioned in log entries (dedup, order-preserving)
      - State:  current handoff (下次接手/等/阻擋/完成於)
      - Last:   most recent log entry, truncated to ~80 chars
    """
    item_id = item.get("id", "?")
    title = (item.get("title") or "").strip()
    # Strip leading `#NN ` prefix — backend (decision #37) prepends it
    # already, so avoid `#118 [done] #118 ...` doubling.
    title = re.sub(r"^#\d+\s+", "", title)
    status = item.get("status") or ""
    desc = item.get("description") if kind == "task" else item.get("body_md")
    desc = desc or ""

    lines: list[str] = []
    lines.append(f"#{item_id} [{status}] {title}")

    # Meta — complexity + hours (parsed from raw markdown, fast)
    meta_parts: list[str] = []
    m1 = re.search(r"^複雜度[：:][ \t]*(\w+)", desc, re.MULTILINE)
    if m1:
        meta_parts.append(m1.group(1))
    m2 = re.search(r"^預估工時[：:][ \t]*~?([\d.]+)\s*h?", desc, re.MULTILINE)
    if m2:
        meta_parts.append(f"~{m2.group(1)}h")
    if meta_parts:
        lines.append(" / ".join(meta_parts))

    # Refs — forward only (reverse would require scanning all items, too
    # expensive for a digest)
    refs = extract_refs(desc)
    if refs:
        chunks = []
        for r in refs:
            ids_str = " ".join(f"#{x}" for x in r.ids)
            chunks.append(f"{r.kind}: {ids_str}")
        lines.append("→ " + " / ".join(chunks))

    # Key files (info tags whitelist)
    tags = extract_info_tags(desc)
    if "關鍵檔案" in tags:
        files = tags["關鍵檔案"]
        # Compact file list: strip parens / annotations, keep path-like
        compact_files = []
        for f in files:
            # Often `path/to/foo.py (description)` — keep path part
            short = f.split("(")[0].strip().split(",")[0].strip()
            if short:
                compact_files.append(short)
        if compact_files:
            lines.append("files: " + ", ".join(compact_files[:8]))
            if len(compact_files) > 8:
                lines[-1] += f" (+{len(compact_files) - 8} more)"

    # Commit hashes (deduped, order-preserving from log entries)
    logs = extract_logs(desc)
    commits: list[str] = []
    seen_commits: set[str] = set()
    for L in logs:
        for cm in _COMMIT_RE.finditer(L.body):
            h = cm.group(1)[:7]  # short hash
            if h not in seen_commits:
                seen_commits.add(h)
                commits.append(h)
    if commits:
        lines.append(f"commits ({len(commits)}): " + ", ".join(commits))

    # Current state (handoff / 等 / 阻擋 / 完成於)
    h = extract_handoff(desc)
    if h:
        note = h.note
        if len(note) > 80:
            note = note[:80].rstrip() + "..."
        lines.append(f"state: **{h.kind}：** {note}")

    # Most recent log snippet (if not already captured by state above)
    if logs and (not h or logs[-1].body[:50] != h.note[:50]):
        last = logs[-1]
        snippet = last.body
        if len(snippet) > 100:
            snippet = snippet[:100].rstrip() + "..."
        lines.append(f"last: [{last.date}] {snippet}")

    return "\n".join(lines)


# ── Phases (Phase 3b-v / #143) ─────────────────────────────────────────────
# Plan docs describe work in phases. Parser extracts phase labels from
# headings + bullets, normalizes to canonical labels. Used by `aitask phases`
# to aggregate task status + timespan per phase.

# Heading-style phase declarations carry more weight (canonical)
_PHASE_HEADING_RE = re.compile(
    r"^#{2,4}\s+.*?Phase\s+([0-9A-Za-z][\w-]*).*?$",
    re.MULTILINE,
)
# Bullet-style ones
_PHASE_BULLET_RE = re.compile(
    r"^[ \t]*-\s+.*?Phase\s+([0-9A-Za-z][\w-]*).*?$",
    re.MULTILINE,
)


def extract_phases(body_md: str) -> List[str]:
    """Extract canonical phase labels from a plan doc body in declaration order.

    Heuristic: headings (`### Phase X`) are strong canonical signals. Bullets
    that say `- Phase X ...` reinforce. Dedup case-insensitively, preserve
    first-occurrence order.

    Returns list like ['A', 'B', 'C'] or ['1', '2', '3a', '3b-i'].
    """
    if not body_md:
        return []
    seen_lower: set[str] = set()
    out: list[str] = []
    # Headings first — they're canonical
    for m in _PHASE_HEADING_RE.finditer(body_md):
        label = m.group(1)
        if label.lower() not in seen_lower:
            seen_lower.add(label.lower())
            out.append(label)
    # Then bullets (may add new ones)
    for m in _PHASE_BULLET_RE.finditer(body_md):
        label = m.group(1)
        if label.lower() not in seen_lower:
            seen_lower.add(label.lower())
            out.append(label)
    return out


def task_mentions_phase(task_title: str, task_desc: str,
                        phase_label: str) -> bool:
    """True if task title or first 500 chars of description mention this
    phase label as a `Phase X` token.

    Uses word-boundary match to avoid `Phase 1` matching `Phase 12`.
    """
    if not phase_label:
        return False
    pat = re.compile(r"\bPhase\s+" + re.escape(phase_label) + r"\b",
                     re.IGNORECASE)
    corpus = (task_title or "") + "\n" + (task_desc or "")[:500]
    return bool(pat.search(corpus))


@dataclass
class PhaseSummary:
    label: str
    task_ids: List[int]
    status_counts: dict        # {'done': 5, 'in_progress': 2, ...}
    first_commit_at: Optional[str]
    last_commit_at: Optional[str]
    commit_count: int


def derive_task_timespan(
    task_id: int, all_commits: List[dict]
) -> tuple:
    """Return (first_committed_at, last_committed_at) for a task.

    `all_commits` is the list from /task-commits endpoint (or equivalent).
    Returns (None, None) if no commits for this task.
    """
    relevant = [c for c in all_commits if c.get("task_id") == task_id]
    if not relevant:
        return None, None
    ts = sorted(c.get("committed_at") or "" for c in relevant)
    return (ts[0] or None, ts[-1] or None)


def aggregate_phase_summary(
    phase_label: str,
    candidate_tasks: List[dict],
    all_commits: List[dict],
) -> PhaseSummary:
    """Given a phase label + candidate tasks (already filtered to be
    related to the plan doc), build a summary.
    """
    task_ids: list[int] = []
    status_counts: dict = {}
    first_ts: Optional[str] = None
    last_ts: Optional[str] = None
    commit_count = 0
    for t in candidate_tasks:
        if not task_mentions_phase(t.get("title") or "",
                                    t.get("description") or "",
                                    phase_label):
            continue
        task_ids.append(t["id"])
        st = t.get("status") or "unknown"
        status_counts[st] = status_counts.get(st, 0) + 1
        ft, lt = derive_task_timespan(t["id"], all_commits)
        if ft and (first_ts is None or ft < first_ts):
            first_ts = ft
        if lt and (last_ts is None or lt > last_ts):
            last_ts = lt
        commit_count += sum(1 for c in all_commits if c.get("task_id") == t["id"])
    return PhaseSummary(
        label=phase_label,
        task_ids=task_ids,
        status_counts=status_counts,
        first_commit_at=first_ts,
        last_commit_at=last_ts,
        commit_count=commit_count,
    )


# ── Graph (Phase 3b / #138) ────────────────────────────────────────────────

@dataclass
class GraphNode:
    """Generic node — works for any aitask data, not project-specific."""
    key: str           # 't<id>' or 'd<id>' — unique handle for Mermaid
    kind: str          # 'task' | 'doc'
    doc_type: Optional[str]  # 'decision' | 'plan' | 'memoir' | None (other docs)
    item_id: int
    title: str
    status: str
    in_count: int = 0
    out_count: int = 0
    is_trap: bool = False     # has 踩雷紀錄 tag
    is_anchor: bool = False   # auto-included as a referenced root (outside scope)
    is_milestone: bool = False  # dev8 #146 — milestone flag from doc field


@dataclass
class GraphEdge:
    source: str        # node key
    target: str        # node key
    relation: str      # 'blocks' | 'relates' | 'triggers' | 'cancelled_by' | 'weak_relates' | 'learned_from'


# Doc title prefix → doc_type mapping (CLAUDE.md convention)
_DOC_TYPE_PREFIXES = [
    ("[decision]", "decision"),
    ("[plan]", "plan"),
    ("[memoir]", "memoir"),
]


def _detect_doc_type(title: str) -> Optional[str]:
    """Return 'decision' / 'plan' / 'memoir' from title prefix, or None."""
    if not title:
        return None
    # Strip leading `#NN ` prefix (decision #37 convention) first
    stripped = re.sub(r"^#\d+\s+", "", title.strip())
    for prefix, kind in _DOC_TYPE_PREFIXES:
        if stripped.startswith(prefix):
            return kind
    return None


def _strip_title_for_label(title: str, max_chars: int = 36) -> str:
    """Compact title for graph label: strip #NN prefix + [type] tag + truncate."""
    if not title:
        return ""
    t = re.sub(r"^#\d+\s+", "", title.strip())
    t = re.sub(r"^\[[^\]]+\]\s*", "", t)  # strip leading bracket tag
    if len(t) > max_chars:
        t = t[:max_chars].rstrip() + "…"
    # Mermaid label escaping — quotes need swap to avoid syntax break
    t = t.replace('"', "'").replace("\n", " ")
    return t


def _doc_has_milestone_flag(doc: dict) -> bool:
    """Detect milestone flag. Handles two shapes:

    1. Synthetic `_milestone_flag: True` annotation (preferred — caller
       pre-resolves field id once outside this hot loop). Used by cmd_graph.
    2. List format `[{field_name, value}]` (legacy / direct API consumer).

    field_values dict form `{field_id_str: value}` is NOT handled here —
    caller must annotate `_milestone_flag` first (field id varies per
    project, name→id map needs API call).
    """
    if doc.get("_milestone_flag") is True:
        return True
    fv = doc.get("field_values")
    if isinstance(fv, list):
        truthy = (True, 1, "1", "true", "True", "yes")
        for entry in fv:
            if (entry.get("field_name") == "是否里程碑"
                    and entry.get("value") in truthy):
                return True
    return False


def build_graph(
    tasks: List[dict],
    docs: List[dict],
    include_isolated: bool = True,
    extra_docs_pool: Optional[List[dict]] = None,
    relations: Optional[List[dict]] = None,
) -> tuple:
    """Build node + edge lists from raw task/doc data.

    Tasks and docs are dicts (with `description` or `body_md` populated).

    Edge sources (in order of priority):
    1. **`relations` param** (Phase 3b-i / dev8 #146) — structured
       item_relations rows with typed relation_kind. Used when provided.
    2. **markdown bold-prefix tags** (legacy / fallback) — extract_refs.
       Used when `relations` is None or as supplement (weak/trap edges
       are always parsed from markdown since they have no structured form).

    weak refs (prose 承 #N) and 踩雷紀錄 → decision edges are STILL parsed
    from markdown regardless — those don't have structured-table counterparts.

    `extra_docs_pool`: optional list of ALL docs (regardless of scope).
    When a scope item references a decision/plan outside scope, it gets
    auto-included from this pool as an anchor node (lighter style).
    Fixes "起點看不到" complaint in #138 follow-up.
    """
    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []

    # Build node index for in-scope items
    for t in tasks:
        key = f"t{t['id']}"
        body = t.get("description") or ""
        title = t.get("title") or ""
        nodes[key] = GraphNode(
            key=key, kind="task", doc_type=None,
            item_id=t["id"],
            title=_strip_title_for_label(title),
            status=t.get("status") or "",
            is_trap=has_trap_marker(body),
        )
    for d in docs:
        key = f"d{d['id']}"
        nodes[key] = GraphNode(
            key=key, kind="doc",
            doc_type=_detect_doc_type(d.get("title") or ""),
            item_id=d["id"],
            title=_strip_title_for_label(d.get("title") or ""),
            status=d.get("status") or "",
            is_milestone=_doc_has_milestone_flag(d),
        )

    # Pool of ALL docs (for anchor auto-include).
    pool_by_id: dict[int, dict] = {}
    if extra_docs_pool:
        for d in extra_docs_pool:
            pool_by_id[d["id"]] = d

    def _maybe_add_anchor(target_id: int) -> Optional[str]:
        """If target_id is a decision/plan doc not yet in nodes, add it
        from pool as an anchor (lighter style). Returns the new key
        or None if not addable."""
        cand_key = f"d{target_id}"
        if cand_key in nodes:
            return cand_key
        if target_id not in pool_by_id:
            return None
        d = pool_by_id[target_id]
        dt = _detect_doc_type(d.get("title") or "")
        if dt not in ("decision", "plan"):
            return None
        nodes[cand_key] = GraphNode(
            key=cand_key, kind="doc", doc_type=dt,
            item_id=target_id,
            title=_strip_title_for_label(d.get("title") or ""),
            status=d.get("status") or "",
            is_anchor=True,
            # dev8 #146 — also propagate milestone flag for anchor docs
            # (often the case for cross-cycle plans like [#19] dev8 主軸
            # being out-of-scope but referenced)
            is_milestone=_doc_has_milestone_flag(d),
        )
        return cand_key

    use_structured = relations is not None
    if use_structured:
        # ── Path A: structured edges from item_relations table ─────────────
        # dev8 #146 — typed kinds from Phase 3b-i: blocks / triggered_by /
        # follow_up_of / supersedes / discovered_during / implements /
        # parent_of / relates. Each preserved as-is in GraphEdge.relation
        # for distinct mermaid edge styling.
        for r in relations:
            s_kind, s_id = r.get("source_kind"), r.get("source_id")
            t_kind, t_id = r.get("target_kind"), r.get("target_id")
            rel = r.get("relation_kind") or "relates"
            src_key = f"{'t' if s_kind == 'task' else 'd'}{s_id}"
            tgt_key = f"{'t' if t_kind == 'task' else 'd'}{t_id}"
            # Anchor-include if target is decision/plan outside scope
            if t_kind == "doc":
                _maybe_add_anchor(t_id)
            if s_kind == "doc":
                _maybe_add_anchor(s_id)
            if src_key in nodes and tgt_key in nodes:
                edges.append(GraphEdge(source=src_key, target=tgt_key, relation=rel))
    else:
        # ── Path B (legacy / fallback): markdown bold-prefix tag parse ─────
        for t in tasks:
            src_key = f"t{t['id']}"
            if src_key not in nodes:
                continue
            body = t.get("description") or ""
            for ref in extract_refs(body):
                for target_id in ref.ids:
                    _maybe_add_anchor(target_id)
                    edges.extend(_make_edges(src_key, ref.kind, target_id, nodes))
        for d in docs:
            src_key = f"d{d['id']}"
            if src_key not in nodes:
                continue
            body = d.get("body_md") or ""
            for ref in extract_refs(body):
                for target_id in ref.ids:
                    _maybe_add_anchor(target_id)
                    edges.extend(_make_edges(src_key, ref.kind, target_id, nodes))

    # ── Weak refs + 踩雷 edges ALWAYS parsed from markdown — no structured form
    for t in tasks:
        src_key = f"t{t['id']}"
        if src_key not in nodes:
            continue
        body = t.get("description") or ""
        title = t.get("title") or ""
        for target_id in extract_weak_refs(title, body):
            _maybe_add_anchor(target_id)
            for cand in (f"t{target_id}", f"d{target_id}"):
                if cand in nodes:
                    edges.append(GraphEdge(source=cand, target=src_key,
                                           relation="weak_relates"))
                    break
        for trap_id in extract_trap_refs(body):
            _maybe_add_anchor(trap_id)
            cand = f"d{trap_id}"
            if cand in nodes:
                edges.append(GraphEdge(source=cand, target=src_key,
                                       relation="learned_from"))

    # Dedupe edges (prefer strong over weak on same pair)
    seen: dict = {}
    # dev8 #146 — 8 typed kinds from Phase 3b-i + legacy markdown-parse kinds.
    # Higher priority = wins on (source, target) collision.
    priority = {
        "supersedes": 5, "blocks": 4, "triggered_by": 4, "triggers": 4,
        "follow_up_of": 4, "implements": 4, "parent_of": 4,
        "discovered_during": 3, "learned_from": 3,
        "relates": 2, "weak_relates": 1, "cancelled_by": 4,
    }
    for e in edges:
        pair = (e.source, e.target)
        if pair in seen:
            old = seen[pair]
            if priority.get(e.relation, 0) > priority.get(old.relation, 0):
                seen[pair] = e
        else:
            seen[pair] = e
    unique = list(seen.values())

    # Update node degree counters
    for e in unique:
        if e.source in nodes:
            nodes[e.source].out_count += 1
        if e.target in nodes:
            nodes[e.target].in_count += 1

    # Optionally drop isolated nodes
    if not include_isolated:
        nodes = {k: n for k, n in nodes.items()
                 if n.in_count + n.out_count > 0 or n.is_trap}
        unique = [e for e in unique
                  if e.source in nodes and e.target in nodes]

    return list(nodes.values()), unique


def _make_edges(src_key: str, ref_kind: str, target_id: int,
                nodes: dict[str, GraphNode]) -> list[GraphEdge]:
    """Resolve a ref into one or more edges (a task ref can refer to either
    a task or a doc — we add edges for whichever exists)."""
    out = []
    # Per-kind direction & relation:
    #   被阻擋: #N → N blocks src   (edge N → src, solid)
    #   阻擋:   #N → src blocks N   (edge src → N, solid)
    #   關聯任務 / 關聯文件 → src relates N (dotted)
    #   When a doc is decision/plan AND src is a task, treat as triggers (D → src)
    relation = {
        "被阻擋": "blocks",       # reversed direction
        "阻擋": "blocks",
        "關聯任務": "relates",
        "關聯文件": "relates",
    }.get(ref_kind, "relates")

    # Look up target in BOTH namespaces (task or doc)
    candidates = [f"t{target_id}", f"d{target_id}"]
    for cand in candidates:
        if cand not in nodes:
            continue

        if ref_kind == "被阻擋":
            out.append(GraphEdge(source=cand, target=src_key, relation="blocks"))
        elif ref_kind == "阻擋":
            out.append(GraphEdge(source=src_key, target=cand, relation="blocks"))
        elif ref_kind == "關聯文件":
            tgt_node = nodes[cand]
            # If target is decision/plan, treat as triggers (D → src)
            if tgt_node.kind == "doc" and tgt_node.doc_type in ("decision", "plan"):
                out.append(GraphEdge(source=cand, target=src_key, relation="triggers"))
            else:
                out.append(GraphEdge(source=src_key, target=cand, relation="relates"))
        else:  # 關聯任務 / unknown
            out.append(GraphEdge(source=src_key, target=cand, relation="relates"))
    return out


def render_mermaid(
    nodes: List[GraphNode],
    edges: List[GraphEdge],
    direction: str = "TD",
    show_isolated_warning: bool = True,
) -> str:
    """Render nodes + edges as Mermaid flowchart syntax.

    Conventions (per #138 spec):
    - Shapes: task `[...]` rect / decision `{...}` diamond / plan `[/.../]`
      parallelogram / memoir `((...))` circle
    - Colors via classDef by status (done / cancelled / in_progress /
      pending) and doc_type (decision / plan / memoir override)
    - Isolated nodes (in_count + out_count == 0) → red border warning
    - Edge styles: blocks solid `-->`, relates dotted `-.relates.->`,
      triggers solid bold `==>`, cancelled_by `--x|cancel|`
    """
    lines: list[str] = [f"flowchart {direction}"]
    # classDef declarations
    lines.extend([
        "  classDef done fill:#d1fae5,stroke:#16a34a",
        "  classDef cancelled fill:#f3f4f6,stroke:#94a3b8,stroke-dasharray:5",
        "  classDef in_progress fill:#fef3c7,stroke:#d97706",
        "  classDef pending fill:#f9fafb,stroke:#6b7280",
        "  classDef decision fill:#e9d5ff,stroke:#8b5cf6,stroke-width:2px",
        "  classDef plan fill:#dbeafe,stroke:#2563eb,stroke-width:2px",
        "  classDef memoir fill:#fce7f3,stroke:#db2777",
        "  classDef isolated fill:#fee2e2,stroke:#dc2626,stroke-width:3px",
        # dev8 #138 follow-up — trap (踩雷) marker: red border + bold
        "  classDef trap fill:#fef2f2,stroke:#dc2626,stroke-width:2px,stroke-dasharray:3",
        # anchor — auto-included reference root (outside scope), lighter
        "  classDef anchor fill:#faf5ff,stroke:#a78bfa,stroke-dasharray:2",
        # dev8 #146 — milestone: 金色粗邊 ⭐
        "  classDef milestone fill:#fef3c7,stroke:#d97706,stroke-width:3px",
    ])

    # Node lines
    for n in nodes:
        # Label prefix: ⭐ milestone > ⚠ trap > nothing
        # dev8 #146 — milestone signal supersedes trap visually (milestone
        # docs unlikely to also be traps; if they are, milestone wins as
        # primary identity)
        if n.is_milestone:
            label_prefix = "⭐ "
        elif n.is_trap:
            label_prefix = "⚠ "
        else:
            label_prefix = ""
        label = f"{label_prefix}#{n.item_id} {n.title}".strip()
        shape_open, shape_close = _shape_brackets(n)
        line = f'  {n.key}{shape_open}"{label}"{shape_close}'
        # Apply class — priority:
        #   milestone > isolated > trap > anchor > doc_type > status
        is_isolated = (n.in_count + n.out_count) == 0
        if n.is_milestone:
            line += ":::milestone"
        elif is_isolated and show_isolated_warning and not n.is_trap:
            line += ":::isolated"
        elif n.is_trap:
            line += ":::trap"
        elif n.is_anchor and n.doc_type in ("decision", "plan"):
            line += f":::{n.doc_type}"
        elif n.doc_type in ("decision", "plan", "memoir"):
            line += f":::{n.doc_type}"
        else:
            cls = _status_class(n.status)
            if cls:
                line += f":::{cls}"
        lines.append(line)

    # Edge lines — group by relation for readability
    for e in edges:
        lines.append(f"  {_edge_syntax(e)}")

    return "\n".join(lines)


def _shape_brackets(n: GraphNode) -> tuple:
    """Mermaid shape brackets per node kind / doc_type / milestone."""
    # dev8 #146 — milestone doc gets hexagon (visually prominent vs plan
    # parallelogram or decision diamond)
    if n.is_milestone:
        return "{{", "}}"            # hexagon
    if n.kind == "doc":
        if n.doc_type == "decision":
            return "{", "}"          # diamond
        if n.doc_type == "plan":
            return "[/", "/]"        # parallelogram
        if n.doc_type == "memoir":
            return "((", "))"        # circle
        return "([", "])"            # stadium (other docs)
    # task — rectangle
    return "[", "]"


def _status_class(status: str) -> str:
    if not status:
        return ""
    norm = status.lower().replace(" ", "_")
    if norm in ("done", "cancelled", "in_progress", "pending"):
        return norm
    # Common variants
    if norm in ("complete", "completed"):
        return "done"
    if norm in ("canceled",):
        return "cancelled"
    return ""


def _edge_syntax(e: GraphEdge) -> str:
    """Map relation_kind → mermaid edge syntax.

    dev8 #146 — extend with 8 Phase 3b-i typed kinds. Each has its own
    visual: arrow style + optional label so the graph self-documents.
    """
    rel = e.relation
    # ── 8 Phase 3b-i typed kinds ───────────────────────────────────────────
    if rel == "blocks":
        return f"{e.source} --> {e.target}"
    if rel == "triggered_by":
        # B was created because of A → A triggers B (bold solid)
        return f"{e.source} ==>|triggers| {e.target}"
    if rel == "follow_up_of":
        # B continues A's work → arrow with label
        return f"{e.source} --\"follow-up\"--> {e.target}"
    if rel == "supersedes":
        # B replaces A — A is now obsolete (×)
        return f"{e.source} --x|supersedes| {e.target}"
    if rel == "discovered_during":
        # B found while doing A — side branch (dotted with label)
        return f"{e.source} -.\"discovered\".-> {e.target}"
    if rel == "implements":
        # A implemented by B (B realizes A)
        return f"{e.source} ==>|implements| {e.target}"
    if rel == "parent_of":
        # A is the meta task, B is sub
        return f"{e.source} ---|sub| {e.target}"
    # ── Legacy markdown-parse kinds ────────────────────────────────────────
    if rel == "triggers":  # markdown-mode synonym for triggered_by
        return f"{e.source} ==> {e.target}"
    if rel == "cancelled_by":
        return f"{e.source} --x|cancel|{e.target}"
    if rel == "weak_relates":
        # weak refs from prose: thin dotted, no label (least noisy)
        return f"{e.source} -..-> {e.target}"
    if rel == "learned_from":
        return f"{e.source} -.\"⚠ trap\".-> {e.target}"
    # default — relates (dotted)
    return f"{e.source} -.relates.-> {e.target}"
