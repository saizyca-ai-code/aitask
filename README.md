# aitask — cross-AI-tool dev workflow integration

CLI + Python library + MCP server for interacting with **AiCodeTask**, a
dev-process tracker web app (config points at whichever instance + project
you're recording to — see [Setup](#setup-recommended--decision-114-phase-1)).
Designed so the same dev workflow can be invoked from **any AI coding
agent** — Claude Code, Gemini Antigravity, Cursor, Aider, ChatGPT…, across
**any number of projects and machines**, from this one standalone package.

## Why

Originally `aitask` lived inside the MSSceneDetect repo as
`.claude/commands/aitask.md` — a Claude Code-specific skill made of markdown
+ inline Python snippets executed via the Bash tool, plus a `tools/aitask/`
subfolder for the actual client code. That worked for Claude Code, in that
one repo, but didn't transfer to other agents or other projects. This
package extracted the same logic into a standalone, pip-installable repo:

1. **`aitask` CLI** — any agent that can run shell commands uses it
2. **`aitask` Python library** — for direct integration
3. **`aitask-mcp` MCP server** — for agents with native MCP support

All three reuse the same `AiTaskClient` underneath. Auth is via Bearer
token (returned by `POST /api/auth/login` as `session_id`) — no cookie
juggling needed.

## Install

```bash
# from this repo (editable — picks up local edits without reinstalling)
pip install -e .

# from PyPI (future)
# pip install aitask
```

Zero runtime deps (pure stdlib `urllib` + `json`). MCP server is
optional and requires `pip install aitask[mcp]`.

## Setup (recommended — decision #114 Phase 1)

Full walkthrough with expected output + troubleshooting:
[`docs/getting-started.md`](docs/getting-started.md). Short version — two
commands, once each:

```bash
aitask setup                         # once per MACHINE — prompts for
                                      # base_url + username + password,
                                      # logs in, saves base_url + token to
                                      # ~/.config/aitask/config.json
                                      # (never the plaintext password)

cd my-project
aitask init -p <id|slug|name>        # once per PROJECT — writes
                                      # ./.claude/aitask-config.json with
                                      # just project_id (+ slug), gitignores
                                      # it, and appends a CLAUDE.md hint.
                                      # base_url/token inherit from setup.
```

`-p <id|slug|name>` also works as a one-off override on ANY subcommand
(doesn't persist) — e.g. `aitask list -p shot_refer` targets a different
project for just that call without touching config.

## Config

Config is a **layered merge**, not pick-first (decision #114 D1 — the old
pick-first order let a global config fully shadow a project's `project_id`,
so per-project config could never be reached):

1. `~/.config/aitask/config.json` (XDG global — base_url + token, shared
   across every project on this machine; `aitask setup` writes this)
2. project layer — exactly ONE of these wins (not merged with each other),
   **overriding** matching keys from the global layer:
   - `--config /path/to/config.json` CLI flag
   - `AITASK_CONFIG` env var
   - walk up from cwd for `.claude/aitask-config.json` (`aitask init` writes
     this, typically just `project_id`)
3. env var overrides — always win on top of both file layers

Config schema:

```json
{
  "base_url":      "http://localhost:5173",
  "project_id":    34,
  "tasks_module":  "tasks",
  "docs_module":   "documents",
  "username":      "claude",
  "password":      "..."
}
```

**Don't know your project_id?** Run `aitask projects` to list all
projects visible to your user — works with just base_url + auth, no
project_id needed.

Or use `token` (preferred for programmatic callers — get it from
`POST /api/auth/login` response body):

```json
{
  "base_url":   "http://localhost:5173",
  "project_id": 34,
  "token":      "abc123-uuid-..."
}
```

Env-var overrides apply on top: `AITASK_BASE_URL`, `AITASK_PROJECT_ID`,
`AITASK_TOKEN`, `AITASK_USERNAME`, `AITASK_PASSWORD` (most useful for MCP
server / CI — token preferred; username+password fallback auto-logs in
on first request).

## CLI

### Setup / discovery

```bash
aitask setup                         # once per machine (see above)
aitask init -p aicodetask            # once per project (see above)
aitask init -p aicodetask --force    # re-run / overwrite existing project config
```

### Auth / discovery

```bash
aitask login --username claude --password ... -v
                                     # → session_id for MCP / Bearer auth
aitask login --save                  # persist token back into config
aitask logout                        # invalidate server session + clear token
aitask projects                      # discover project_id
```

### Tasks — create / progress / close

```bash
aitask list                          # pending tasks by status
aitask list --include-done           # include closed
aitask list --doc                    # documents grouped by status
aitask new "[shots] foo bar" --complexity M --hours 3 \
    --tag "關鍵檔案: app/foo.py:12-30" \
    --tag "關聯任務: #51" \
    --body @notes.md                 # body from file
aitask log 42 "commit abc123 — sub 2 完成"   # append timestamped note
aitask log 50 "補充結論..." --doc    # append to a DOC body (separate id space!)
aitask done 42                       # mark done (follows workflow)
aitask update 42 in_progress         # set status (follows workflow)
aitask update 19 published --doc     # set a DOC's status (separate id space!)
aitask done 42 --force               # skip workflow — Owner/admin only
```

> **狀態變更與 workflow（重要）**
> `done` / `update` 預設**遵循該專案模組的 workflow**（`override=False`）：
> - workflow **關閉** → 任何成員都能自由設任意狀態（dev-task 自由狀態的常見用法）。
> - workflow **開啟** → 你的角色需要被授予對應的 transition（或角色 `is_owner`）。
>
> 加 `--force` 才會跳過 workflow（`override=True`），而那是 **Owner / `admin.override_project` 限定**
> 能力（MSSceneDetect decision #57 §6 — 強制改狀態不可一般授予）。所以把 aitask
> 當「自由設狀態」的工具時，建議**關閉該專案 tasks/documents 模組的 workflow**，
> 自動化使用者用一般成員身分即可，不需 Owner 或 `--force`。
> （早期版本 client 預設 `override=True`，§6 上線後會對非 Owner 使用者 403 —
> 已於 #227 改為預設 `override=False` + `--force` 顯式 opt-in。）

### Documents — plan / decision / spike / generic

```bash
aitask plan "dev9 主軸" --body @plan.md          # [plan]   status=draft
aitask decision "Shot ID 重設計" --body @decision.md
                                     # [decision] status=published
                                     # body MUST contain "否決方案"
aitask spike "歷程檢視器" --body @spike.md       # [spike]  exploration, pre-plan
aitask doc spec "API contract" --body @spec.md   # generic, type = first arg
```

### Read — token-efficient slices (dev8 #130)

```bash
aitask get 42                        # structured slice (handoff/refs/tags/tail logs)
aitask get 42 --handoff              # only the 下次接手 line
aitask get 42 --digest               # ~80-150 token rule-based summary
aitask get 19 --doc --full           # whole raw doc body
aitask grep "shot_code"                      # substring search over task+doc bodies
aitask grep "shot_code" --kind doc           # docs only (default: all)
aitask refs 32                       # forward + reverse refs (who mentions #32)
aitask recent -n 10                  # most recently-logged items (session start)
aitask recent --all --since 2026-06-01
```

### Relations / milestones / viz (dev8 Phase 3b, #138–#146)

```bash
aitask commits 45                    # all commits for a task (multi-commit table)
aitask commits --find abc123         # reverse: which task(s) own this hash
aitask graph --since 2026-05-23      # Mermaid flowchart of refs + milestones ⭐
aitask phases 19                     # plan-doc phase status + commit-derived timeline
aitask milestone suggest             # candidate milestones by relation count
aitask milestone mark 19 --criteria "..."    # mark doc as milestone
aitask milestone status              # milestones + referenced-task completion %
aitask milestone-view 19             # write [viz] doc: gantt + flowchart for a milestone
```

Run `aitask <cmd> -h` for the full flag set on any subcommand.

## Python library

```python
from aitask import load_config, AiTaskClient, build_task_description

cfg = load_config()
client = AiTaskClient.from_config(cfg)

# List
for task in client.list_tasks():
    print(task["id"], task["title"])

# Create with dual-track tags
desc = build_task_description(
    complexity="M", hours="3",
    tags={"關聯任務": "#51 #52", "關鍵檔案": "app/foo.py:12-30"},
    body="### 應做\n- step 1\n- step 2",
)
result = client.create_task("[shots] foo", desc)
print("created", result["id"])

# Done
client.mark_task_done(result["id"])
```

## MCP server (Phase C)

```bash
# install into the SAME Python the MCP command will point at
"<python>" -m pip install -e ".[mcp]"
"<python>" -m aitask.mcp   # speaks stdio MCP protocol (Ctrl+C to exit)
```

Plug into an MCP-aware tool. Use the **absolute Python path + `-m aitask.mcp`** —
NOT the bare `aitask-mcp` name (its .exe lands in `<python>/Scripts/`, usually not
on PATH → "command not found" / no tools appear):

```json
{
  "mcpServers": {
    "aitask": {
      "command": "C:/path/to/your/python/python.exe",
      "args": ["-m", "aitask.mcp"],
      "env": {
        "AITASK_BASE_URL": "http://localhost:5173",
        "AITASK_PROJECT_ID": "34",
        "AITASK_USERNAME": "claude",
        "AITASK_PASSWORD": "your-password"
      }
    }
  }
}
```

Username/password auto re-logs-in when the session expires (survives server
restarts); `AITASK_TOKEN` is an alternative but dies on restart. Tools exposed:
list / get / grep / recent / new_task / log / mark_done / set_status / edit / rm /
create_plan / create_decision / create_spike / create_doc / list_projects /
get_conventions. See `docs/integrations/` for per-tool setup recipes.

## 加 / 改子指令時 — parity checklist（維護者必讀，dev9 #262）

aitask 的同一組能力散在四處，**加或改一個指令時四處都要同步**，否則某些 AI 工具
看不到（CLAUDE.md 反覆踩過的「半數工具看不到」雷）：

1. **CLI** — `src/aitask/cli.py`：`cmd_xxx` handler + `sub.add_parser(...)`
2. **MCP** — `src/aitask/mcp.py`：對應 `@server.tool()`（給走 MCP 的 Antigravity/Cursor）
3. **Skill** — `.claude/commands/aitask.md`：「子指令一覽」表 + 範例（給 Claude Code）
4. **Docs** — 本 `README.md` 工具清單 + 必要時 `src/aitask/AICONTEXT.md`（conventions 面）

**例外（decision #114 Phase 1）**：`setup` / `init` **不進 MCP**。兩者是互動式
bootstrap（setup 要密碼 hidden input、init 要在還沒有 config 的情況下先跑起來）——
MCP server 啟動本身就要求 config 已存在（走 env var），概念上矛盾。這兩個指令的
定位是「裝好工具的第一步」，用 CLI 跑就好。

底層共用 `client.py`（加一個 `client.xxx()` 方法、CLI 跟 MCP 都呼叫它，邏輯不重複）。
改完跑一次「`_build_server()` 列 tools」+ CLI `--help` 對照，確認兩邊指令集一致。

## 合作 conventions（給 AI 工具的 system prompt）

裝好 CLI / MCP 後 AI 還需要知道**怎麼用**aitask 才能配合你的工作流（什麼時
候呼叫、dual-track 標籤怎麼填、「下次接手」conventions 等）。

`src/aitask/AICONTEXT.md` 是 tool-agnostic 的合作 conventions、paste 進任何 AI
工具的 system prompt / workspace rules 就能用。它是 **package data**（跟著
`pip install` 一起裝進去，所以 `aitask_get_conventions` 在 wheel 安裝下也讀得
到）—— 別把它移回 repo 根目錄，那樣只有 editable 安裝能用。

Claude Code 走 `CLAUDE.md` 自動載入、Codex 走 `AGENTS.md`，兩者都只是薄指標指
向這份。別的工具（Antigravity / Cursor / ...）走 MCP `aitask_get_conventions`
自動拿，或手動 paste。
