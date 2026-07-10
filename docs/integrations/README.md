# aitask × AI 工具整合

本目錄收集 per-tool 接 aitask 的 recipe。原則：**最小可動的範例、不寫得
太完整**（系統還在邊開發邊用、避免文件 churn）。

> 還沒裝過 aitask / 還沒 `setup`+`init` 過？先看
> [`../getting-started.md`](../getting-started.md)——這裡的 recipe 都假設
> 那步已經做完。

## 兩件事要分清

接 aitask 進 AI 工具有**兩層**：

1. **工具存取權** — MCP server 或 CLI binary 讓 AI 可以「呼叫」aitask
   功能（list / new / done / log / ...）。這層是 per-tool recipe 教的。
2. **合作 conventions** — 「什麼時候該呼叫」「dual-track 標籤怎麼寫」「下次
   接手 convention」「否決方案精神」等。**單裝 MCP / CLI 不會自動帶這層**。

合作 conventions 的 source of truth：[`../../AICONTEXT.md`](../../AICONTEXT.md)。
是 tool-agnostic 的 markdown、paste 進任何 AI 工具的 system prompt /
workspace rules 就能用。

當前 recipe：

| 工具 | Recipe | 路徑 |
|---|---|---|
| Claude Code | MCP server + skill 雙路徑 | [claude-code.md](claude-code.md) |
| Gemini Antigravity | MCP server | [gemini-antigravity.md](gemini-antigravity.md) |

## 通用 system-prompt fragment（短版）

完整 conventions 在 [`../../AICONTEXT.md`](../../AICONTEXT.md)。下面只是
**最短的工具用法 cheat sheet**，給只想要 quick reference 的場景：

````markdown
你的開發進度可以記錄到 AiCodeTask 系統。可用工具：

**MCP（推薦，原生支援的工具用）**：
- `aitask_get_conventions` — **session 開始先 call 這個**、拿合作 conventions
- `aitask_list_projects` — 列可看到的 projects（找 project_id 用、setup 階段）
- `aitask_list` — 列 pending tasks（session 開始用）
- `aitask_new_task(title, body, complexity, hours, tags)` — 開新 task
- `aitask_log(task_id, note)` — commit 後追加 note
- `aitask_mark_done(task_id)` — 標 done
- `aitask_create_plan(title, body)` — plan mode 完存 [plan] doc
- `aitask_create_decision(title, body)` — 重大決策存 [decision] doc
  （body 必須含「否決方案」section）

**CLI（fallback，shell-only 工具用）**：
```bash
aitask projects                          # 列 projects 找 project_id
aitask list
aitask new "title" --complexity M --hours 3 --tag "key: value" --body "..."
aitask done <id>
aitask log <id> "<note>"
aitask plan "title" --body @file.md
aitask decision "title" --body @file.md
```

何時用：session 開始 / commit 完成後 / plan 結束 / 重大決策。
不要為純 read / typo fix / spike 開記錄。Token 預算：每 session ≤ 6 次。

詳細 convention 見專案的 CLAUDE.md。
````

加新工具時：複製格式、寫一份 `<tool-name>.md`。**不要寫得超過必要長度** —
通常 30-50 行就夠（介紹 + config + 驗證指令）。
