# Claude Code × aitask

兩條路徑可選 — 看你想要 AI 用什麼方式呼叫 aitask。

兩條路徑都假設你已經照 [`../getting-started.md`](../getting-started.md)
裝好 aitask（`pip install -e .` 進你選定的 Python 環境）。下面的
`<python>` 都代表**那個環境**的 `python.exe`（一般裝法在 PATH 上直接打
`python` 就是；獨立 venv/embedded Python 要用完整路徑，例如
`C:/path/to/your/venv/Scripts/python.exe`）。

## 路徑 A：MCP server（推薦、tool-call 體驗最好）

1. 安裝 mcp 依賴 — **裝進 command 會指向的那個 Python**：
   ```bash
   "<python>" -m pip install -e ".[mcp]"
   ```
2. Claude Code MCP config（`.claude/settings.json` 或 user-global）。`command` 用
   **絕對路徑 Python + `-m aitask.mcp`**（別用 `aitask-mcp` 裸名 — .exe 落在
   該 Python 的 `Scripts/`（Windows）/ `bin/`（Unix），多半不在 PATH，會
   command not found）：
   ```json
   {
     "mcpServers": {
       "aitask": {
         "command": "<python>",
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
   帳密路徑在 token 失效時自動重登（server 常重啟也不斷）。或省 env，讓它
   走 config 分層合併（全域 `~/.config/aitask/config.json` + 專案
   `.claude/aitask-config.json`，見 getting-started）。也可改 `AITASK_TOKEN`
   （session_id）但 server 重啟會失效、要重拿 — 開發期建議帳密。
3. 重啟 Claude Code → AI 應看到 `aitask_list / aitask_new_task / ...` tools。

## 路徑 B：slash command（CLI-based）

兩種寫法可並存：

- **User 層可攜版**（`~/.claude/commands/aitask.md`）——跨所有專案生效，
  只講通用 aitask CLI 用法。
- **專案層厚版**（`<project>/.claude/commands/aitask.md`）——覆蓋前者，放
  該專案自己的協作慣例（雙軌標籤詞彙、複雜度定義等）。`aitask init` 不會
  自動幫你建這份，需要的話手動仿照現有專案的版本寫。

User 在 chat 打 `/aitask list` 觸發 skill、AI 用 Bash 執行 `aitask` CLI
（已在 PATH 上的話直接打指令名即可，不用再自己拼 Python 呼叫）。

兩條路徑可並存 — 通常 **MCP 適合 AI tool-call**、**slash command 適合
user explicit 觸發**。

## 合作 conventions 從哪來

Claude Code 自動載入專案根的 `CLAUDE.md`。如果該專案已經寫了完整的
aitask conventions（dual-track 標籤、L1/L2/L3 觸發層、下次接手、否決方案
精神等），Claude Code 不用再額外灌。

如果**沒有** — `aitask init` 會在 `CLAUDE.md` 補一段基本提示；更完整的
conventions 可以 paste `src/aitask/AICONTEXT.md`（package data，跟著
`pip install` 一起裝進去）的內容到該專案的 `CLAUDE.md` 或 user system prompt。
AICONTEXT.md 是 tool-agnostic 的、跨 AI 工具通用版。

## 驗證

```bash
# CLI 驗證
aitask list

# MCP server 驗證（需 mcp package 裝好）— 用絕對路徑 Python + -m
"<python>" -m aitask.mcp
# 應該 hang 在 stdio transport（沒 traceback 就對了，^C 退出）
```

MCP server 啟動失敗？通常是 `mcp` package 沒裝 — script 會印 install 指令。
