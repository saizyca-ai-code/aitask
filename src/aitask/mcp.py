"""aitask-mcp — MCP (Model Context Protocol) server for AiCodeTask.

Exposes the same operations as the CLI as MCP tools so AI agents with
native MCP support (Claude Code, Cursor, ChatGPT, OpenAI Codex, Gemini
Antigravity, ...) can call them directly without shelling out to the CLI.

Thin wrapper over `AiTaskClient` — when the API or client changes, the
tools auto-follow with minimal code edits here.

Install:
    pip install -e ".[mcp]"

Run (stdio transport):
    aitask-mcp

Configure in MCP-aware tool (Claude Code example):
    {
      "mcpServers": {
        "aitask": {
          "command": "aitask-mcp",
          "env": { "AITASK_TOKEN": "<session_id>" }
        }
      }
    }
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from .client import AiTaskClient, AiTaskError
from .config import load_config
from .tags import (
    build_task_description,
    title_with_id_prefix,
    description_with_first_line_title,
    check_category,
)


def _format_tag_dict(tags: Optional[dict]) -> dict[str, str]:
    """Coerce loose dict (str-keyed, str-valued) into the shape build_task_
    description expects. MCP tool args come in JSON so we normalise here."""
    if not tags:
        return {}
    return {str(k): str(v) for k, v in tags.items() if v}


def _build_server():
    """Lazy-import mcp + construct FastMCP server. Raises ImportError with
    install hint if mcp package missing."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as e:
        raise ImportError(
            "MCP server requires the `mcp` package. Install with:\n"
            "    pip install -e \".[mcp]\"\n"
            "or:\n"
            "    pip install mcp"
        ) from e

    cfg = load_config()
    client = AiTaskClient.from_config(cfg)
    server = FastMCP(
        "aitask",
        instructions=(
            "AiCodeTask — AI dev-progress tracker (tasks + documents).\n\n"
            "BEFORE using any aitask_* write tool (aitask_new_task, aitask_log, "
            "aitask_create_decision / _plan / _spike, aitask_edit), call "
            "`aitask_get_conventions` ONCE this session to load the collaboration "
            "conventions: the dual-track markdown tag vocabulary (連結類 / 資訊類), "
            "task / decision / plan / spike body structure, the '下次接手' handoff "
            "markers, and the deep-link rule for referencing #NN.\n\n"
            "These tools give you ACCESS to the tracker (the WHERE); "
            "`aitask_get_conventions` tells you HOW to write so your markdown "
            "matches the project's format. Skipping it produces plain, "
            "convention-less task/doc bodies. AICONTEXT.md is the single source "
            "of truth for conventions — not any per-tool CLAUDE.md reference "
            "(that file belongs to a different client and is not visible here)."
        ),
    )

    # AICONTEXT.md ships inside the package (pyproject package-data), so the
    # same path resolves for both editable and wheel installs.
    _candidate = Path(__file__).resolve().parent / "AICONTEXT.md"
    _aicontext_path = _candidate if _candidate.is_file() else None

    # ── Tools ───────────────────────────────────────────────────────────

    @server.tool()
    def aitask_get_conventions() -> str:
        """Return the AiCodeTask collaboration conventions (AICONTEXT.md).

        **CALL THIS AT SESSION START** before using any other aitask_* tool.
        The other tools give you ACCESS to AiCodeTask; this tool tells you
        HOW the user expects you to use them — trigger times (L1/L2/L3
        levels), dual-track tag conventions, '下次接手' handoff pattern,
        '否決方案' enforcement rationale, honesty rules, and propose→
        confirm→execute workflow for M+ tasks.

        Without these conventions you'll use the other aitask tools as
        generic APIs and miss the workflow the user actually wants.

        Returns the AICONTEXT.md content as a string (~180 lines markdown).
        """
        if _aicontext_path is None:
            return (
                f"AICONTEXT.md not found at {_candidate}. The aitask package "
                "was installed without its conventions doc (expected as "
                "package-data alongside the module). Manual fallback: ask the "
                "user to point you at AICONTEXT.md in the aitask source repo."
            )
        return _aicontext_path.read_text(encoding="utf-8")

    @server.tool()
    def aitask_list_projects() -> list[dict]:
        """List all visible AiCodeTask-style projects on this server.

        ⚠️ Do NOT pick one yourself and proceed — always show the full list
        to the user and ask which project_id to use. This applies even if
        you're improvising (e.g. a fallback shell that lost your MCP env
        vars, or `project_id` config you can't read) — silently guessing
        (defaulting to whichever project looks familiar from docs/examples,
        or "the first one") writes data into the wrong project without
        anyone noticing. Only proceed once the user has told you which
        project_id to use, or you already have one from a working
        AITASK_PROJECT_ID / config — call this tool only when that's
        genuinely missing, and treat its output as read-only reference
        for the human, not a menu for you to choose from."""
        projects = client.list_projects()
        return [
            {
                "id": p.get("id"),
                "slug": p.get("slug"),
                "name": p.get("name"),
                "description": p.get("description"),
            }
            for p in projects
        ]

    @server.tool()
    def aitask_list(include_done: bool = False) -> dict:
        """List pending tasks in the AiCodeTask project, grouped by status.
        Set include_done=True to also show closed tasks. Use this at session
        start to recover context, or whenever you need to find a task id."""
        items = client.list_tasks()
        opts = client.get_task_status_options()
        status_label = {o["id"]: o["label"] for o in opts.get("options", [])}
        done_ids = {o["id"] for o in opts.get("options", []) if o.get("is_done")}

        groups: dict[str, list[dict]] = {}
        for it in items:
            s = it.get("status") or "unknown"
            if not include_done and s in done_ids:
                continue
            groups.setdefault(s, []).append({
                "id": it["id"],
                "title": it.get("title", ""),
            })
        return {
            "groups": {
                status_label.get(k, k): v for k, v in groups.items()
            },
            "total": sum(len(v) for v in groups.values()),
        }

    @server.tool()
    def aitask_new_task(
        title: str,
        body: str = "",
        complexity: str = "M",
        hours: str = "3",
        tags: Optional[dict] = None,
    ) -> dict:
        """Create a new task with the project's dual-track convention
        (call aitask_get_conventions for the full tag vocabulary + structure).

        Args:
            title: task title (e.g. "[shots] foo bar"). The CLI auto-prepends
                "#NN " after backend assigns the id.
            body: free-form markdown for the ## 內容 section.
            complexity: 'S', 'M', 'L', or 'XL'.
            hours: estimated hours (e.g. "3" or "6-8").
            tags: dict of tag_name → value. Recognised keys auto-route:
                * Link tags (bold-prefix in output): 關聯任務, 關聯文件,
                  阻擋, 被阻擋
                * Info tags (list item in output): 關鍵檔案, 驗證指令,
                  踩雷紀錄, 下次留意, 下次接手, 等

        Returns: {id, title}.
        """
        desc = build_task_description(
            complexity=complexity,
            hours=hours,
            tags=_format_tag_dict(tags),
            body=body,
        )
        result = client.create_task(title, desc)
        task_id = result["id"]

        final_title = title_with_id_prefix(task_id, title)
        final_desc = description_with_first_line_title(final_title, desc)
        client.update_task(task_id, title=final_title, description=final_desc)

        # Structured fields (mirror CLI cmd_new)
        fields = client.get_task_fields()
        field_by_name = {f["name"]: f["id"] for f in fields}
        values = []
        if "複雜度" in field_by_name and complexity in {"S", "M", "L", "XL"}:
            values.append({"field_id": field_by_name["複雜度"], "value": complexity})
        hid = (
            field_by_name.get("預估工時（小時）")
            or field_by_name.get("預估工時(小時)")
            or field_by_name.get("預估工時")
        )
        if hid:
            import re
            m = re.match(r"~?\s*([\d.]+)", str(hours))
            if m:
                values.append({"field_id": hid, "value": m.group(1)})
        if values:
            client.set_task_field_values(task_id, values)

        out = {"id": task_id, "title": final_title}
        warn = check_category(title)   # #198 — soft nudge on [area/type]
        if warn:
            out["convention_warning"] = warn
        return out

    @server.tool()
    def aitask_mark_done(task_id: int, commit_hash: Optional[str] = None) -> dict:
        """Mark a task as done (sets status to whichever option has is_done=True
        in the module's status-options). Use after the corresponding git
        commit lands.

        Args:
            task_id: id of the task to close.
            commit_hash: optional — when set, also writes this value to the
                structured `commit_hash` field on the task (dual-track
                convention: structured field for UI / queries + description
                log entry for AI context). Pass the short or full SHA.
        """
        client.mark_task_done(task_id)
        if commit_hash:
            client.set_task_commit_hash(task_id, commit_hash)
        return {"id": task_id, "status": "done", "commit_hash": commit_hash}

    @server.tool()
    def aitask_log(task_id: int, note: str, commit_hash: Optional[str] = None,
                   is_doc: bool = False) -> dict:
        """Append a timestamped note to a task's description (or a document's
        body_md with is_doc=True). Use after each git commit to record the
        commit hash + summary, or to leave a '下次接手' breadcrumb at session
        end. tasks and docs are SEPARATE id namespaces — set is_doc to target
        a document.

        Args:
            task_id: id of the task (or doc when is_doc=True) to log against.
            note: note text (timestamp prefix added automatically).
            commit_hash: optional (tasks only) — when set, the note is auto-
                prefixed with `commit <hash> — ` AND the value is written to
                the structured `commit_hash` field.
            is_doc: True → append to a DOCUMENT's body_md instead of a task.
        """
        if is_doc:
            client.append_to_doc_body(task_id, note)
            return {"id": task_id, "logged": True, "is_doc": True}
        if commit_hash:
            note = (f"commit {commit_hash} — {note}" if note.strip()
                    else f"commit {commit_hash}")
        client.append_to_task_description(task_id, note)
        if commit_hash:
            client.set_task_commit_hash(task_id, commit_hash)
        return {"id": task_id, "logged": True, "commit_hash": commit_hash}

    @server.tool()
    def aitask_set_status(task_id: int, status: str) -> dict:
        """Explicitly set a task's status (overrides workflow). Use when
        you need to move tasks through specific states beyond just done.
        Available status ids depend on the module — call aitask_list first
        if unsure."""
        client.set_task_status(task_id, status)
        return {"id": task_id, "status": status}

    @server.tool()
    def aitask_create_plan(title: str, body: str = "") -> dict:
        """Create a [plan] document (status=draft). Use after plan mode
        completes to persist the plan for the next session.

        Title is auto-prefixed with '[plan]'. Body should describe the plan
        in markdown.
        """
        doc_id = client.create_doc_typed(
            title, body, doc_type="plan", prefix="[plan]",
        )
        return {"id": doc_id, "type": "plan"}

    @server.tool()
    def aitask_create_decision(title: str, body: str) -> dict:
        """Create a [decision] document (status=published).

        IMPORTANT: body MUST contain the section '否決方案' (rejected
        alternatives) per the project convention (see aitask_get_conventions).
        The tool refuses to create
        a decision doc without it, because decisions without recorded
        alternatives lose all learning value over time. Include a
        `### 否決方案` section listing the options NOT chosen and why.

        Title is auto-prefixed with '[decision]'.
        """
        if "否決方案" not in body:
            raise AiTaskError(
                "Decision doc body must contain a '否決方案' section "
                "explaining what alternatives were rejected and why. "
                "Add a `### 否決方案` block before retrying."
            )
        doc_id = client.create_doc_typed(
            title, body, doc_type="decision", prefix="[decision]",
        )
        return {"id": doc_id, "type": "decision"}

    @server.tool()
    def aitask_create_spike(title: str, body: str = "") -> dict:
        """Create a [spike] document (status=draft) — an exploratory
        'want to do X, not sure how yet' record (pre-plan vision layer).
        Title auto-prefixed '[spike]'. See aitask_get_conventions for spike conventions."""
        doc_id = client.create_doc_typed(
            title, body, doc_type="spike", prefix="[spike]",
        )
        return {"id": doc_id, "type": "spike"}

    @server.tool()
    def aitask_get(item_id: int, is_doc: bool = False) -> dict:
        """Read a single task (default) or document (is_doc=True): title +
        full body + status. Use to inspect a task's handoff/tags/logs or to
        read a decision/plan/doc body before editing. tasks and docs are
        SEPARATE id namespaces."""
        item = client.get_doc(item_id) if is_doc else client.get_task(item_id)
        body = item.get("body_md") if is_doc else item.get("description")
        return {
            "id": item.get("id"),
            "title": item.get("title"),
            "status": item.get("status"),
            "body": body or "",
        }

    @server.tool()
    def aitask_grep(pattern: str, kind: str = "all") -> dict:
        """Full-text search across task / doc bodies. kind: 'task' | 'doc' |
        'all'. Returns matching items with id + title + snippet — the right
        way to 'find related tasks' instead of guessing ids."""
        out: dict = {}
        if kind in ("task", "all"):
            out["tasks"] = client.search_tasks(pattern, limit=100).get("items", [])
        if kind in ("doc", "all"):
            out["docs"] = client.search_docs(pattern, limit=100).get("items", [])
        return out

    @server.tool()
    def aitask_recent(limit: int = 20) -> dict:
        """Recently active tasks / docs (those with recent log activity) — a
        session-start digest of where work last left off."""
        return {
            "tasks": client.recent_tasks(limit=limit).get("items", []),
            "docs": client.recent_docs(limit=limit).get("items", []),
        }

    @server.tool()
    def aitask_edit(
        item_id: int,
        body: Optional[str] = None,
        title: Optional[str] = None,
        is_doc: bool = False,
    ) -> dict:
        """REPLACE a task description / doc body_md (vs aitask_log which
        APPENDS). Use to revise a decision/plan body or fix content. At least
        one of body / title is required.

        For TASKS, body replaces the WHOLE description — you are responsible
        for keeping the first-line '#NN title' + AI tags. Read with aitask_get
        first, edit, then write back.
        """
        if body is None and title is None:
            raise AiTaskError("aitask_edit needs at least one of body / title.")
        fields: dict = {}
        if is_doc:
            client.get_doc(item_id)  # validate existence
            if body is not None:
                fields["body_md"] = body
            if title is not None:
                fields["title"] = title
            client.update_doc(item_id, **fields)
        else:
            client.get_task(item_id)  # validate existence
            if body is not None:
                fields["description"] = body
            if title is not None:
                fields["title"] = title
            client.update_task(item_id, **fields)
        return {"id": item_id, "edited": list(fields.keys()), "is_doc": is_doc}

    @server.tool()
    def aitask_rm(item_id: int, is_doc: bool = False, force: bool = False) -> dict:
        """Delete a task (default) or document (is_doc=True). Soft-delete
        (archive) by default; force=True permanently deletes. The calling
        agent is responsible for confirming intent before calling."""
        if is_doc:
            client.get_doc(item_id)
            client.delete_doc(item_id, force=force)
        else:
            client.get_task(item_id)
            client.delete_task(item_id, force=force)
        return {"id": item_id, "deleted": True, "permanent": force, "is_doc": is_doc}

    return server


def main(argv: Optional[list[str]] = None) -> int:
    """Entrypoint — run MCP server on stdio transport."""
    try:
        server = _build_server()
    except ImportError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"✗ Failed to initialise MCP server: {e}", file=sys.stderr)
        return 1

    server.run()  # FastMCP defaults to stdio transport
    return 0


if __name__ == "__main__":
    sys.exit(main())
