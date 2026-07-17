# Codex × aitask

假設你已照 [`../getting-started.md`](../getting-started.md) 裝好 aitask。下面
`<python>` 代表**裝了 aitask 的那個 Python**（獨立 venv 要用完整路徑，例如
`C:/path/to/venv/Scripts/python.exe`）。

## 路徑 A：MCP server（推薦）

1. 安裝 mcp 依賴 —— 裝進 `command` 會指向的那個 Python：
   ```bash
   "<python>" -m pip install -e ".[mcp]"
   ```
2. Codex 的 MCP config 在 `~/.codex/config.toml`。用**絕對路徑 Python +
   `-m aitask.mcp`**（別用 `aitask-mcp` 裸名 —— .exe 落在該 Python 的
   `Scripts/` / `bin/`，多半不在 PATH）：
   ```toml
   [mcp_servers.aitask]
   command = "<python>"
   args = ["-m", "aitask.mcp"]

   [mcp_servers.aitask.env]
   AITASK_BASE_URL = "http://localhost:5173"
   AITASK_PROJECT_ID = "<your-project-id>"
   AITASK_USERNAME = "<your-username>"
   AITASK_PASSWORD = "<your-password>"
   ```
   > ⚠️ `<...>` 是佔位符，**不是預設值**。`project_id` 用 `aitask projects` 查、
   > 或直接問 user 要記到哪個專案 —— 寫錯不會報錯，只會安靜地把資料寫進錯的
   > 專案（AICONTEXT.md「專案識別安全」那節）。username 用你自己的帳號，不是
   > 「codex」這種照抄文件的名字。

   帳密路徑在 token 失效時**自動重登**（server 重啟也不斷）。或省掉 env、走
   config 分層合併（全域 `~/.config/aitask/config.json` + 專案
   `.claude/aitask-config.json`）—— 但若全域 config 只存 token 沒存帳密，
   token 失效時無法自動重登，要重跑 `aitask login --save`。
3. 重啟 Codex → 應看到 `aitask_list / aitask_new_task / ...` tools。

## 合作 conventions 從哪來

**單裝 MCP 不會自動帶 conventions** —— 但 server `instructions` 會叫 client
開場先呼叫 `aitask_get_conventions`，那個 tool 回傳
[`../../src/aitask/AICONTEXT.md`](../../src/aitask/AICONTEXT.md) 全文（dual-track
標籤、L1/L2/L3、下次接手、否決方案精神等）。不用手動 paste、convention 更新
自動吃到。

Codex 另外會自動載入 repo 根目錄的 **`AGENTS.md`**。本 repo 的 `AGENTS.md` 是
薄指標（指向 AICONTEXT.md + CLAUDE.md），刻意不複製慣例內容 —— 你自己的專案
建議照抄這個模式，別把 AICONTEXT.md 整份貼進去變成會 drift 的第二份副本。

## 路徑 B：CLI（shell-only）

Codex 能跑 shell 就能直接用 `aitask` CLI（`aitask list` / `new` / `log` /
`done` …，見 [README](README.md) 的 cheat sheet）。這條路徑**沒有**
`aitask_get_conventions`，conventions 要靠 `AGENTS.md` 指路或手動 paste。

## 驗證

```bash
aitask list                    # CLI 驗證
"<python>" -m aitask.mcp       # MCP 驗證：應 hang 在 stdio（沒 traceback 就對，^C 退出）
```

MCP server 啟動失敗多半是 `mcp` package 沒裝 —— script 會印 install 指令。
