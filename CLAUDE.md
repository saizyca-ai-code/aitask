<!-- aitask:init -->
# aitask — AI 開發夥伴規則

我是這個 repo 的 AI 開發夥伴。這裡是 **aitask 獨立 pip 套件**本身的原始碼
（decision #114 / #116 從 MSSceneDetect 抽出）：AiCodeTask 開發追蹤器的
CLI + Python client lib + MCP server。

---

## 協作慣例 → 讀 `src/aitask/AICONTEXT.md`（session 開始先讀一遍）

本 repo 的**合作方式**（雙軌標籤詞彙、decision 文件必含「否決方案」、
提案 → 確認 → 執行、方案 A/B/C、誠實規則、commit 切細、「下次接手」收尾、
deep-link 規約…）**單一來源在 `src/aitask/AICONTEXT.md`**。它是 tool-agnostic
版、同時給走 MCP 的其他 AI 工具（Antigravity / Cursor / Codex）用。本檔只放
repo 專屬 context，不重複 AICONTEXT.md 的內容。

> 它住在 package 裡（不是 repo 根目錄）是刻意的：它是 `aitask_get_conventions`
> 的**執行期資源**，得靠 pyproject `package-data` 才能跟著 wheel 走。移回根目錄
> 會讓非 editable 安裝讀不到（`tests/test_packaging.py` 守這條）。

> ⚠️ **Dual-sync（decision #25 / #116）**：`AICONTEXT.md` 與 MSSceneDetect repo 的
> `CLAUDE.md` + `/aitask` skill 是同一套慣例的兩份。改**任何** convention，兩邊
> 都要更新（新增 chapter 前先 grep 兩份看現有覆蓋）。

---

## 開發追蹤 → AiCodeTask project **AiTaskMCP (#51)**

- `.claude/aitask-config.json` 已指向 `project_id=51`（slug=`aitaskmcp`）。
- Session 開始 `aitask list`；commit 後 `aitask log <id>` / `aitask done <id>`；
  重大決策（含 trade-off）`aitask decision`；發現 sub-task `aitask new`。
- **Chat 回覆提及 task / doc 一律 deep link**（裸 `#NN` 會被 linkify 成 404）：
  - Task：`[#NN](http://localhost:5173/#project/aitaskmcp/tasks?open=NN)`
  - Doc：`[#NN](http://localhost:5173/#project/aitaskmcp/documents?open=NN)`

---

## 這個 repo 是什麼（三個 consumer）

| 檔案 | 角色 | 誰用 |
|---|---|---|
| `src/aitask/cli.py` | `aitask` CLI | 人 + Claude Code（走 Bash） |
| `src/aitask/mcp.py` | `aitask-mcp` MCP server | Antigravity / Cursor 等 MCP client |
| `src/aitask/client.py` | REST client lib | CLI + MCP 共用 |
| `src/aitask/parse.py` / `tags.py` | 標籤 parser + 雙軌 tag 組裝 | 上面三者共用 |
| `src/aitask/AICONTEXT.md` | tool-agnostic 慣例（`aitask_get_conventions` 回傳它）；package data | MCP client + `CLAUDE.md` / `AGENTS.md` 指過去 |

---

## 動手前必懂（影響面）

- **雙 editable 安裝**：這份 code 以 `pip install -e` 裝在兩處 —— 使用者的 uv venv
  （PATH 上的 `aitask` / `aitask-mcp`）+ MSSceneDetect 的 `python_embed`。改了**立即
  生效兩邊**，不用重裝（reconnect / 重啟跑該 code 的行程即可）。
- **MCP server 改動（`mcp.py`）影響所有 MCP client**。client 唯一看得到的是
  **tool docstring + server `instructions`**（`FastMCP("aitask", instructions=...)`）—
  改 docstring / 加工具時要想到 Antigravity 那邊會怎麼讀。**別在 docstring 指
  「CLAUDE.md」**（MCP client 看不到）—— 要指就指 `aitask_get_conventions`。
- **慣例遞送給 MCP client** 靠 `aitask_get_conventions()`（回傳 AICONTEXT.md）+
  server `instructions`（叫 client 開場先呼叫它）。改慣例 = 改 AICONTEXT.md，
  MCP client 自動吃到；但 Claude Code 那條要另外 sync（見上面 dual-sync）。

---

## 測試 / 驗證

- ⚠️ **目前 parse 單元測試在 MSSceneDetect 的 `tests/test_aitask_parse.py`**，本 repo
  **還沒有自己的 test 套件** —— 這是個候選 task（把測試搬進來 / 補 CI，避免測試綁
  在 consumer repo）。
- 快速 smoke：`python -c "import aitask.cli, aitask.mcp, aitask.parse"`、`aitask list`、
  `aitask-mcp`（起 stdio server）。
- 改 `mcp.py` 後驗 server 建構：`python -c "import aitask.mcp as m; m._build_server()"`。

---

## 誠實 / 風格重點（完整見 `AICONTEXT.md`）

- **決策文件必寫「否決方案」+ 具體理由**，否則沒學習價值（`aitask_create_decision`
  / `aitask decision` 會 enforce）。
- **M+ 改動先提案**（方案 A/B/C + 取捨）→ 使用者確認 → 執行；S task / 小 bug 直接做。
- **不確定就說不確定**，別假裝有見解。**commit 切細**、每個 message 是給未來的文檔。
