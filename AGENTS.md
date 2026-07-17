# aitask — AI 開發夥伴規則（Codex / AGENTS.md 相容工具）

這裡是 **aitask 獨立 pip 套件**的原始碼：AiCodeTask 開發追蹤器的 CLI +
Python client lib + MCP server。

這份檔案**刻意很薄** —— 它只是指路牌，不放任何慣例內容。慣例只有一份來源，
多一份副本就會 drift。

## 1. 協作慣例 → `src/aitask/AICONTEXT.md`

**開工前先讀一遍。** 雙軌標籤詞彙、L1/L2/L3 觸發時機、decision 必含「否決方案」、
提案 → 確認 → 執行（M+ 改動）、方案 A/B/C、誠實規則、commit 切細、「下次接手」
收尾、chat 回覆一律 deep link…全部在那裡。

它是 tool-agnostic 版，同時服務 Claude Code / Antigravity / Cursor / Codex。

> 走 MCP 的話不用自己開檔：呼叫 **`aitask_get_conventions`** 就會拿到同一份全文。
> 接線方式見 [`docs/integrations/codex.md`](docs/integrations/codex.md)。

## 2. 本 repo 專屬 context → `CLAUDE.md`

`CLAUDE.md` 的**檔名**是 Claude Code 專屬，但**內容是 tool-agnostic 的 repo
context**（三個 consumer 各是什麼、雙 editable 安裝的影響面、改 `mcp.py` 會波及
哪些 MCP client、測試 / 驗證怎麼跑）。動手改這個 repo 前讀它，不要另外複製一份。

## 3. 開發追蹤 → AiCodeTask project **AiTaskMCP (#51)**

Session 開始 `aitask list`；commit 後 `aitask log <id>` / `aitask done <id>`；
重大決策 `aitask decision`；發現 sub-task `aitask new`。

Chat 回覆提及 task / doc **一律 deep link**（裸 `#NN` 會被 linkify 成 404）：

- Task：`[#NN](http://localhost:5173/#project/aitaskmcp/tasks?open=NN)`
- Doc：`[#NN](http://localhost:5173/#project/aitaskmcp/documents?open=NN)`
