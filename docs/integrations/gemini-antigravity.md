# Gemini Antigravity × aitask

Antigravity 原生支援 MCP，所以走 MCP server 路徑接。假設你已經照
[`../getting-started.md`](../getting-started.md) 裝好 aitask（`pip install -e .`
進你選定的 Python 環境）。下面的 `<python>` 都代表**那個環境**的
`python.exe`——一般裝法在 PATH 上直接打 `python` 就是；獨立 venv/embedded
Python 要用完整路徑。

## 設定

1. 安裝 mcp 依賴 — **裝進哪個 Python 很重要**：MCP config 的 `command` 要指向
   *同一個* Python，否則 `aitask.mcp` 模組找不到：
   ```bash
   # Windows（--cache-dir 繞過某些機器上壞掉的 pip cache 路徑）
   "<python>" -m pip install --cache-dir %TEMP%/pipcache -e ".[mcp]"
   ```

2. 確保你要記錄進去的 AiCodeTask 後端在跑（`base_url` 指到的那個服務）—
   Antigravity 不會自動把它拉起來。

3. 查 `project_id`：
   ```bash
   aitask projects
   # 印出：
   #   ID  Slug          Name           Description
   #   34  aicodetask    AiCodeTask     ManageAiCodeTask
   ```
   或 MCP 啟動後讓 AI 呼叫 `aitask_list_projects` 也行。

4. **填 MCP config**。關鍵兩點：**`command` 用絕對路徑的 Python + `-m aitask.mcp`**
   （不要用 `aitask-mcp` — 那個 .exe 落在該 Python 的 `Scripts/`，多半不在 PATH 上、
   會「command not found / 工具沒出現」），認證**推薦帳密**（見下）。

   **推薦寫法 — Python `-m` + 帳密**（最穩、server 重啟也不用重設）：
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
   MCP server 啟動時自動 `POST /api/auth/login`、後續用拿到的 session 跑。**帳密路徑
   會在 token 失效時自動重登**，所以後端常重啟（開發期常見）也不會斷。

   **替代 — 用 token（避免明碼密碼進 config）**：
   ```bash
   "<python>" -m aitask.cli login --username claude --password your-password -v
   # 印出 session_id，貼到上面 env 的 AITASK_TOKEN（移除 USERNAME/PASSWORD）
   ```
   ⚠ **token 會在 server 重啟 / session 過期時失效**、得重跑上面指令換一張。後端
   重啟頻繁的開發環境 → **建議直接用帳密路徑**，少一個壞掉的點。

5. **灌合作 conventions**：MCP 只提供工具存取權、不傳合作風格。**推薦**做法
   是讓 AI 自己 fetch conventions（單一 source of truth、改一次所有工具下次
   session 都拿到最新版）。

   Antigravity workspace rules（或 system prompt / per-project AI rules）只
   需要一行：

   ```
   At the start of each session, call the `aitask_get_conventions` tool and
   strictly follow the conventions it returns. After that, proactively use
   other aitask_* tools per the L1/L2/L3 trigger guidance.
   ```

   AI session 開始時 call `aitask_get_conventions` → 拿到 AICONTEXT.md 全文
   →   後續行為按 conventions 走（dual-track 標籤、下次接手、否決方案、L1/L2/L3
   分級等）。

   **替代做法**（不想多一次 tool call）：手動 paste `src/aitask/AICONTEXT.md`
   （package data，跟著 `pip install` 一起裝進去）整份進 workspace rules。
   Convention 更新時要重 paste。

## 驗證

打開 Antigravity → 新對話 → 直接讓 AI 試 `aitask_list`。應該看到你
config 指到的那個專案的 pending tasks。

## MCP server 沒出現 / 「command not found」/ 沒有 aitask_* 工具？

最常見的卡點，依序檢查：

1. **`command` 用對 Python 了嗎**：必須是「裝了 `aitask[mcp]` 的那個 Python」的絕對
   路徑 + `args:["-m","aitask.mcp"]`。用 `aitask-mcp`（裸名）多半會 not found（.exe
   落在該 Python 的 `Scripts/`、不在 PATH）。
2. **手動跑一次確認能起**（會 hang 在 stdio，看到沒 traceback 就對了，Ctrl+C 退出）：
   ```bash
   "<python>" -m aitask.mcp
   ```
   - `No module named aitask` → 第 1 步裝錯 Python，重裝到 command 指的那個。
   - `No module named mcp` → 漏了 `[mcp]` extra，重跑 `pip install -e ".[mcp]"`。
3. **後端沒在跑** → tool call 會連線失敗。先確認 `base_url` 指到的服務起來了。
4. 改完 config 記得**重啟 Antigravity**（MCP server 清單啟動時才讀）。

## 撞到 403「缺少權限：view.tasks」？

Auth 過了但你的 user 在 該 project 上沒有 view.tasks 權限。檢查：

* 該 user 是不是 project member（Project Settings → 成員）
* 該 user 的 role 是否含 view.tasks（Project Settings → 角色與權限 → 該 role
  → view.tasks 打勾）
* Owner role / Administrators 群組成員都自動含所有權限

新建 user 預設不屬於任何 project — 要 admin 手動加成 member 並指派 role。

## 跨工具共用 config

如果你 Claude Code + Antigravity 都用同一個 user 帳號，直接跑
[`aitask setup`](../getting-started.md) 一次——寫進
`~/.config/aitask/config.json`（XDG 標準），兩邊都能讀，不必每個工具都設
env var：

```json
{
  "base_url": "http://localhost:5173",
  "token": "<session_id>"
}
```

（`aitask setup` 只存 `base_url` + 登入拿到的 token，不存明碼密碼。想額外
記 project_id，用 `aitask init -p <project>` 在該專案目錄再加一層。）

## 已知限制

- Antigravity 目前還在 active dev、MCP integration 細節可能變動 — recipe
  寫到本檔時的版本，發現 broken 時更新本檔
- AiCodeTask 後端還沒有「user → 取自己長效 token」的 UI；用 `aitask login`
  拿的是 session token（server 重啟或 session 過期就失效、要重拿）
