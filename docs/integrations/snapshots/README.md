# 各 AI 工具端的實際設定快照（retire 時封存）

這裡是 aitask 停止維護前，從各 AI 工具**實際載入的位置**複製回來的檔案。
目的是保存「當時每個 client 到底看到什麼」，不是安裝說明 —— 怎麼接線看上一層的
per-tool recipe（[`../README.md`](../README.md)）。

**這些是快照、不會再更新。** 慣例的 single source of truth 仍是
[`src/aitask/AICONTEXT.md`](../../../src/aitask/AICONTEXT.md)；MCP 工具定義的
來源是 [`src/aitask/mcp.py`](../../../src/aitask/mcp.py) 的 tool docstring。

| 路徑 | 來源 | 取得時間 |
|---|---|---|
| `claude-code/commands/aitask.md` | Claude Code 的 `/aitask` slash command（原位置 `%USERPROFILE%\.claude\commands\aitask.md`） | 2026-08-29 |
| `gemini-antigravity/server-instructions.md` | `aitask-mcp` server 的 `instructions`（`FastMCP("aitask", instructions=...)`），Antigravity 開場看到的那段 | 2026-09-10 |
| `gemini-antigravity/mcp-tools/*.json` | Antigravity 快取的 MCP 工具定義（name / description / JSON schema），一個工具一個檔 | 2026-09-10 |

備註：

- Antigravity 原本存了兩份（`antigravity/` 與 `antigravity-ide/`，後者 2026-09-16），
  內容逐位元組相同，只留一份。
- `mcp-tools/*.json` 是由 `mcp.py` 自動產生的，跟同時期的 `mcp.py` 有出入時以
  `mcp.py` 為準。
- `claude-code/commands/aitask.md` 開頭寫的 AICONTEXT.md 路徑（`C:\_App\...`）是
  當時的機器路徑，照原樣保留。
