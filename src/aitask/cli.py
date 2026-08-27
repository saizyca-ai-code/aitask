"""aitask CLI — argparse subcommands matching the original Claude Code
skill so existing muscle memory transfers.

Subcommands (mirrors `.claude/commands/aitask.md` originals):
    list [--doc]                list pending tasks (or documents) by status
    new <title>                 create a task with dual-track structure
    done <id>                   mark task as done (status with is_done=True)
    log <id> <note>             append timestamped note to description
    update <id> <status_id>     set status (follows workflow; --force to skip)
    plan <title> [body file]    create [plan] document (status=draft)
    decision <title> [body file] create [decision] document (status=published,
                                 enforces 否決方案 mention per CLAUDE.md)
    doc <type> <title> [body file] generic document creation

Usage:
    aitask list
    aitask new "[shots] foo" --complexity M --hours 3 \\
        --tag "關鍵檔案: app/foo.py:12-30"
    aitask done 42
    aitask log 42 "commit abc123 — sub 2 完成"
"""
from __future__ import annotations

import argparse
import io
import json
import locale
import re
import sys
from pathlib import Path
from typing import Optional

from .client import AiTaskClient, AiTaskError
from .config import load_config, global_config_path
from .tags import (
    build_task_description,
    title_with_id_prefix,
    description_with_first_line_title,
    check_category,
)
from . import parse  # dev8 #130 Phase 1 — description slicing


def _ensure_utf8_streams():
    """Windows cp950 console doesn't encode CJK / emoji — force utf-8 on BOTH
    stdout and stderr. stderr matters: every server error body (`{"detail":
    "任務不存在"}`) and every `✗ ...` line goes there, and cp950 +
    backslashreplace turned them into mojibake / `✗`.
    Idempotent: skip a stream already utf-8 (e.g. caller pre-wrapped)."""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        enc = getattr(stream, "encoding", "") or ""
        if enc.lower().replace("-", "") == "utf8":
            continue
        if hasattr(stream, "buffer"):
            setattr(sys, name, io.TextIOWrapper(
                stream.buffer, encoding="utf-8", errors="replace",
                line_buffering=True,
            ))


def _parse_tags(raw_list: list[str]) -> dict[str, str]:
    """`--tag "key: value"` flags → dict. Splits on first ':' only."""
    out: dict[str, str] = {}
    for raw in raw_list or []:
        if ":" not in raw:
            continue
        k, _, v = raw.partition(":")
        out[k.strip()] = v.strip()
    return out


def _require_modules(client: AiTaskClient, *needed: str) -> int:
    """dev8 #147 — defensive module check. Print clear error + return
    non-zero exit code if any required module isn't enabled. Caller
    short-circuits.

    Returns 0 if all present (proceed), 2 if any missing (CLI usage error).
    Silent if module discovery itself errors (some old projects without
    /api/projects/{id}/modules endpoint will just proceed and crash later —
    we don't want to add a NEW failure mode for legacy backends).
    """
    enabled = client.list_enabled_modules()
    if not enabled:
        return 0  # discovery failed, assume legacy backend — let it through
    missing = [m for m in needed if m not in enabled]
    if not missing:
        return 0
    print(f"✗ Module(s) not enabled in this project: {', '.join(missing)}",
          file=sys.stderr)
    print(f"  Enabled: {', '.join(enabled) or '(none)'}", file=sys.stderr)
    print(f"  This command needs: {', '.join(needed)}", file=sys.stderr)
    print(f"  → Enable in: Project Settings → 模組 → {missing[0]}",
          file=sys.stderr)
    return 2


def _read_stdin_text() -> str:
    """Read stdin as UTF-8, bypassing the text wrapper Python built for us.

    On Windows `sys.stdin` is `cp950` + `errors='surrogateescape'`, so piped
    UTF-8 bytes come back half-mojibake with lone surrogates embedded — which
    then blow up as `UnicodeEncodeError: surrogates not allowed` the moment
    `json.dumps(...).encode('utf-8')` tries to send them. Read the raw buffer
    instead and decode it ourselves (utf-8 first, locale as fallback for a
    genuinely non-UTF-8 pipe).
    """
    buf = getattr(sys.stdin, "buffer", None)
    if buf is None:  # already a text-only stream (tests / odd embeddings)
        return sys.stdin.read()
    raw = buf.read()
    for enc in ("utf-8", locale.getpreferredencoding(False)):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _read_body(arg: str | None) -> str:
    """If body arg starts with '@', treat as filename; '-' is stdin; else
    literal string."""
    if not arg:
        return ""
    if arg == "-":
        return _read_stdin_text()
    if arg.startswith("@"):
        return Path(arg[1:]).read_text(encoding="utf-8")
    return arg


# ── Subcommand handlers ────────────────────────────────────────────────────

def cmd_logout(client: AiTaskClient, args) -> int:
    """Invalidate current session on the server + remove token from config.

    Best-effort: server call is fire-and-forget (any failure ignored — the
    session may already be invalid). Always clears local token / config.
    """
    ok = client.logout()
    # Remove token from config file too (caller passes cfg via attribute)
    cfg = getattr(args, "_cfg", None)
    removed_path = None
    if cfg:
        try:
            removed_path = cfg.remove_token()
        except Exception as e:
            print(f"(warn: could not remove token from config: {e})", file=sys.stderr)
    print(f"✓ logged out{' (server session invalidated)' if ok else ' (local only)'}"
          + (f"; cleared token from {removed_path}" if removed_path else ""))
    return 0


def cmd_login(client: AiTaskClient, args) -> int:
    """Login + print session_id (token). Use to get a token for MCP config
    or other Bearer-auth scenarios. Reads username/password from --username/
    --password flags, or falls back to config.

    Output (machine-friendly): just the session_id on a line, so it's
    easy to capture in scripts (`TOKEN=$(aitask login)`).
    With --verbose: full login response including user info.
    """
    # Allow override via flags
    username = args.username or client._username
    password = args.password or client._password
    if not username or not password:
        print(
            "✗ aitask login needs username + password. Provide via:\n"
            "  --username / --password flags, or\n"
            "  AITASK_USERNAME / AITASK_PASSWORD env vars, or\n"
            "  username / password fields in aitask config JSON",
            file=sys.stderr,
        )
        return 1
    resp = client.login_explicit(username, password)
    sid = resp.get("session_id") if isinstance(resp, dict) else None
    if not sid:
        print("✗ login succeeded but server did not return session_id", file=sys.stderr)
        return 1
    if args.verbose:
        user = resp.get("user", {})
        print(f"✓ logged in as {user.get('name', '?')} (id={user.get('id', '?')})", file=sys.stderr)
        print(f"  role: {user.get('role', '?')}", file=sys.stderr)
        print(f"  session_id (use as Bearer token):")
    print(sid)
    if args.verbose:
        print(file=sys.stderr)
        print("Use in MCP config:", file=sys.stderr)
        print(f"  AITASK_TOKEN={sid}", file=sys.stderr)
    # --save: write back to config source file
    if args.save:
        cfg = getattr(args, "_cfg", None)
        if not cfg:
            print("(--save ignored: config object unavailable)", file=sys.stderr)
            return 0
        try:
            path = cfg.save_token(sid)
            print(f"✓ token saved to {path}", file=sys.stderr)
        except ValueError as e:
            print(f"(--save failed: {e})", file=sys.stderr)
            return 1
    return 0


def cmd_projects(client: AiTaskClient, args) -> int:
    """List available projects (discovery — use when you don't know which
    project_id to put in your config)."""
    projects = client.list_projects()
    if not projects:
        print("(no projects visible to this user)")
        return 0
    # Compact table: id / slug / name / description (truncated)
    print(f"{'ID':>4}  {'Slug':<20s}  {'Name':<30s}  Description")
    print(f"{'─' * 4}  {'─' * 20}  {'─' * 30}  {'─' * 30}")
    for p in projects:
        pid = p.get("id", "?")
        slug = (p.get("slug") or "")[:20]
        name = (p.get("name") or "")[:30]
        desc = (p.get("description") or "")[:60]
        print(f"{pid:>4}  {slug:<20s}  {name:<30s}  {desc}")
    print()
    print(f"Set `project_id` in your aitask config to one of the IDs above.")
    print(
        "(AI agents: don't self-select from this list and proceed — ask the "
        "user which project_id to use, even when improvising a workaround.)",
        file=sys.stderr,
    )
    return 0


# ── decision #114 Phase 1 — portability: setup / init / -p ─────────────────

def cmd_setup(args) -> int:
    """D3 — bootstrap the GLOBAL config (`~/.config/aitask/config.json`),
    once per machine. Prompts for base_url + credentials, logs in, and
    persists ONLY base_url + token (never the plaintext password — same
    spirit as `login --save`, decision #114 explicitly rejects storing
    credentials in the global file).

    Runs BEFORE `load_config` in main() — a fresh machine has no config yet,
    so this can't depend on one existing.
    """
    import getpass

    base_url = (
        args.base_url
        or input("aitask base_url [http://localhost:5173]: ").strip()
        or "http://localhost:5173"
    ).rstrip("/")
    username = args.username or input("username: ").strip()
    password = args.password or getpass.getpass("password: ")
    if not username or not password:
        print("✗ username + password required", file=sys.stderr)
        return 1

    client = AiTaskClient(base_url=base_url)
    try:
        resp = client.login_explicit(username, password)
    except AiTaskError as e:
        print(f"✗ login failed: {e}", file=sys.stderr)
        return 1
    sid = resp.get("session_id") if isinstance(resp, dict) else None
    if not sid:
        print("✗ login succeeded but server did not return session_id", file=sys.stderr)
        return 1

    path = global_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if path.is_file():
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    data["base_url"] = base_url
    data["token"] = sid
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    user = resp.get("user", {}) if isinstance(resp, dict) else {}
    print(f"✓ logged in as {user.get('name', username)} (id={user.get('id', '?')})")
    print(f"✓ global config saved: {path}")
    print(f"  base_url={base_url}")
    print()
    print("Next: cd into a project directory and run `aitask init -p <project>`.")
    return 0


def _resolve_project_ref(client: AiTaskClient, ref: str) -> Optional[int]:
    """D4 — resolve `<id|slug|name>` → project_id via the `projects` API.
    Prints a clear error + returns None on failure (not found / ambiguous
    name — caller should exit non-zero without proceeding)."""
    if ref.isdigit():
        return int(ref)
    projects = client.list_projects()
    slug_matches = [p for p in projects if p.get("slug") == ref]
    if len(slug_matches) == 1:
        return slug_matches[0]["id"]
    name_matches = [p for p in projects if p.get("name") == ref]
    if len(name_matches) == 1:
        return name_matches[0]["id"]
    if len(name_matches) > 1:
        print(f"✗ Ambiguous project name {ref!r} matches {len(name_matches)} projects: "
              + ", ".join(f"#{p['id']}({p.get('slug')})" for p in name_matches),
              file=sys.stderr)
        print("  Use slug or id instead of name.", file=sys.stderr)
        return None
    print(f"✗ No project found matching {ref!r} (tried id / slug / name)", file=sys.stderr)
    return None


def _ensure_gitignored(project_root: Path, rel_path: str) -> None:
    """Append `rel_path` to project_root/.gitignore if not already covered.
    Best-effort — silently skips if .gitignore isn't writable for some reason
    other than not existing (e.g. no permission is NOT worth failing init over)."""
    gi = project_root / ".gitignore"
    try:
        existing = gi.read_text(encoding="utf-8") if gi.is_file() else ""
    except Exception:
        return
    if rel_path in existing.splitlines():
        return
    sep = "" if (not existing or existing.endswith("\n")) else "\n"
    try:
        gi.write_text(existing + sep + rel_path + "\n", encoding="utf-8")
    except Exception:
        pass


def _init_claude_md_hint(project_root: Path) -> None:
    """Append a short pointer block to CLAUDE.md so the AI knows aitask is
    wired up + where to find THIS project's own conventions. Idempotent —
    skips if the marker is already present. Creates CLAUDE.md if missing."""
    marker = "<!-- aitask:init -->"
    claude_md = project_root / "CLAUDE.md"
    existing = claude_md.read_text(encoding="utf-8") if claude_md.is_file() else ""
    if marker in existing:
        return
    block = (
        f"\n{marker}\n"
        "## AiCodeTask (aitask)\n\n"
        "此專案已接上 AiCodeTask 開發追蹤。用 `/aitask`（或 `aitask` CLI）記錄開發\n"
        "進度 — session 開始先 `aitask list`、commit 完成後 `aitask log` / `aitask done`。\n"
        "通用子指令說明見可攜版 command；**這個專案自己的協作慣例（雙軌標籤詞彙、\n"
        "複雜度定義、decision 文件規範等）** 請寫進本檔案（或已寫在下方，若既有）。\n"
    )
    sep = "" if (not existing or existing.endswith("\n")) else "\n"
    claude_md.write_text(existing + sep + block, encoding="utf-8")
    print(f"  + CLAUDE.md hint appended ({claude_md})")


def _init_validate(client: AiTaskClient, project_id: int) -> None:
    """D8 — check tasks+documents modules enabled + expected custom fields
    exist. WARN only, never block init (缺欄位 aitask 本來就容錯，只寫
    markdown 軌 — 見 decision #114 D8 否決自動 seed 的理由)."""
    probe = AiTaskClient(
        base_url=client.base_url, project_id=project_id,
        tasks_module=client.tasks_module, docs_module=client.docs_module,
        token=client._token, username=client._username, password=client._password,
    )
    enabled = probe.list_enabled_modules()
    if enabled:
        missing_mod = [m for m in ("tasks", "documents") if m not in enabled]
        if missing_mod:
            print(f"  ⚠ module(s) not enabled: {', '.join(missing_mod)} "
                  f"— enable in Project Settings → 模組")
    else:
        print("  ⚠ could not verify enabled modules (older backend?) — proceeding anyway")
        return

    expected_task_fields = {"複雜度", "預估工時（小時）", "預估工時(小時)", "預估工時"}
    try:
        task_fields = {f["name"] for f in probe.get_task_fields()}
        if not (expected_task_fields & task_fields):
            print("  ⚠ tasks module missing 複雜度/預估工時 custom fields — "
                  "aitask will still work (writes to markdown body only, "
                  "dual-track convention). Add fields in Settings if you want "
                  "them structured.")
    except Exception:
        pass

    expected_doc_fields = {"類型"}
    try:
        doc_fields = {f["name"] for f in probe.get_doc_fields()}
        if not (expected_doc_fields & doc_fields):
            print("  ⚠ documents module missing 類型 custom field — "
                  "plan/decision/spike prefix still works, just no filterable field.")
    except Exception:
        pass


def cmd_init(client: AiTaskClient, args) -> int:
    """D3 — bootstrap a PROJECT config in the CURRENT directory:
    `./.claude/aitask-config.json`, containing only `project_id`
    (+ `project_slug` for deep links). base_url/token inherit from the
    global config via the D1 layered merge — that's the whole point.

    Target project comes from the shared `-p` flag (D4) resolved in main()
    onto `client.project_id` before this handler runs — `init` doesn't need
    its own resolution logic.
    """
    if client.project_id is None:
        print("✗ init needs a target project: pass -p <id|slug|name>", file=sys.stderr)
        return 2

    project_id = client.project_id
    try:
        projects = client.list_projects()
    except AiTaskError as e:
        print(f"✗ could not reach {client.base_url}: {e}", file=sys.stderr)
        return 1
    proj = next((p for p in projects if p.get("id") == project_id), None)
    if proj is None:
        print(f"✗ project id {project_id} not visible to this account "
              f"(run `aitask projects` to list what you can see)", file=sys.stderr)
        return 1

    project_root = Path.cwd()
    target_dir = project_root / ".claude"
    target_path = target_dir / "aitask-config.json"
    if target_path.is_file() and not args.force:
        print(f"✗ {target_path} already exists. Pass --force to overwrite.",
              file=sys.stderr)
        return 1

    target_dir.mkdir(parents=True, exist_ok=True)
    data = {"project_id": project_id}
    if proj.get("slug"):
        data["project_slug"] = proj["slug"]
    target_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _ensure_gitignored(project_root, ".claude/aitask-config.json")

    print(f"✓ project config written: {target_path}")
    print(f"  project #{project_id} — {proj.get('name', '')} (slug={proj.get('slug', '')})")

    _init_validate(client, project_id)
    _init_claude_md_hint(project_root)

    print()
    print("✓ init complete — try `aitask list` from this directory.")
    return 0


def cmd_list(client: AiTaskClient, args) -> int:
    if getattr(args, "doc", False):
        return _list_docs(client)
    items = client.list_tasks()
    opts = client.get_task_status_options()
    status_label = {o["id"]: o["label"] for o in opts.get("options", [])}
    # Statuses hidden from the default list: completed (is_done) + parked.
    # 'deferred' is a conventional "not now, maybe later" status — kept off the
    # active list like done. Reveal both with --include-done.
    hidden_ids = {o["id"] for o in opts.get("options", []) if o.get("is_done")}
    hidden_ids.add("deferred")

    groups: dict[str, list[dict]] = {}
    for it in items:
        s = it.get("status") or "unknown"
        groups.setdefault(s, []).append(it)

    # Stable display order — common statuses first, others alphabetic
    order_hint = ["in_progress", "pending", "review", "blocked"]
    sorted_keys = (
        [k for k in order_hint if k in groups]
        + sorted(k for k in groups if k not in order_hint and k not in hidden_ids)
    )
    if args.include_done:
        sorted_keys += sorted(k for k in groups if k in hidden_ids)

    for s in sorted_keys:
        label = status_label.get(s, s)
        print(f"\n## {label} ({len(groups[s])})")
        for it in groups[s]:
            print(f"  #{it['id']:>3} {it.get('title', '')}")
    return 0


def _list_docs(client: AiTaskClient) -> int:
    """`aitask list --doc` — documents grouped by status (#8).

    No hiding here, unlike tasks: `published` is `is_done` on the documents
    workflow, and published docs (decisions / memoirs) are exactly the ones
    you want to see. `--include-done` is therefore a no-op for docs.
    """
    items = client.list_docs(fields="minimal")
    opts = client.get_doc_status_options()
    options = opts.get("options", [])
    status_label = {o["id"]: o["label"] for o in options}
    order = {o["id"]: o.get("sort_order", 99) for o in options}

    groups: dict[str, list[dict]] = {}
    for it in items:
        groups.setdefault(it.get("status") or "unknown", []).append(it)

    for s in sorted(groups, key=lambda k: (order.get(k, 99), k)):
        print(f"\n## {status_label.get(s, s)} ({len(groups[s])})")
        for it in groups[s]:
            print(f"  #{it['id']:>3} {it.get('title', '')}")
    if not items:
        print("(no documents)")
    return 0


def cmd_new(client: AiTaskClient, args) -> int:
    body = _read_body(args.body)
    desc = build_task_description(
        complexity=args.complexity,
        hours=args.hours,
        tags=_parse_tags(args.tag),
        body=body,
    )

    # Step 1: POST create, get id
    result = client.create_task(args.title, desc)
    task_id = result["id"]

    # Step 2: PATCH title with #NN prefix + prepend title as first line of desc
    final_title = title_with_id_prefix(task_id, args.title)
    final_desc = description_with_first_line_title(final_title, desc)
    client.update_task(task_id, title=final_title, description=final_desc)

    # Step 3: structured fields (複雜度 / 預估工時)
    fields = client.get_task_fields()
    field_by_name = {f["name"]: f["id"] for f in fields}
    values = []
    if "複雜度" in field_by_name and args.complexity in {"S", "M", "L", "XL"}:
        values.append({"field_id": field_by_name["複雜度"], "value": args.complexity})
    hid = (
        field_by_name.get("預估工時（小時）")
        or field_by_name.get("預估工時(小時)")
        or field_by_name.get("預估工時")
    )
    if hid:
        import re
        m = re.match(r"~?\s*([\d.]+)", str(args.hours))
        if m:
            values.append({"field_id": hid, "value": m.group(1)})
    if values:
        client.set_task_field_values(task_id, values)

    print(f"✓ created task #{task_id}: {args.title}")
    warn = check_category(args.title)   # #198 — soft nudge on [area/type]
    if warn:
        print(warn)
    return 0


def _write_commit_dual_track(client: AiTaskClient, task_id: int,
                              commit_hash: str, note: str = "") -> None:
    """dev8 #142 Phase 3b-iv — write commit to BOTH the legacy commit_hash
    field (single value, last-wins, kept for back-compat) AND the new
    task_commits table (multi-value, structured). Best-effort on the table
    side — if task_commits endpoint isn't available (older server), silently
    skip and let the field-only write succeed.
    """
    # Legacy single-field write (idempotent, overwrite)
    client.set_task_commit_hash(task_id, commit_hash)
    # New multi-value table write (idempotent via UNIQUE)
    try:
        client.add_task_commit(task_id, commit_hash,
                               message_first_line=(note[:120] if note else ""))
    except Exception:
        # Don't fail the whole `log` / `done` flow if endpoint isn't ready
        pass


def cmd_done(client: AiTaskClient, args) -> int:
    client.mark_task_done(args.task_id, force=getattr(args, "force", False))
    if args.commit:
        _write_commit_dual_track(client, args.task_id, args.commit)
    print(f"✓ task #{args.task_id} marked done"
          + (f" [commit={args.commit}]" if args.commit else ""))
    return 0


def cmd_log(client: AiTaskClient, args) -> int:
    # dev9 #276 follow-up — note 支援 @file / - (stdin) / 字面字串，跟 --body
    # 一致（_read_body）。之前 log 只認 '-'、`@path` 被當字面文字 append（多行
    # 檢查表批次寫不進去的那個雷）。@file 不存在 → main() 接 FileNotFoundError
    # 印乾淨的 ✗，不再 silent 寫入路徑字串。
    note = _read_body(args.note)
    raw_note = note  # 解析後的純內容（給 commit message_first_line 用）
    # If --commit given, prefix the note for human-readable description
    if args.commit:
        note = f"commit {args.commit} — {note}" if note.strip() else f"commit {args.commit}"

    # --doc: append to a DOCUMENT's body_md. tasks/docs are separate id
    # namespaces; without this flag `log` always targeted a *task*, silently
    # mis-firing when the caller meant a same-numbered doc (the footgun).
    if getattr(args, "doc", False):
        client.append_to_doc_body(args.task_id, note)
        print(f"✓ logged to doc #{args.task_id}")
        return 0

    client.append_to_task_description(args.task_id, note)
    if args.commit:
        # Use raw note (resolved, minus the "commit XYZ — " prefix) as message_first_line
        _write_commit_dual_track(client, args.task_id, args.commit, note=raw_note)
    print(f"✓ logged to task #{args.task_id}"
          + (f" [commit={args.commit}]" if args.commit else ""))

    # Collision heads-up: if a document shares this id, the caller may have
    # meant the doc. Cheap probe; ignore lookup errors (no such doc).
    try:
        client.get_doc(args.task_id)
        print(f"  ⚠ #{args.task_id} 也是一份文件；剛寫進的是 task。"
              f"要寫文件用：aitask log {args.task_id} --doc …")
    except Exception:
        pass
    return 0


def cmd_edit(client: AiTaskClient, args) -> int:
    """#223 — REPLACE an existing task description / doc body_md (vs `log` which
    appends). Use for revising decision/plan/spike docs or fixing a body. Pair
    with `get` to read → edit → put back:
        aitask get 72 --doc > d.md  &&  aitask edit 72 --doc --body @d.md
    """
    body = _read_body(args.body) if args.body is not None else None
    if body is None and args.title is None:
        print("✗ 需要 --body 或 --title 至少一個", file=sys.stderr)
        return 2

    if getattr(args, "doc", False):
        client.get_doc(args.id)  # validate existence (raises if missing)
        fields = {}
        if body is not None:
            fields["body_md"] = body
        if args.title is not None:
            fields["title"] = args.title
        client.update_doc(args.id, **fields)
        what = "+".join(k for k in ("body_md" if body is not None else None,
                                    "title" if args.title is not None else None) if k)
        print(f"✓ edited doc #{args.id} [{what}]")
        return 0

    client.get_task(args.id)  # validate existence
    fields = {}
    if body is not None:
        fields["description"] = body
        # The task description carries conventions (first-line #NN title + AI
        # tags). `edit` replaces it wholesale — caller owns keeping those.
        print("  ⚠ 已整段取代 task description；first-line 標題 + AI 標籤請自行保留",
              file=sys.stderr)
    if args.title is not None:
        fields["title"] = args.title
    client.update_task(args.id, **fields)
    what = "+".join(k for k in ("description" if body is not None else None,
                                "title" if args.title is not None else None) if k)
    print(f"✓ edited task #{args.id} [{what}]")
    return 0


def cmd_rm(client: AiTaskClient, args) -> int:
    """#85 — delete a task / doc (--doc). Soft-delete (archive) by default;
    --force = permanent. Requires --yes (CLI is non-interactive, destructive)."""
    is_doc = getattr(args, "doc", False)
    getter = client.get_doc if is_doc else client.get_task
    kind = "doc" if is_doc else "task"
    item = getter(args.id)  # validate existence (raises if missing)
    title = (item.get("title") or "")[:70]
    if not args.yes:
        mode = "永久刪除" if args.force else "封存 (soft-delete)"
        print(f"將{mode} {kind} #{args.id}: {title}\n  加 --yes 確認執行"
              + ("（永久刪除再加 --force）" if not args.force else ""),
              file=sys.stderr)
        return 2
    (client.delete_doc if is_doc else client.delete_task)(args.id, force=args.force)
    print(f"✓ {'permanently deleted' if args.force else 'archived'} {kind} #{args.id}: {title}")
    return 0


def cmd_commits(client: AiTaskClient, args) -> int:
    """List all commits associated with a task (Phase 3b-iv)."""
    rc = _require_modules(client, "tasks")
    if rc:
        return rc
    if args.find:
        # Reverse lookup: hash → task(s)
        resp = client.find_task_by_commit(args.find)
        items = resp.get("items", [])
        if not items:
            print(f"(no task associated with commit {args.find})")
            return 0
        print(f"=== {len(items)} match(es) for {args.find!r} ===")
        for r in items:
            print(f"  task #{r['task_id']:>3}  {r['commit_hash']}  "
                  f"{(r.get('message_first_line') or '')[:60]}")
        return 0

    if args.all:
        resp = client.list_all_task_commits(since=args.since or "")
        items = resp.get("items", [])
        if not items:
            print("(no commits in project)")
            return 0
        # Group by task_id
        by_task: dict[int, list] = {}
        for r in items:
            by_task.setdefault(r["task_id"], []).append(r)
        for tid in sorted(by_task.keys()):
            rows = by_task[tid]
            print(f"task #{tid}  ({len(rows)} commits):")
            for r in rows:
                first = (r.get("message_first_line") or "")[:70]
                print(f"  - {r['commit_hash']}  [{r.get('committed_at', '')[:10]}]  {first}")
        print()
        print(f"({len(items)} commits across {len(by_task)} tasks)")
        return 0

    # Default: list for one task
    if args.task_id is None:
        print("✗ pass a task_id, or --all / --find <hash>", file=sys.stderr)
        return 2
    resp = client.list_task_commits(args.task_id)
    items = resp.get("items", [])
    if not items:
        print(f"(task #{args.task_id} has no commits)")
        return 0
    print(f"=== task #{args.task_id} — {len(items)} commit(s) ===")
    for r in items:
        first = (r.get("message_first_line") or "")[:70]
        date = (r.get("committed_at") or "")[:10]
        print(f"  {r['commit_hash']}  [{date}]  {first}")
    return 0


def cmd_update(client: AiTaskClient, args) -> int:
    force = getattr(args, "force", False)
    suffix = " [forced]" if force else ""

    # --doc: set a DOCUMENT's status. tasks/docs are separate id namespaces;
    # without this flag `update` always targeted a *task*, silently moving the
    # wrong item's status when the caller meant a same-numbered doc (the same
    # footgun `log --doc` exists for).
    if getattr(args, "doc", False):
        client.set_doc_status(args.task_id, args.status_id, override=force)
        print(f"✓ doc #{args.task_id} → status={args.status_id}{suffix}")
        return 0

    client.set_task_status(args.task_id, args.status_id, override=force)
    print(f"✓ task #{args.task_id} → status={args.status_id}{suffix}")

    # Collision heads-up: if a document shares this id, the caller may have
    # meant the doc. Cheap probe; ignore lookup errors (no such doc).
    try:
        client.get_doc(args.task_id)
        print(f"  ⚠ #{args.task_id} 也是一份文件；剛改的是 task 的 status。"
              f"要改文件用：aitask update {args.task_id} {args.status_id} --doc")
    except Exception:
        pass
    return 0


def cmd_doc_generic(client: AiTaskClient, doc_type: str,
                    title: str, body_arg: str | None,
                    prefix: str | None = None) -> int:
    body = _read_body(body_arg)
    doc_id = client.create_doc_typed(
        title, body, doc_type=doc_type, prefix=prefix,
    )
    print(f"✓ created {doc_type} doc #{doc_id}: {title}")
    return 0


def cmd_plan(client: AiTaskClient, args) -> int:
    return cmd_doc_generic(client, "plan", args.title, args.body, prefix="[plan]")


def cmd_spike(client: AiTaskClient, args) -> int:
    """Create a [spike] document (status=draft).

    dev8 #147 — exploration / vision-stage record. Use when you want to
    capture「想做 X、有 vision、還沒決定方法」— BEFORE plan stage. Doc
    body should include:
    - Background / why (the inspiration)
    - 候選方案 (multiple possible approaches, not decided)
    - Open questions (what need to figure out before plan)
    - 暫定不要做的部分

    [spike] graduates to [plan] when an approach is chosen, or stays as
    historical record of「why we explored this」if abandoned.
    """
    return cmd_doc_generic(client, "spike", args.title, args.body,
                           prefix="[spike]")


def cmd_decision(client: AiTaskClient, args) -> int:
    body = _read_body(args.body)
    if "否決方案" not in body:
        print(
            "✗ Refused: decision doc must contain 「否決方案」 section per CLAUDE.md.\n"
            "  Add a `### 否決方案` block explaining what alternatives were rejected and why.",
            file=sys.stderr,
        )
        return 2
    doc_id = client.create_doc_typed(
        args.title, body, doc_type="decision", prefix="[decision]",
    )
    print(f"✓ created decision doc #{doc_id}: {args.title}")
    return 0


def cmd_doc(client: AiTaskClient, args) -> int:
    # dev8 #147 follow-up — auto-prefix `[<type>]` to match convention
    # (plan / decision / spike already pass explicit prefix; generic `doc`
    # was missing). Past memoir doc creation lost the prefix because of
    # this gap. Now: `aitask doc memoir "X"` → `[memoir] X` → `#NN [memoir] X`.
    prefix = f"[{args.doc_type}]"
    return cmd_doc_generic(client, args.doc_type, args.title, args.body,
                           prefix=prefix)


# ── dev8 #130 Phase 1: token-efficient read helpers ────────────────────────

def _fetch_item(client: AiTaskClient, item_id: int, kind: str) -> dict:
    """Fetch task or doc by kind. kind: 'task' | 'doc'."""
    return client.get_doc(item_id) if kind == "doc" else client.get_task(item_id)


def _list_items(client: AiTaskClient, kind: str) -> list[dict]:
    return client.list_docs() if kind == "doc" else client.list_tasks()


def cmd_get(client: AiTaskClient, args) -> int:
    """Print structured slices of a task or doc — title + filtered sections.

    Default output is compact (summary + handoff + last 3 logs + refs +
    info tags). Flags narrow to specific slices for minimal token cost:
      --tail N    : only last N log entries
      --handoff   : only the current handoff state line
      --refs      : forward refs only (use `aitask refs` for reverse too)
      --tags      : info tags (key files / verify / lessons) only
      --full      : print whole raw description (current `client.get_task`)
    """
    kind = "doc" if args.doc else "task"
    item = _fetch_item(client, args.id, kind)
    desc = item.get("description") if kind == "task" else item.get("body_md")
    desc = desc or ""

    if args.full:
        print(item.get("title", ""))
        print()
        print(desc)
        return 0

    # dev8 #133 Phase 1.5 — `--digest` is the rule-based summary mode
    # (super-compact, ~80-150 tokens — see parse.build_digest)
    if args.digest:
        print(parse.build_digest(item, kind=kind))
        return 0

    title = item.get("title") or ""
    status = item.get("status") or ""
    print(f"{title}  [{status}]")

    # Slices — default prints all; flags narrow.
    want_all = not any([args.tail, args.handoff, args.refs, args.tags, args.summary])

    if want_all or args.summary:
        summary = parse.extract_summary(desc, max_chars=args.summary_chars)
        if summary:
            print()
            print(summary)

    if want_all or args.refs:
        refs = parse.extract_refs(desc)
        if refs:
            print()
            print("# Refs (forward)")
            for r in refs:
                ids_str = " ".join(f"#{x}" for x in r.ids)
                print(f"  {r.kind}: {ids_str}")

    if want_all or args.tags:
        tags = parse.extract_info_tags(desc)
        if tags:
            print()
            print("# Tags")
            for k, vs in tags.items():
                for v in vs:
                    print(f"  {k}: {v}")

    if want_all or args.handoff:
        h = parse.extract_handoff(desc)
        if h:
            print()
            print(f"# State: **{h.kind}：** {h.note}")

    # Log slice
    n = args.tail if args.tail else (3 if want_all else 0)
    if n > 0:
        logs = parse.extract_logs(desc)
        if logs:
            print()
            print(f"# Log (last {min(n, len(logs))} of {len(logs)})")
            for L in logs[-n:]:
                print(f"  [{L.date}] {L.body}")

    return 0


def cmd_checklist(client: AiTaskClient, args) -> int:
    """Parse a doc's markdown task-list checkboxes → compact checked/pending
    state. Lets the AI quickly read what the user has ticked off WITHOUT
    pulling the whole document into context (dev9 #277 回饋 — session 檢查表)."""
    import re
    item = _fetch_item(client, args.id, "doc")
    body = item.get("body_md") or ""
    title = item.get("title") or ""
    box = re.compile(r"^\s*[-*+]\s+\[([ xX])\]\s+(.*?)\s*$")
    head = re.compile(r"^#{1,6}\s+(.*\S)\s*$")
    items = []  # (checked, label, section)
    section = None
    for line in body.splitlines():
        h = head.match(line)
        if h:
            section = h.group(1).strip()
            continue
        m = box.match(line)
        if m:
            items.append((m.group(1).lower() == "x", m.group(2).strip(), section))
    total = len(items)
    done = sum(1 for c, _, _ in items if c)
    print(f"#{args.id} {title} — {done}/{total} checked"
          + (f"  ({total - done} pending)" if total else ""))
    shown = [it for it in items if not it[0]] if args.pending else items
    last = object()
    for checked, label, sec in shown:
        if sec != last:
            if sec:
                print(f"\n[{sec}]")
            last = sec
        print(f"  {'[x]' if checked else '[ ]'} {label}")
    return 0


def cmd_grep(client: AiTaskClient, args) -> int:
    """Search across task / doc descriptions. Prints id + title + snippet.

    dev8 #135 Phase 2 — uses server-side `/search` endpoint (LIKE filter +
    snippet generation). Server returns minimal projection (no full bodies),
    so this is token-efficient end-to-end.

    ⚠️ It is a **substring** match, not a regex — the server runs SQL LIKE.
    Backslash-escaped patterns match nothing; `[memoir]` works as-is. (#8:
    help text used to claim regex, and `-i` / `--ctx` were accepted but
    never read — both removed rather than left lying.)
    """
    pattern = args.pattern
    kinds: list[str] = []
    if args.kind == "all":
        kinds = ["task", "doc"]
    else:
        kinds = [args.kind]

    total_hits = 0
    for kind in kinds:
        if len(kinds) > 1:
            print(f"\n# {kind}s")
        try:
            if kind == "task":
                resp = client.search_tasks(pattern, limit=200)
            else:
                resp = client.search_docs(pattern, limit=200)
        except Exception as e:
            print(f"✗ {kind} search failed: {e}", file=sys.stderr)
            continue
        for it in resp.get("items", []):
            total_hits += 1
            print(f"  #{it['id']:>3}  {(it.get('title') or '')[:60]}")
            snip = it.get("snippet") or ""
            if snip:
                print(f"        {snip}")
    if total_hits == 0:
        print(f"(no matches for \"{pattern}\")")
    return 0


def cmd_refs(client: AiTaskClient, args) -> int:
    """Forward + reverse refs for a task / doc.

    Forward: bold-prefix refs in this item's description (`**關聯任務：** #N`).
    Reverse: server-side `/refs/{id}` endpoint scans both tasks + docs for
    word-boundary `#<id>` mentions (dev8 #135 Phase 2 — was client-side scan).
    """
    item_id = args.id
    kind = "doc" if args.doc else "task"

    # Forward — still client-side parsing (one item fetch is cheap)
    item = _fetch_item(client, item_id, kind)
    desc = (item.get("description") if kind == "task" else item.get("body_md")) or ""
    refs = parse.extract_refs(desc)
    print(f"# Forward refs from {kind} #{item_id}")
    if refs:
        for r in refs:
            ids = " ".join(f"#{x}" for x in r.ids)
            print(f"  {r.kind}: {ids}")
    else:
        print("  (none)")

    # Reverse — server-side endpoints (one call per module, word-boundary filtered)
    print()
    print(f"# Reverse refs (items mentioning #{item_id})")
    found_any = False
    for scan_kind in ("task", "doc"):
        try:
            if scan_kind == "task":
                resp = client.reverse_refs_tasks(item_id, limit=100)
            else:
                resp = client.reverse_refs_docs(item_id, limit=100)
        except Exception as e:
            print(f"  ({scan_kind} reverse-ref endpoint failed: {e})")
            continue
        for it in resp.get("items", []):
            if it.get("id") == item_id and scan_kind == kind:
                continue
            found_any = True
            label = f"{scan_kind} #{it['id']}"
            print(f"  {label:>14}  {(it.get('title') or '')[:50]}")
            print(f"  {'':>14}  {it.get('snippet') or ''}")
    if not found_any:
        print("  (none)")
    return 0


def cmd_graph(client: AiTaskClient, args) -> int:
    """Render a Mermaid `flowchart TD` of the project history graph (#138).

    Scope selection (pick one):
      --since YYYY-MM-DD       items created on/after date
      --from-id N [--to-id N]  id range (inclusive)
      --root <kind>:<id> [--depth N]  BFS from root (currently 1-hop only)

    Output goes to stdout as raw Mermaid syntax — paste into any doc with
    a markdown-it-mermaid plugin (this project's documents module qualifies)
    and the diagram renders inline.
    """
    # dev8 #147 — graph needs at least one of tasks/documents. With only
    # one, it degrades to single-kind graph (still useful). Both missing
    # is a hard fail.
    enabled = client.list_enabled_modules()
    if enabled:
        if "tasks" not in enabled and "documents" not in enabled:
            print("✗ Neither tasks nor documents module is enabled in this project.",
                  file=sys.stderr)
            print("  graph needs at least one. Enable in: Project Settings → 模組",
                  file=sys.stderr)
            return 2
        if "documents" not in enabled:
            print("# (documents not enabled — graph degraded to tasks-only; "
                  "no milestone/decision/plan nodes)", file=sys.stderr)
        if "tasks" not in enabled:
            print("# (tasks not enabled — graph degraded to docs-only; "
                  "no task nodes)", file=sys.stderr)
    # dev8 #138 perf — minimal mode skips assignee/watcher/field_values
    # hydration (N+1 query storm), ~10x faster on large lists. For graph
    # we only need title / description / body_md / status / created_at.
    # dev8 #146 — docs use full mode (need field_values for milestone flag).
    # Doc count is ~30 in dev8 not ~150 tasks, so the perf hit is ~0.5s
    # (acceptable for the milestone ⭐ payoff).
    all_tasks = client.list_tasks(fields="minimal")
    all_docs = client.list_docs()  # full — needs field_values

    def in_scope(item: dict) -> bool:
        if args.since:
            ts = (item.get("created_at") or "")[:10]
            if ts < args.since:
                return False
        if args.until:
            ts = (item.get("created_at") or "")[:10]
            if ts > args.until:
                return False
        if args.from_id and item.get("id", 0) < args.from_id:
            return False
        if args.to_id and item.get("id", 0) > args.to_id:
            return False
        return True

    tasks = [t for t in all_tasks if in_scope(t)]
    docs = [d for d in all_docs if in_scope(d)]

    # dev8 #138 perf — list endpoints already return description / body_md
    # inline (docs truncated to 8000 chars on the wire, plenty for ref
    # extraction since refs cluster at the top). Skip per-item refetches
    # — they were 70+ sequential API calls and made `graph` take ~5-10s.
    # Trade-off: log entries past the 8000-char mark in long docs not seen
    # for ref extraction, but refs there are extremely rare.
    full_tasks = tasks
    full_docs = docs
    extra_docs_pool = [d for d in all_docs if d["id"] not in {x["id"] for x in docs}]

    # dev8 #146 — pull structured item_relations table by default. Markdown
    # parse stays as fallback when --legacy or relations table empty/erroring.
    relations: list | None = None
    if not getattr(args, "legacy", False):
        try:
            relations = client.list_relations().get("items", [])
        except Exception as e:
            print(f"# (item_relations fetch failed, falling back to markdown: {e})",
                  file=sys.stderr)
            relations = None

    # dev8 #146 — milestone detection: map field name → id once, then annotate
    # docs with a synthetic `_milestone_flag` boolean. parse.build_graph reads
    # this via `_doc_has_milestone_flag`. Field id varies per project so
    # name-based lookup is required.
    try:
        doc_fields = client.get_doc_fields()
        milestone_fid = next(
            (str(f["id"]) for f in doc_fields if f.get("name") == "是否里程碑"),
            None,
        )
    except Exception:
        milestone_fid = None
    if milestone_fid:
        truthy = {True, 1, "1", "true", "True", "yes"}
        for d in full_docs:
            fv = d.get("field_values")
            if isinstance(fv, dict) and fv.get(milestone_fid) in truthy:
                d["_milestone_flag"] = True
        # Also annotate extra_docs_pool (anchor candidates)
        for d in extra_docs_pool:
            fv = d.get("field_values")
            if isinstance(fv, dict) and fv.get(milestone_fid) in truthy:
                d["_milestone_flag"] = True

    nodes, edges = parse.build_graph(
        full_tasks, full_docs,
        include_isolated=not args.drop_isolated,
        extra_docs_pool=extra_docs_pool,
        relations=relations,
    )

    if not nodes:
        print("(no items in scope)", file=sys.stderr)
        return 1

    if not args.no_fence:
        print("```mermaid")
    print(parse.render_mermaid(nodes, edges, direction=args.dir))
    if not args.no_fence:
        print("```")

    # Stats to stderr for the user (doesn't pollute the mermaid output)
    n_tasks = sum(1 for n in nodes if n.kind == "task")
    n_docs = sum(1 for n in nodes if n.kind == "doc")
    n_iso = sum(1 for n in nodes if n.in_count + n.out_count == 0)
    print(
        f"# {len(nodes)} nodes ({n_tasks} tasks, {n_docs} docs), "
        f"{len(edges)} edges, {n_iso} isolated",
        file=sys.stderr,
    )
    return 0


# dev8 #143 Phase 3b-v — Plan phase aggregate + task timeline ───────────────

def cmd_phases(client: AiTaskClient, args) -> int:
    """Parse `### Phase X` headings from a plan doc + aggregate task status +
    derive timespan from task_commits.committed_at (no user-filled dates)."""
    rc = _require_modules(client, "tasks", "documents")
    if rc:
        return rc
    doc_id = args.doc_id
    doc = client.get_doc(doc_id)
    body = doc.get("body_md") or ""
    title = (doc.get("title") or "")[:80]

    phases = parse.extract_phases(body)
    if not phases:
        print(f"(doc #{doc_id} {title} — no `### Phase X` headings or "
              f"`- Phase X` bullets found)")
        return 0

    # Find tasks related to this plan doc:
    #   - via item_relations (typed: source/target is doc N)
    #   - via weak ref scan if relations table empty (legacy)
    relations = client.list_relations().get("items", [])
    related_task_ids: set[int] = set()
    for r in relations:
        if r["source_kind"] == "doc" and r["source_id"] == doc_id and r["target_kind"] == "task":
            related_task_ids.add(r["target_id"])
        if r["target_kind"] == "doc" and r["target_id"] == doc_id and r["source_kind"] == "task":
            related_task_ids.add(r["source_id"])

    all_tasks = client.list_tasks()  # full mode — need description + status
    # Two pools:
    #   - "confirmed": tasks explicitly related via item_relations (high confidence)
    #   - "tentative": all OTHER tasks that mention a phase label (loose match —
    #     may include false positives if phase label clashes across plans)
    # Phase A/B/C 風 labels rarely conflict; numeric `Phase 1` could — caller
    # can see status_counts split to spot it.
    confirmed_tasks = [t for t in all_tasks if t["id"] in related_task_ids]
    tentative_tasks = [t for t in all_tasks if t["id"] not in related_task_ids]
    candidate_tasks = all_tasks  # combined for matching, split shown below

    all_commits = client.list_all_task_commits().get("items", [])

    print(f"=== doc #{doc_id} {title} ===")
    print(f"Phases declared: {', '.join(phases)}")
    print(f"Confirmed (explicit relation): {len(confirmed_tasks)}, "
          f"tentative (phase-mention only): scanning {len(tentative_tasks)}")
    print(f"Total project commits: {len(all_commits)}")
    print()

    # Render summary per phase
    for label in phases:
        # Confirmed pool first
        conf_sum = parse.aggregate_phase_summary(label, confirmed_tasks, all_commits)
        tent_sum = parse.aggregate_phase_summary(label, tentative_tasks, all_commits)
        # Combine
        all_task_ids = conf_sum.task_ids + tent_sum.task_ids
        if not all_task_ids:
            print(f"  Phase {label}: (no matching tasks)")
            continue
        sc: dict = {}
        for k, v in conf_sum.status_counts.items():
            sc[k] = sc.get(k, 0) + v
        for k, v in tent_sum.status_counts.items():
            sc[k] = sc.get(k, 0) + v
        done = sc.get("done", 0) + sc.get("completed", 0)
        total = sum(sc.values())
        pct = int(100 * done / total) if total else 0
        bar = "█" * (pct // 10) + "·" * (10 - pct // 10)
        # Min/max across both pools
        candidates_ts = [conf_sum.first_commit_at, tent_sum.first_commit_at]
        first_ts = min((t for t in candidates_ts if t), default=None)
        candidates_lt = [conf_sum.last_commit_at, tent_sum.last_commit_at]
        last_ts = max((t for t in candidates_lt if t), default=None)
        commits_total = conf_sum.commit_count + tent_sum.commit_count
        ts_str = ""
        if first_ts:
            ts_str = f"  {first_ts[:10]} → {(last_ts or first_ts)[:10]}"
        tag = f" ({len(conf_sum.task_ids)} confirmed)" if conf_sum.task_ids else " (all tentative)"
        print(f"  Phase {label:>5s}  [{bar}] {done}/{total} ({pct}%)"
              f"  {commits_total} commits{ts_str}{tag}")
        if args.verbose:
            for tid in conf_sum.task_ids:
                t = next((x for x in confirmed_tasks if x["id"] == tid), {})
                print(f"      #{tid:>3} ✓ ({t.get('status'):>10s})  "
                      f"{(t.get('title') or '')[:60]}")
            for tid in tent_sum.task_ids:
                t = next((x for x in tentative_tasks if x["id"] == tid), {})
                print(f"      #{tid:>3} ? ({t.get('status'):>10s})  "
                      f"{(t.get('title') or '')[:60]}")
    return 0


# dev8 #141 Phase 3b-ii — Milestone framework ──────────────────────────────
# Surface "this plan/decision is a big-deal checkpoint" via structured fields
# + auto-suggestion from relation_count + status. CLAUDE.md philosophy:
# user can't invent the milestone concept abstractly — framework suggests
# from data, user confirms / overrides.

MILESTONE_FIELDS = {"是否里程碑", "完成條件", "達成總結"}


def _get_milestone_field_ids(client: AiTaskClient) -> dict[str, int]:
    """Return {field_name: field_id} for the 3 milestone fields. KeyError
    if any are missing (user needs to run add_document_meta_fields.py)."""
    fields = client.get_doc_fields()
    out = {f["name"]: f["id"] for f in fields if f["name"] in MILESTONE_FIELDS}
    missing = MILESTONE_FIELDS - set(out)
    if missing:
        raise AiTaskError(
            f"Missing milestone fields: {', '.join(missing)}. "
            f"Run: tools/add_document_meta_fields.py --apply"
        )
    return out


def _doc_is_milestone(doc: dict, field_id: int) -> bool:
    """Read 是否里程碑 checkbox from doc.field_values dict
    ({field_id_str: value}). Falsey if field not set."""
    fv = doc.get("field_values") or {}
    if not isinstance(fv, dict):
        return False
    v = fv.get(str(field_id))
    return v in (True, 1, "1", "true", "True", "yes")


def _doc_field_value(doc: dict, field_id: int) -> str:
    """Read a single field value as string."""
    fv = doc.get("field_values") or {}
    if not isinstance(fv, dict):
        return ""
    return str(fv.get(str(field_id)) or "")


def cmd_milestone(client: AiTaskClient, args) -> int:
    """Dispatch milestone sub-action."""
    rc = _require_modules(client, "documents")
    if rc:
        return rc
    action = args.action
    if action == "list":
        return _milestone_list(client, args)
    if action == "suggest":
        return _milestone_suggest(client, args)
    if action == "mark":
        return _milestone_mark(client, args)
    if action == "unmark":
        return _milestone_unmark(client, args)
    if action == "status":
        return _milestone_status(client, args)
    print(f"✗ Unknown milestone action: {action}", file=sys.stderr)
    return 2


def _milestone_list(client: AiTaskClient, args) -> int:
    """List all docs marked is_milestone=true."""
    fids = _get_milestone_field_ids(client)
    docs = client.list_docs()  # need field_values, so 'full' mode
    is_ms_fid = fids["是否里程碑"]
    crit_fid = fids["完成條件"]
    marked = [d for d in docs if _doc_is_milestone(d, is_ms_fid)]
    if not marked:
        print("(no milestones marked yet — try `aitask milestone suggest`)")
        return 0
    print(f"=== {len(marked)} milestones ===\n")
    for d in marked:
        title = d.get("title") or ""
        status = d.get("status") or ""
        criteria = _doc_field_value(d, crit_fid).strip().split("\n")[0]
        print(f"  doc #{d['id']:>3}  {title[:60]}  ({status})")
        if criteria:
            print(f"           完成條件: {criteria[:80]}")
    return 0


def _milestone_suggest(client: AiTaskClient, args) -> int:
    """Find milestone candidates by relation count + doc_type heuristic.

    Logic: docs (type=plan or decision) with N+ incoming/relating rows
    in item_relations are likely milestones — they "anchor" multiple tasks.
    """
    threshold = args.threshold
    fids = _get_milestone_field_ids(client)
    is_ms_fid = fids["是否里程碑"]
    relations = client.list_relations().get("items", [])
    # Count by (target_kind, target_id) — touches on both sides
    incoming: dict[tuple[str, int], int] = {}
    for r in relations:
        key = (r["target_kind"], r["target_id"])
        incoming[key] = incoming.get(key, 0) + 1
        # Also count source side — for plans, source 「關聯任務 #N」 entries
        # mean plan points to tasks, so source-side count is also signal
        skey = (r["source_kind"], r["source_id"])
        incoming[skey] = incoming.get(skey, 0) + 1

    docs = client.list_docs()
    candidates: list[tuple[int, dict, int]] = []  # (count, doc, count)
    for d in docs:
        if _doc_is_milestone(d, is_ms_fid):
            continue  # already marked
        # detect type from title prefix (decision / plan)
        title = d.get("title") or ""
        is_plan_or_decision = (
            "[plan]" in title or "[decision]" in title
        )
        if not is_plan_or_decision:
            continue
        count = incoming.get(("doc", d["id"]), 0)
        if count >= threshold:
            candidates.append((count, d, count))

    candidates.sort(key=lambda x: -x[0])

    if not candidates:
        print(f"(no candidates — no plan/decision doc has ≥{threshold} relations)")
        return 0

    print(f"=== {len(candidates)} milestone candidates (relation count ≥ {threshold}) ===\n")
    # Show 1-2 already-marked examples (to teach vocabulary by example)
    already = [d for d in docs if _doc_is_milestone(d, is_ms_fid)]
    if already:
        print("Existing milestones (reference):")
        for d in already[:2]:
            cnt = incoming.get(("doc", d["id"]), 0)
            print(f"  ✓ #{d['id']:>3} {(d.get('title') or '')[:55]}  ({cnt} rels)")
        print()

    print("Candidates:")
    for cnt, d, _ in candidates:
        title = d.get("title") or ""
        status = d.get("status") or ""
        print(f"  #{d['id']:>3}  {title[:55]}  ({status}, {cnt} rels)")
    print()
    print("To mark: aitask milestone mark <doc_id> [--criteria \"...\"]")
    return 0


def _milestone_mark(client: AiTaskClient, args) -> int:
    """Set is_milestone=true on a doc, optionally with done_criteria."""
    doc_id = args.doc_id
    doc = client.get_doc(doc_id)  # validate existence + check current state
    fids = _get_milestone_field_ids(client)
    if _doc_is_milestone(doc, fids["是否里程碑"]):
        print(f"(doc #{doc_id} is already a milestone)")
        return 0

    values = [{"field_id": fids["是否里程碑"], "value": "true"}]
    if args.criteria:
        values.append({"field_id": fids["完成條件"], "value": args.criteria})
    client.set_doc_field_values(doc_id, values)
    title = doc.get("title") or ""
    print(f"✓ doc #{doc_id} marked as milestone: {title[:60]}")
    if args.criteria:
        print(f"  完成條件: {args.criteria[:80]}")
    else:
        print("  (no 完成條件 set — pass --criteria \"...\" to add)")
    return 0


def _milestone_unmark(client: AiTaskClient, args) -> int:
    """Set is_milestone=false. Keeps 完成條件 / 達成總結 untouched
    (data preserved in case user wants to re-mark)."""
    doc_id = args.doc_id
    doc = client.get_doc(doc_id)
    fids = _get_milestone_field_ids(client)
    if not _doc_is_milestone(doc, fids["是否里程碑"]):
        print(f"(doc #{doc_id} wasn't marked as milestone)")
        return 0

    client.set_doc_field_values(
        doc_id, [{"field_id": fids["是否里程碑"], "value": "false"}]
    )
    print(f"✓ doc #{doc_id} unmarked")
    return 0


def _milestone_status(client: AiTaskClient, args) -> int:
    """List milestones with referenced-task completion %."""
    fids = _get_milestone_field_ids(client)
    is_ms_fid = fids["是否里程碑"]
    docs = client.list_docs()
    marked = [d for d in docs if _doc_is_milestone(d, is_ms_fid)]
    if not marked:
        print("(no milestones marked)")
        return 0

    relations = client.list_relations().get("items", [])
    tasks = client.list_tasks()
    task_status = {t["id"]: (t.get("status") or "") for t in tasks}

    print(f"=== {len(marked)} milestones, completion status ===\n")
    for d in marked:
        # Find related task ids (either direction)
        related_task_ids: set[int] = set()
        for r in relations:
            if r["source_kind"] == "doc" and r["source_id"] == d["id"] and r["target_kind"] == "task":
                related_task_ids.add(r["target_id"])
            elif r["target_kind"] == "doc" and r["target_id"] == d["id"] and r["source_kind"] == "task":
                related_task_ids.add(r["source_id"])
        if not related_task_ids:
            print(f"  #{d['id']:>3}  {(d.get('title') or '')[:55]}  (0 related tasks)")
            continue
        done = sum(1 for tid in related_task_ids
                   if task_status.get(tid, "").lower() in ("done", "completed", "complete"))
        total = len(related_task_ids)
        pct = int(100 * done / total) if total else 0
        bar = "█" * (pct // 10) + "·" * (10 - pct // 10)
        title = (d.get("title") or "")[:50]
        print(f"  #{d['id']:>3}  {title:<50}  [{bar}] {done}/{total} ({pct}%)")
    return 0


# dev8 #144 — Viz pass: milestone-view ─────────────────────────────────────
# Render a milestone doc + its phases as a markdown report with multiple
# mermaid blocks (gantt phase timeline + task flowchart per phase).
# Auto-writes to a [viz] doc so user sees rendered mermaid without copy-paste.

def _safe_label(s: str, max_chars: int = 40) -> str:
    """Sanitize a string for safe inclusion in mermaid labels (avoid quote
    escape pain + truncate long titles)."""
    if not s:
        return ""
    s = s.replace('"', "'").replace("\n", " ").strip()
    # Strip leading #NN prefix + [type] tag
    s = re.sub(r"^#\d+\s+", "", s)
    s = re.sub(r"^\[[^\]]+\]\s*", "", s)
    if len(s) > max_chars:
        s = s[:max_chars].rstrip() + "…"
    return s


def _norm_status(s: str) -> str:
    """Canonicalize status names — done/in_progress/pending."""
    if not s:
        return "pending"
    n = s.lower().strip()
    if n in ("done", "complete", "completed"):
        return "done"
    if n in ("in_progress", "in progress", "doing", "active"):
        return "in_progress"
    return "pending"


def _build_milestone_view(
    doc: dict,
    phases: list,
    confirmed_tasks: list,
    tentative_tasks: list,
    all_commits: list,
) -> str:
    """Generate the full markdown report for a milestone doc."""
    doc_id = doc["id"]
    title = doc.get("title") or ""
    body = doc.get("body_md") or ""
    status = doc.get("status") or ""

    # Per-phase aggregation (pull from parse.aggregate_phase_summary)
    phase_summaries: list = []
    for label in phases:
        conf = parse.aggregate_phase_summary(label, confirmed_tasks, all_commits)
        tent = parse.aggregate_phase_summary(label, tentative_tasks, all_commits)
        phase_summaries.append((label, conf, tent))

    # Overall stats
    all_matched_ids: set = set()
    overall_status: dict = {}
    overall_first: str | None = None
    overall_last: str | None = None
    overall_commits = 0
    for label, conf, tent in phase_summaries:
        all_matched_ids.update(conf.task_ids)
        all_matched_ids.update(tent.task_ids)
        for k, v in conf.status_counts.items():
            overall_status[k] = overall_status.get(k, 0) + v
        for k, v in tent.status_counts.items():
            overall_status[k] = overall_status.get(k, 0) + v
        overall_commits += conf.commit_count + tent.commit_count
        for ts in (conf.first_commit_at, tent.first_commit_at):
            if ts and (overall_first is None or ts < overall_first):
                overall_first = ts
        for ts in (conf.last_commit_at, tent.last_commit_at):
            if ts and (overall_last is None or ts > overall_last):
                overall_last = ts

    total = sum(overall_status.values())
    done = overall_status.get("done", 0) + overall_status.get("completed", 0)
    pct = int(100 * done / total) if total else 0

    lines: list = []
    # ── Header ──────────────────────────────────────────────────────────────
    clean_title = re.sub(r"^#\d+\s+\[\w+\]\s*", "", title)
    lines.append(f"# 📊 Milestone Progress: #{doc_id} {clean_title}")
    lines.append("")
    lines.append(f"> Auto-generated by `aitask milestone-view {doc_id}`. "
                 f"Re-run to refresh.")
    lines.append("")
    meta_lines = [
        f"- **Source doc:** #{doc_id} ({status})",
        f"- **Phases declared:** {', '.join(phases) if phases else '(none)'}",
        f"- **Tasks tracked:** {len(all_matched_ids)}",
        f"- **Progress:** {done}/{total} ({pct}%)",
        f"- **Commits:** {overall_commits}",
    ]
    if overall_first:
        span_days = ""
        try:
            from datetime import datetime
            a = datetime.fromisoformat(overall_first.replace("Z", "+00:00").split("+")[0])
            b = datetime.fromisoformat((overall_last or overall_first).replace("Z", "+00:00").split("+")[0])
            span_days = f" ({(b - a).days + 1} days)"
        except Exception:
            pass
        meta_lines.append(f"- **Time span:** {overall_first[:10]} → "
                          f"{(overall_last or overall_first)[:10]}{span_days}")
    lines.extend(meta_lines)
    lines.append("")

    # ── Phase Gantt ─────────────────────────────────────────────────────────
    lines.append("## Phase Timeline")
    lines.append("")
    lines.append("```mermaid")
    # dev8 #144 follow-up — gantt density config. User feedback: 字太小、難看。
    # barHeight + fontSize 拉大、leftPadding 留空間給 section label、
    # useMaxWidth=false 讓圖照原始 size 渲染 (容器再 horizontal scroll)
    lines.append("%%{init: {'gantt': {"
                 "'barHeight': 32, 'fontSize': 14, 'sectionFontSize': 16, "
                 "'leftPadding': 140, 'topPadding': 40, 'gridLineStartPadding': 40, "
                 "'useMaxWidth': false}}}%%")
    lines.append("gantt")
    lines.append("    title Phase Timeline")
    lines.append("    dateFormat YYYY-MM-DD")
    lines.append("    axisFormat %m-%d")
    for label, conf, tent in phase_summaries:
        clean_label = re.sub(r"[^\w-]", "_", label)
        all_task_ids = conf.task_ids + tent.task_ids
        if not all_task_ids:
            lines.append(f"    section Phase {label} (no tasks)")
            continue
        # Determine date range for the phase — min across BOTH pools,
        # max across BOTH pools (use min/max not `or`, both can have data)
        firsts = [ts for ts in (conf.first_commit_at, tent.first_commit_at) if ts]
        lasts = [ts for ts in (conf.last_commit_at, tent.last_commit_at) if ts]
        first = (min(firsts)[:10] if firsts else "")
        last = (max(lasts)[:10] if lasts else first)
        if not first:
            lines.append(f"    section Phase {label} (no commits)")
            continue
        sc: dict = {}
        for k, v in conf.status_counts.items():
            sc[k] = sc.get(k, 0) + v
        for k, v in tent.status_counts.items():
            sc[k] = sc.get(k, 0) + v
        p_done = sc.get("done", 0) + sc.get("completed", 0)
        p_total = sum(sc.values())
        gantt_class = "done" if p_done == p_total else "active"
        if first == last:
            range_str = f"{first}, 1d"
        else:
            range_str = f"{first}, {last}"
        lines.append(f"    section Phase {label}")
        lines.append(f"    {p_done}/{p_total} tasks done :{gantt_class}, "
                     f"p_{clean_label}, {range_str}")
    lines.append("```")
    lines.append("")

    # ── Task Flowchart per Phase ───────────────────────────────────────────
    lines.append("## Tasks by Phase")
    lines.append("")
    lines.append("```mermaid")
    lines.append("%%{init: {'flowchart': {"
                 "'nodeSpacing': 30, 'rankSpacing': 50, "
                 "'useMaxWidth': false}, 'themeVariables': {'fontSize': '15px'}}}%%")
    lines.append("flowchart LR")
    lines.append("    classDef done fill:#d1fae5,stroke:#16a34a")
    lines.append("    classDef in_progress fill:#fef3c7,stroke:#d97706")
    lines.append("    classDef pending fill:#f9fafb,stroke:#6b7280")
    lines.append("    classDef tentative stroke-dasharray:3,fill:#faf5ff")
    # Mermaid disallows the same node id appearing in multiple subgraphs —
    # if a task matches multiple phases (e.g. #63 mentions both Phase A AND
    # Phase B), namespace each occurrence: tN_pX. Visually it shows "the
    # same task in two phases" which is the truth (task spans both).
    for label, conf, tent in phase_summaries:
        all_task_ids = conf.task_ids + tent.task_ids
        if not all_task_ids:
            continue
        clean_label = re.sub(r"[^\w-]", "_", label)
        lines.append(f"    subgraph p_{clean_label}[\"Phase {label}\"]")
        for tid in conf.task_ids:
            t = next((x for x in confirmed_tasks if x["id"] == tid), {})
            st = _norm_status(t.get("status", ""))
            label_text = _safe_label(t.get("title", ""))
            lines.append(f"        t{tid}_{clean_label}"
                         f"[\"#{tid} {label_text}\"]:::{st}")
        for tid in tent.task_ids:
            t = next((x for x in tentative_tasks if x["id"] == tid), {})
            label_text = _safe_label(t.get("title", ""))
            lines.append(f"        t{tid}_{clean_label}"
                         f"[\"#{tid} {label_text} ?\"]:::tentative")
        lines.append("    end")
    lines.append("```")
    lines.append("")

    # ── Footer with verbose task list ──────────────────────────────────────
    lines.append("## Task Detail")
    lines.append("")
    for label, conf, tent in phase_summaries:
        if not (conf.task_ids or tent.task_ids):
            continue
        # Phase heading carries info: progress + dates (visual density)
        # dev8 #144 follow-up — user feedback「Phase 字要粗體或 header 背景色」
        # 用 enriched heading 把 progress + timespan 塞進標題行、自帶視覺密度
        sc: dict = {}
        for k, v in conf.status_counts.items():
            sc[k] = sc.get(k, 0) + v
        for k, v in tent.status_counts.items():
            sc[k] = sc.get(k, 0) + v
        p_done = sc.get("done", 0) + sc.get("completed", 0)
        p_total = sum(sc.values())
        firsts = [ts for ts in (conf.first_commit_at, tent.first_commit_at) if ts]
        lasts = [ts for ts in (conf.last_commit_at, tent.last_commit_at) if ts]
        first = (min(firsts)[:10] if firsts else "")
        last = (max(lasts)[:10] if lasts else first)
        time_str = ""
        if first:
            time_str = f" · {first}" + (f" → {last}" if last and last != first else "")
        prog_emoji = "✅" if p_done == p_total and p_total > 0 else "🚧"
        lines.append(f"### {prog_emoji} Phase {label} — {p_done}/{p_total} done{time_str}")
        lines.append("")
        for tid in conf.task_ids:
            t = next((x for x in confirmed_tasks if x["id"] == tid), {})
            st = t.get("status") or "?"
            tt = (t.get("title") or "").replace("|", "│")[:80]
            lines.append(f"- ✓ #{tid} ({st}) — {tt}")
        for tid in tent.task_ids:
            t = next((x for x in tentative_tasks if x["id"] == tid), {})
            st = t.get("status") or "?"
            tt = (t.get("title") or "").replace("|", "│")[:80]
            lines.append(f"- ? #{tid} ({st}, tentative) — {tt}")
        lines.append("")

    return "\n".join(lines)


def _find_or_create_viz_doc(client: AiTaskClient, milestone_doc_id: int,
                            milestone_title: str, body: str) -> int:
    """Find existing `[viz] #<id>` doc for this milestone, update it.
    If not found, create new. Returns the viz doc id."""
    # Search for existing
    docs = client.list_docs(fields="minimal")
    # Stable title format: "[viz] #<milestone_id> <clean title>"
    clean = re.sub(r"^#\d+\s+\[\w+\]\s*", "", milestone_title)
    viz_title_marker = f"[viz] #{milestone_doc_id}"
    existing = next((d for d in docs
                     if viz_title_marker in (d.get("title") or "")), None)
    if existing:
        client.update_doc(existing["id"], body_md=body)
        return existing["id"]
    # Create new
    viz_title_raw = f"{viz_title_marker} {clean[:60]}"
    doc_id = client.create_doc_typed(
        viz_title_raw, body, doc_type="note", prefix=None,
    )
    return doc_id


def cmd_milestone_view(client: AiTaskClient, args) -> int:
    """Generate + render milestone progress as markdown with mermaid blocks.

    Auto-writes to a [viz] doc so user sees the rendered mermaid immediately
    in the documents UI (idempotent — same milestone re-runs update in-place).
    """
    rc = _require_modules(client, "tasks", "documents")
    if rc:
        return rc
    doc_id = args.doc_id
    doc = client.get_doc(doc_id)
    body = doc.get("body_md") or ""
    title = doc.get("title") or ""

    phases = parse.extract_phases(body)
    if not phases:
        print(f"✗ doc #{doc_id} has no phase declarations — "
              f"add `### Phase X` headings or `- Phase X` bullets first")
        return 2

    relations = client.list_relations().get("items", [])
    related_task_ids: set = set()
    for r in relations:
        if r["source_kind"] == "doc" and r["source_id"] == doc_id and r["target_kind"] == "task":
            related_task_ids.add(r["target_id"])
        if r["target_kind"] == "doc" and r["target_id"] == doc_id and r["source_kind"] == "task":
            related_task_ids.add(r["source_id"])

    all_tasks = client.list_tasks()
    confirmed_tasks = [t for t in all_tasks if t["id"] in related_task_ids]
    tentative_tasks = [t for t in all_tasks if t["id"] not in related_task_ids]
    all_commits = client.list_all_task_commits().get("items", [])

    markdown = _build_milestone_view(
        doc, phases, confirmed_tasks, tentative_tasks, all_commits
    )

    if args.stdout:
        print(markdown)
        return 0

    # Default: write/update [viz] doc
    viz_id = _find_or_create_viz_doc(client, doc_id, title, markdown)
    # Try to print a deep link (config base_url not always set)
    cfg = getattr(args, "_cfg", None)
    base = getattr(cfg, "base_url", "http://127.0.0.1:5173") if cfg else "http://127.0.0.1:5173"
    slug = getattr(cfg, "project_slug", "aicodetask") if cfg else "aicodetask"
    print(f"✓ wrote viz to doc #{viz_id}")
    print(f"  {base}/#project/{slug}/documents?open={viz_id}")
    return 0


def cmd_recent(client: AiTaskClient, args) -> int:
    """Items with most recent activity (server-side sort by updated_at).
    dev8 #135 Phase 2 — was client-side fetch+sort, now server endpoint
    returns minimal projection with last-log snippet already extracted."""
    n = args.n
    kinds = ["task"] if not args.docs else ["doc"]
    if args.all:
        kinds = ["task", "doc"]

    rows: list[tuple[str, str, dict]] = []
    for kind in kinds:
        try:
            if kind == "task":
                resp = client.recent_tasks(limit=n if not args.all else n * 2,
                                           since=args.since or "")
            else:
                resp = client.recent_docs(limit=n if not args.all else n * 2,
                                          since=args.since or "")
        except Exception as e:
            print(f"({kind} recent failed: {e})")
            continue
        for it in resp.get("items", []):
            rows.append((it.get("updated_at") or "", kind, it))

    rows.sort(key=lambda r: r[0], reverse=True)
    rows = rows[:n]
    if not rows:
        print("(no recent activity)")
        return 0

    for upd, kind, it in rows:
        title = it.get("title") or ""
        status = it.get("status") or ""
        last_date = it.get("last_log_date") or upd[:10] or "——"
        print(f"[{last_date}]  {kind} #{it['id']:>3} {title[:60]}  ({status})")
        snip = it.get("last_log_snippet") or ""
        if snip:
            print(f"             > {snip[:120]}")
    return 0


# ── Entrypoint ─────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aitask",
        description="Cross-AI-tool CLI for AiCodeTask dev workflow",
    )
    p.add_argument("--config", help="path to aitask config JSON")
    sub = p.add_subparsers(dest="cmd")

    # setup — decision #114 D3: once-per-machine global config bootstrap
    pst = sub.add_parser("setup",
        help="bootstrap the GLOBAL config (~/.config/aitask/config.json), once per machine")
    pst.add_argument("--base-url", dest="base_url", default=None,
                     help="skip the prompt (e.g. http://localhost:5173)")
    pst.add_argument("--username", default=None, help="skip the prompt")
    pst.add_argument("--password", default=None, help="skip the prompt (else hidden input)")
    pst.set_defaults(func=None)  # handled specially in main() — no config/client needed yet

    # init — decision #114 D3: once-per-project config (just project_id)
    pin = sub.add_parser("init",
        help="bootstrap THIS project's config (./.claude/aitask-config.json) — "
             "pick the project with -p <id|slug|name>")
    pin.add_argument("--force", action="store_true",
                     help="overwrite existing ./.claude/aitask-config.json")
    pin.set_defaults(func=cmd_init)

    # login (get session_id token for MCP / Bearer auth)
    pli = sub.add_parser("login", help="login and print session_id (token for MCP / Bearer auth)")
    pli.add_argument("--username", help="username (overrides config / env)")
    pli.add_argument("--password", help="password (overrides config / env)")
    pli.add_argument("--verbose", "-v", action="store_true",
                     help="also print user info + usage hint to stderr")
    pli.add_argument("--save", action="store_true",
                     help="persist token back to config source file "
                          "(plaintext — same risk as storing password)")
    pli.set_defaults(func=cmd_login)

    # logout (invalidate server session + remove token from config)
    plo = sub.add_parser("logout", help="invalidate server session + clear token from config")
    plo.set_defaults(func=cmd_logout)

    # projects (discovery — works without project_id in config)
    pp = sub.add_parser("projects", help="list available projects (for finding project_id)")
    pp.set_defaults(func=cmd_projects)

    # list
    pl = sub.add_parser("list", help="list pending tasks grouped by status")
    pl.add_argument("--include-done", action="store_true",
                    help="also show done/closed tasks (tasks only)")
    pl.add_argument("--doc", action="store_true",
                    help="list documents instead of tasks (all statuses)")
    pl.set_defaults(func=cmd_list)

    # new
    pn = sub.add_parser("new", help="create a new task")
    pn.add_argument("title")
    pn.add_argument("--complexity", choices=["S", "M", "L", "XL"], default="M")
    pn.add_argument("--hours", default="3", help="estimated hours (e.g. '3' or '6-8')")
    pn.add_argument("--tag", action="append", default=[],
                    help="dual-track tag, format 'key: value'; repeatable")
    pn.add_argument("--body", default="",
                    help="task body (or @filename / '-' for stdin)")
    pn.set_defaults(func=cmd_new)

    # done
    pd = sub.add_parser("done", help="mark a task as done")
    pd.add_argument("task_id", type=int)
    pd.add_argument("--commit", help="associated commit hash (writes to commit_hash field)")
    pd.add_argument("--force", action="store_true",
                    help="skip workflow (Owner/admin only); default follows the "
                         "workflow — works for any member when it's disabled")
    pd.set_defaults(func=cmd_done)

    # log
    plg = sub.add_parser("log", help="append timestamped note to a task (or a doc with --doc)")
    plg.add_argument("task_id", type=int, help="task id (or doc id when --doc given)")
    plg.add_argument("note", help="note text, '@file' to read from a file, or '-' for stdin")
    plg.add_argument("--commit", help="associated commit hash (auto-prefixes note + writes to commit_hash field)")
    plg.add_argument("--doc", action="store_true",
                     help="append to a DOCUMENT's body_md instead of a task (tasks/docs are separate id namespaces)")
    plg.set_defaults(func=cmd_log)

    # edit — #223: replace existing body (vs log = append)
    ped = sub.add_parser("edit",
                         help="replace an existing task description / doc body (--doc)")
    ped.add_argument("id", type=int, help="task id (or doc id when --doc given)")
    ped.add_argument("--doc", action="store_true",
                     help="edit a DOCUMENT body_md instead of a task description")
    ped.add_argument("--body", default=None,
                     help="new body (or @filename / '-' for stdin)")
    ped.add_argument("--title", default=None, help="also rename title")
    ped.set_defaults(func=cmd_edit)

    # rm — #85: delete task/doc (soft by default, --force permanent)
    prm = sub.add_parser("rm", help="delete a task / doc (--doc); soft by default, --force permanent")
    prm.add_argument("id", type=int, help="task id (or doc id when --doc given)")
    prm.add_argument("--doc", action="store_true", help="delete a DOCUMENT instead of a task")
    prm.add_argument("--force", action="store_true", help="permanent delete (default = archive)")
    prm.add_argument("--yes", action="store_true", help="confirm (required; CLI is non-interactive)")
    prm.set_defaults(func=cmd_rm)

    # update
    pu = sub.add_parser("update", help="set task status (or a doc's with --doc); follows workflow, --force to skip")
    pu.add_argument("task_id", type=int, help="task id (or doc id when --doc given)")
    pu.add_argument("status_id",
                    help="status id — tasks: 'in_progress' / 'done'; docs: 'draft' / 'published'")
    pu.add_argument("--doc", action="store_true",
                    help="set a DOCUMENT's status instead of a task (tasks/docs are separate id namespaces)")
    pu.add_argument("--force", action="store_true",
                    help="skip workflow (Owner/admin only); default follows the "
                         "workflow — works for any member when it's disabled")
    pu.set_defaults(func=cmd_update)

    # plan
    pp = sub.add_parser("plan", help="create a [plan] document (status=draft)")
    pp.add_argument("title")
    pp.add_argument("--body", default="",
                    help="body markdown (or @filename / '-' for stdin)")
    pp.set_defaults(func=cmd_plan)

    # spike (dev8 #147) — exploration / vision-stage doc
    psp = sub.add_parser("spike",
        help="create a [spike] document (exploration, before plan stage)")
    psp.add_argument("title")
    psp.add_argument("--body", default="",
                    help="body markdown (or @filename / '-' for stdin)")
    psp.set_defaults(func=cmd_spike)

    # decision
    pdc = sub.add_parser("decision", help="create a [decision] document (status=published)")
    pdc.add_argument("title")
    pdc.add_argument("--body", default="",
                    help="body markdown — MUST contain '否決方案' section")
    pdc.set_defaults(func=cmd_decision)

    # doc (generic)
    pdg = sub.add_parser("doc", help="create a generic document (specify type)")
    pdg.add_argument("doc_type", help="e.g. 'spec', 'note', 'memo'")
    pdg.add_argument("title")
    pdg.add_argument("--body", default="",
                    help="body markdown (or @filename / '-' for stdin)")
    pdg.set_defaults(func=cmd_doc)

    # dev8 #130 Phase 1 — token-efficient read commands ───────────────────
    # get — structured slice of a task/doc (vs full description blob)
    pg = sub.add_parser("get",
        help="get task/doc slice (handoff/refs/tags/tail logs/summary)")
    pg.add_argument("id", type=int)
    pg.add_argument("--doc", action="store_true",
                    help="fetch a document (default: task)")
    pg.add_argument("--tail", type=int, default=0,
                    help="show last N log entries (default 3 in compact)")
    pg.add_argument("--handoff", action="store_true",
                    help="show only the current handoff state line")
    pg.add_argument("--refs", action="store_true",
                    help="show only forward refs (see `aitask refs <id>` for reverse)")
    pg.add_argument("--tags", action="store_true",
                    help="show only info tags (關鍵檔案 / 驗證 / 踩雷紀錄 / 下次留意)")
    pg.add_argument("--summary", action="store_true",
                    help="show only the summary paragraph")
    pg.add_argument("--summary-chars", type=int, default=240,
                    help="max chars for summary truncation (default 240)")
    pg.add_argument("--full", action="store_true",
                    help="print whole raw description (== current get_task)")
    pg.add_argument("--digest", action="store_true",
                    help="rule-based super-compact summary (~80-150 tokens)")
    pg.set_defaults(func=cmd_get)

    # checklist — parse a doc's markdown checkboxes → compact checked state
    pck = sub.add_parser("checklist",
        help="parse a doc's markdown - [ ] checkboxes → compact checked/pending state")
    pck.add_argument("id", type=int, help="document id (a note with - [ ] items)")
    pck.add_argument("--pending", action="store_true",
                     help="only show unchecked items (what's left to test)")
    pck.set_defaults(func=cmd_checklist)

    # grep — full-text search across descriptions
    pgr = sub.add_parser("grep",
        help="substring search over task/doc bodies, print id + snippet")
    pgr.add_argument("pattern",
                    help="literal substring (server-side LIKE — NOT a regex)")
    pgr.add_argument("--kind", choices=["task", "doc", "all"], default="all",
                    help="which module to search (default: all)")
    pgr.set_defaults(func=cmd_grep)

    # refs — forward + reverse refs for an id
    prf = sub.add_parser("refs",
        help="show forward + reverse refs (who mentions #N)")
    prf.add_argument("id", type=int)
    prf.add_argument("--doc", action="store_true",
                    help="treat id as a document id (default: task)")
    prf.set_defaults(func=cmd_refs)

    # graph — Mermaid flowchart of tasks + docs + their refs (#138)
    pgh = sub.add_parser("graph",
        help="render Mermaid flowchart of task/doc refs (paste into a markdown doc to view)")
    pgh.add_argument("--since", default="",
                     help="YYYY-MM-DD lower bound on created_at (e.g. 2026-05-23 for dev8)")
    pgh.add_argument("--until", default="",
                     help="YYYY-MM-DD upper bound on created_at")
    pgh.add_argument("--from-id", type=int, default=0,
                     help="lower id bound (inclusive)")
    pgh.add_argument("--to-id", type=int, default=0,
                     help="upper id bound (inclusive)")
    pgh.add_argument("--dir", default="TD", choices=["TD", "LR", "BT", "RL"],
                     help="flowchart direction (default TD)")
    pgh.add_argument("--drop-isolated", action="store_true",
                     help="omit isolated nodes (default: keep + red border warning)")
    pgh.add_argument("--no-fence", action="store_true",
                     help="don't wrap output in ```mermaid ... ``` fence")
    pgh.add_argument("--legacy", action="store_true",
                     help="use markdown bold-prefix parse instead of "
                          "item_relations table (Phase 3b-i)")
    pgh.set_defaults(func=cmd_graph)

    # milestone-view — dev8 #144 viz pass ──────────────────────────────────
    pmv = sub.add_parser("milestone-view",
        help="generate phase gantt + task flowchart for a milestone doc, "
             "auto-write to [viz] doc")
    pmv.add_argument("doc_id", type=int)
    pmv.add_argument("--stdout", action="store_true",
                     help="print markdown to stdout instead of writing to doc")
    pmv.set_defaults(func=cmd_milestone_view)

    # phases — dev8 #143 Phase 3b-v ───────────────────────────────────────
    pph = sub.add_parser("phases",
        help="aggregate plan-doc phase status + timeline (Phase 3b-v)")
    pph.add_argument("doc_id", type=int, help="plan doc id")
    pph.add_argument("-v", "--verbose", action="store_true",
                     help="list each task per phase")
    pph.set_defaults(func=cmd_phases)

    # commits — dev8 #142 Phase 3b-iv ─────────────────────────────────────
    pcm = sub.add_parser("commits",
        help="list commits for task / all / find by hash (Phase 3b-iv)")
    pcm.add_argument("task_id", type=int, nargs="?", default=None,
                    help="task id (omit if using --all or --find)")
    pcm.add_argument("--all", action="store_true",
                    help="list all commits across all tasks, grouped")
    pcm.add_argument("--find", default="",
                    help="reverse lookup: find task(s) for this commit hash")
    pcm.add_argument("--since", default="",
                    help="(with --all) only commits since YYYY-MM-DD")
    pcm.set_defaults(func=cmd_commits)

    # milestone — dev8 #141 Phase 3b-ii ───────────────────────────────────
    pms = sub.add_parser("milestone",
        help="manage milestone docs (list/suggest/mark/unmark/status)")
    pms_sub = pms.add_subparsers(dest="action")
    pms_sub.add_parser("list", help="list all docs marked as milestones")
    pms_sug = pms_sub.add_parser("suggest",
        help="find candidate milestones by relation count")
    pms_sug.add_argument("--threshold", type=int, default=3,
                         help="min relation count to suggest (default 3)")
    pms_mk = pms_sub.add_parser("mark", help="mark a doc as milestone")
    pms_mk.add_argument("doc_id", type=int)
    pms_mk.add_argument("--criteria", default="",
                        help="完成條件 — what must be true to call this done")
    pms_un = pms_sub.add_parser("unmark", help="unmark milestone (keeps fields)")
    pms_un.add_argument("doc_id", type=int)
    pms_sub.add_parser("status",
        help="list milestones with referenced-task completion %")
    pms.set_defaults(func=cmd_milestone)

    # recent — recently-touched items digest
    prc = sub.add_parser("recent",
        help="items with most recent log activity (session-start digest)")
    prc.add_argument("-n", type=int, default=10, help="how many items (default 10)")
    prc.add_argument("--docs", action="store_true",
                    help="docs instead of tasks")
    prc.add_argument("--all", action="store_true",
                    help="both tasks AND docs")
    prc.add_argument("--since", default="",
                    help="only items with log date >= this (YYYY-MM-DD)")
    prc.set_defaults(func=cmd_recent)

    # decision #114 D4 — global `-p <id|slug|name>` project override, added
    # to every subcommand uniformly via retrofit loop (cleaner than repeating
    # `parents=[...]` at every `sub.add_parser(...)` call site above).
    # `setup` is excluded — it has no project concept (machine-wide bootstrap).
    for name, subp in sub.choices.items():
        if name == "setup":
            continue
        subp.add_argument("-p", "--project", default=None,
                          help="target project by id|slug|name for this "
                               "invocation (overrides config project_id, "
                               "doesn't persist; required for `init`)")

    return p


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_streams()
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "cmd", None) is None:
        parser.print_help()
        return 0

    # `setup` bootstraps the global config from nothing — must run BEFORE
    # load_config, which would raise FileNotFoundError on a fresh machine
    # with no config anywhere yet.
    if args.cmd == "setup":
        try:
            return cmd_setup(args)
        except KeyboardInterrupt:
            print("\n(interrupted)", file=sys.stderr)
            return 130

    try:
        cfg = load_config(args.config)
        # D4 — resolve `-p` (if given) against a project-less probe client,
        # then point cfg at the resolved project for this invocation only
        # (never persisted — that's what `init` is for).
        if getattr(args, "project", None):
            probe = AiTaskClient(
                base_url=cfg.base_url, token=cfg.token,
                username=cfg.username, password=cfg.password,
            )
            resolved = _resolve_project_ref(probe, args.project)
            if resolved is None:
                return 1
            cfg.project_id = resolved
        client = AiTaskClient.from_config(cfg)
        # Expose cfg to subcommand handlers that need to mutate config file
        # (`login --save` / `logout`). Subcommands that don't touch config
        # simply ignore it. Stashed on args (parser-namespaced) rather than
        # adding a parameter to every handler signature.
        args._cfg = cfg
        return args.func(client, args) or 0
    except AiTaskError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n(interrupted)", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
