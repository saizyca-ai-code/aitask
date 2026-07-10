# 快速上手 — 從安裝到第一次 `aitask list`

給第一次在**新機器**或**新專案**接上 aitask 的人。這份文件跟著套件一起
散佈，所以不引用任何特定 AiCodeTask 實例的內部連結——完整設計背景（config
分層合併 + setup/init + `-p` 解析的決策脈絡）記在原始開發那個 AiCodeTask
專案的 decision 文件裡，跟這份套件文件是分開的兩件事。配置 schema / 解析
順序等參考資料見主 [README.md](../README.md#config)。

## 心智模型

**大腦（後端 + DB，一個共用）** vs **電話（CLI，可散佈到任何機器 / 專案）**。
「記到哪個專案」永遠由 config 決定，跟工具裝在哪無關。兩步驟：

1. `aitask setup` — **每台機器一次**：存 `base_url` + 登入 token 到全域
   config。
2. `aitask init -p <project>` — **每個專案一次**：在專案目錄寫一個只含
   `project_id` 的 config，`base_url`/token 繼承步驟 1。

裝過一次 + 每個新專案一句話，之後這台機器上任何專案目錄都能直接
`aitask list` / `aitask new ...`。

## 0. 安裝

`aitask` 是一個獨立的 pip 套件（自己一份 repo，不跟著任何使用它的專案
走）。裝一次、裝進**你自己選的一個 Python 環境**（建議是專門給 aitask 用
的 venv，不要裝進系統 Python — 避免跟其他工具的套件版本打架）：

```bash
# 從這份 aitask 原始碼的 repo 根目錄
pip install -e .

# 之後任何目錄都能呼叫（前提是這個 Python 環境的 Scripts/bin 在 PATH 上）
aitask --help
```

零執行期相依（純 stdlib）。MCP server 才需要 `pip install -e ".[mcp]"`。

> **找不到 `aitask` 指令？** 確認裝的是你目前用的那個 Python 環境（`pip install -e`
> 是裝進當時 `pip` 對應的 interpreter，不是系統全域）。指令腳本會落在該
> Python 的 `Scripts/`（Windows）或 `bin/`（Unix）目錄，需要在 PATH 上才能
> 直接打 `aitask`；否則用完整路徑呼叫，例如
> `<python_dir>/Scripts/aitask.exe <subcommand>`。
>
> **給 AI 代理人的注意事項**：如果 shell 裡 `aitask` 指令找不到，**不要**
> 自己猜一個本機路徑（例如去找專案目錄下有沒有 `tools/aitask/` 之類的資料
> 夾、或憑印象拼湊 `sys.path.insert(0, ...)` 的舊呼叫方式）——`aitask` 現在
> 是獨立套件，沒有固定的相對路徑可猜。正確做法：跟使用者確認這台機器上
> aitask 裝在哪個 Python 環境、該環境的 `Scripts/`（或 `bin/`）目錄有沒有
> 在 PATH 上，或者請他們直接提供完整的 `aitask` 執行檔路徑。

## 1. `aitask setup` — 每台機器一次

```bash
aitask setup
```

互動式問三個問題：

```
aitask base_url [http://localhost:5173]:   ← 你的 AiCodeTask 後端網址，Enter 用預設值
username:                                   ← 你的帳號
password:                                   ← 密碼（隱藏輸入，打字不顯示）
```

成功會印：

```
✓ logged in as <name> (id=<id>)
✓ global config saved: ~/.config/aitask/config.json
  base_url=<base_url>
```

寫進 `~/.config/aitask/config.json` 的**只有 `base_url` 跟登入拿到的
session token**——密碼只在這次登入用一下，不會被存下來。

不想互動輸入（例如寫腳本 / CI）可以帶 flag 跳過 prompt：

```bash
aitask setup --base-url http://localhost:5173 --username claude --password ...
```

`token` 是 session_id、不會過期（除非登出），機器重開機不用重跑 setup。

## 2. `aitask init -p <project>` — 每個專案一次

```bash
cd my-project
aitask init -p <id|slug|name>
```

`-p` 可以吃 project **id**（`34`）、**slug**（`aicodetask`）、或**name**
（`AiCodeTask`）——不確定的話先跑 `aitask projects` 列出帳號可見的所有
專案。

成功會印：

```
✓ project config written: my-project/.claude/aitask-config.json
  project #<id> — <name> (slug=<slug>)

✓ init complete — try `aitask list` from this directory.
```

同時會：

- 寫 `.gitignore` 排除該 config 檔（裡面雖然只有 project_id，仍視為機器
  本地設定，不進版控）
- 在 `CLAUDE.md` 補一段「這個專案已接 aitask」的提示（沒有 `CLAUDE.md` 會
  新建；已存在則 idempotent — 重跑不會重複加）
- 檢查 tasks/documents 模組是否啟用、複雜度/預估工時/類型等自訂欄位是否
  存在——**缺的話印警告、不擋你**（aitask 本來就容錯：欄位缺就只寫
  markdown 那一軌，見 [README.md](../README.md) 雙軌資訊架構）

已經 init 過想重寫（例如專案改名、換了 slug）：`aitask init -p <project> --force`。

## 3. 驗證

```bash
cd my-project
aitask list
```

這時 `my-project/.claude/aitask-config.json` 只有 `project_id`，`base_url`
跟 `token` 是從步驟 1 寫的全域 config 繼承來的（分層合併：全域當底 ← 專案
覆蓋 ← env 變數最上層，細節見 [README.md](../README.md#config)）。能印出
pending tasks 列表就代表整條鏈路是通的。

## 4. 一次性切換專案（不改 config）

任何子指令都能接 `-p <id|slug|name>`，只影響**這一次呼叫**，不寫回任何
config 檔：

```bash
aitask list -p other-project          # 臨時查另一個專案
aitask new "標題" -p other-project    # 臨時建到另一個專案
```

適合「大部分時間記到專案 A，偶爾想順手記一筆到專案 B」的情境，不用整組
config 換來換去。

## 疑難排解

| 現象 | 原因 / 處理 |
|---|---|
| `aitask config not found` | 兩個 config 都沒有。先跑 `aitask setup`，再 `aitask init -p ...` |
| `HTTP 401` | token 失效或密碼錯——重跑 `aitask setup`（或 `aitask login --save` 只換 token） |
| `HTTP 403` | 帳號權限不足，跟後端 Owner 確認角色 |
| `Connection failed` | `base_url` 沒在跑或打錯——檢查 `~/.config/aitask/config.json` 的 `base_url` |
| `-p` 報「Ambiguous project name」 | 有多個專案同名，改用 slug 或 id |
| `-p` 報「No project found」 | 帳號看不到那個專案，或 id/slug/name 打錯，先跑 `aitask projects` 核對 |
| `init` 報「already exists」 | 該目錄已經 init 過，要覆寫加 `--force` |

## 之後想清掉重來

```bash
rm ~/.config/aitask/config.json        # 清全域（下次要重新 setup）
rm my-project/.claude/aitask-config.json   # 清單一專案（下次要重新 init）
aitask logout                          # 順便讓後端 session 失效（best-effort）
```
