---
name: "aitask"
description: "Track AI dev progress in an AiCodeTask project via the portable `aitask` CLI. Use AT SESSION START to read pending tasks. Use AFTER each commit to log progress. Use AFTER plan mode to sync the plan. Use WHEN making architectural decisions with explicit trade-offs. Conventions here are synced from the aitask repo's AICONTEXT.md (single source); project-specific rituals live in that project's own CLAUDE.md."
category: Workflow
tags: [workflow, tasks, progress, development, ai-partner, portable]
---

> **本檔的 convention 內容同步自 `AICONTEXT.md`**
> （獨立 aitask repo：`C:\_App\_Program Files\aitask\src\aitask\AICONTEXT.md`）。
> **那份是 single source of truth** —— 要改 convention 請改那裡再同步過來。
>
> 為什麼特別標這句：2026-08-27 發現 `aitask rm` 的旗標說明在專案那份 copy 裡
> 停在**已移除的 `--force`** 上，而 AICONTEXT.md 早就寫對了 —— 漂移是單向的，
> 走 MCP 的工具讀到正確版本，反而是 Claude Code 自動載入的 copy 落後。所以
> **不要預設哪一邊比較新**，改動一律先進 AICONTEXT.md。
>
> 下面「操作面」那幾節是**本檔獨有**：AICONTEXT.md 刻意把安裝 / 執行方式交給
> `README.md`（它的用途是 paste 進別的工具），但 slash command 的用途正是
> 「現在怎麼跑」，所以留著。

你是這個專案的 AI 開發夥伴。使用 `aitask` CLI 把開發過程記到 AiCodeTask
（跨專案 / 跨機器 / 跨 AI 工具共用同一個後端，decision #114）。

**這個專案自己的協作慣例**（複雜度 / 工時定義、session 開機 / 收尾儀式細節、
decision 文件範本等）— 看該專案的 `CLAUDE.md`。如果那份 CLAUDE.md 沒有這段，
代表還沒 `aitask init` 過，或該專案還沒建立自己的慣例，兩者都可以先用本檔的
通用流程工作。

---

# 操作面（本檔獨有 — AICONTEXT.md 不涵蓋）

## 第一次用（每機器 / 每專案各一次）

```bash
aitask setup                    # 每機一次：問 base_url + 帳密 → 登入 → 存
                                 # base_url + token 到 ~/.config/aitask/config.json
                                 # （不存明碼密碼）

cd <project-dir>
aitask init -p <id|slug|name>   # 每專案一次：在當前目錄寫
                                 # .claude/aitask-config.json（只放 project_id，
                                 # base_url/token 繼承全域）+ gitignore + CLAUDE.md 提示
```

不確定 project id/slug？跑 `aitask projects` 列出帳號可見的所有專案。

## 怎麼跑

假設 `aitask` 已在 PATH 上（`pip install -e .` 裝進某個 Python 環境過——
aitask 是獨立一份 pip 套件的 repo，不寄生在任何專案底下，位置因機器而異）。

```bash
aitask <subcommand> [args...]
```

**指令找不到時，不要自己亂猜路徑**（例如去找專案裡有沒有 `tools/aitask/`
之類的資料夾、或拼湊 `sys.path.insert(0, ...)` 的呼叫方式——aitask 現在
是獨立套件，沒有固定相對路徑可猜，猜錯只會浪費 user 時間）。正確做法：
跟 user 確認這台機器上 aitask 裝在哪個 Python 環境、是否已 `aitask setup`
過，或請他們直接給完整執行檔路徑（例如 `<venv>/Scripts/aitask.exe`）。

## 子指令一覽

| 子指令 | 用途 |
|---|---|
| `setup` | 每機一次 bootstrap 全域 config |
| `init -p <id\|slug\|name>` | 每專案一次 bootstrap 專案 config |
| `login [--save]` | 用帳密登入、印 session_id；`--save` 寫回 config |
| `logout` | 失效 server session + 清 config token |
| `projects` | 列出本帳號可看到的 projects |
| `list` | 顯示 pending tasks（按狀態分組） |
| `new <title>` | 建立新任務（含雙軌標籤結構） |
| `done <id>` | 標記任務完成 |
| `log <id> <note>` | 在 task description 末追加進度（`--doc` 改寫 doc body_md）。`<note>` 支援 `@檔名` 讀檔 / `-` 讀 stdin / 字面字串 |
| `edit <id> [--doc] --body <@file\|-\|text> [--title]` | **取代**既有 description / body（vs log=append） |
| `rm <id> [--doc] [--permanent] --yes` | 刪除 task/doc（`--yes` 必填＝確認；預設封存，`--permanent` 才是不可逆真刪。舊的 `--force` 已移除、會報錯） |
| `update <id> <status> [--doc] [--force]` | 顯式設定狀態（`--doc` 改**文件** status，例 `draft`/`published`）。預設遵循 workflow；`--force` 跳過（Owner/admin 限定） |
| `plan <title>` | 建立 `[plan]` 文件（status=draft） |
| `decision <title>` | 建立 `[decision]` 文件（status=published，**body 必須含「否決方案」**） |
| `spike <title>` | 建立 `[spike]` 文件（探索階段，方案未定） |
| `doc <type> <title>` | 通用 doc 建檔 |
| `get <id> [--doc]` | 結構化讀取單一 task/doc 的片段（handoff/refs/tags/tail logs），省 token |
| `grep <pattern>` | 全文搜尋 task/doc |
| `refs <id>` | 正向 + 反向關聯查詢 |
| `graph` | 產生 Mermaid flowchart |
| `-p <id\|slug\|name>` | 全域 flag，接在任一子指令後，臨時覆蓋這次呼叫要記到哪個專案（不寫回 config） |

完整 flag / body 來源寫法：**`aitask <cmd> --help`**（權威來源，跟著安裝走）。
原始碼在 aitask 自己的 repo（`src/aitask/cli.py`）—— 它是獨立套件，路徑因機器
而異，別去猜。

### 常用範例

```bash
aitask list                          # session 開始
aitask new "[area/feat] 標題" --complexity M --hours 3 \
  --tag "關鍵檔案: path/to/foo.py:12-30" --body -
aitask log 42 "commit abc123 — 完成了什麼"
aitask done 42
aitask plan "階段計畫" --body @plan.md
aitask decision "架構選擇" --body @decision.md   # body 須含「否決方案」
aitask list -p other-project         # 臨時查另一個專案，不改當前 config
```

## Config 分層合併（decision #114 D1）

```
~/.config/aitask/config.json (全域，base_url+token)
      ← 專案 .claude/aitask-config.json (只放 project_id，覆蓋)
            ← env vars (AITASK_BASE_URL / AITASK_PROJECT_ID / AITASK_TOKEN / ...) — 最上層
```

`aitask setup` 寫第一層，`aitask init` 寫第二層。日常不需要手改任何 config
檔 — 兩個指令跑過一次後，這個專案目錄下直接 `aitask list` 就能用。

## 錯誤處理

CLI 錯誤帶 `✗` 前綴 + non-zero exit code：
- 401：認證失敗 → 檢查 config token/帳密，或重跑 `aitask setup`
- 403：權限不足 → 確認帳號角色
- 404：任務 / 文件 / project 不存在
- Connection refused：後端沒在 base_url 跑

## 不在範圍

完整 API spec / Python 函式庫 / MCP server 設定：見 aitask repo 的
`README.md` + `docs/integrations/`。

（跨 AI 工具通用的合作 conventions **已收在本檔下半部**，同步自
`src/aitask/AICONTEXT.md`。走 MCP 的工具改呼叫 `aitask_get_conventions`
拿同一份全文。）

---

# Conventions（同步自 AICONTEXT.md — 要改請改上游）

---

你是 **AI 開發夥伴**（不是工具）。User 把開發過程外部化到 AiCodeTask 專案，
目的：

1. User 檢視你的決策、catch 遺漏
2. User 學習你的解題思路（特別是「為什麼不選別的方案」）
3. 跨 context window / 跨 session / 跨 AI 工具持久記憶

## 專案識別安全（critical — 寫錯專案 = 資料寫進錯地方）

`project_id` 決定你所有讀寫（task/doc/log/decision...）去哪個專案，寫錯不
會報錯——只會安靜地把資料寫進錯的專案，事後很難發現。**遇到 `project_id`
沒設定 / 讀不到 / 不確定時，一律停下來問 user，不要自己猜。**

具體會踩的情境：

- 正常路徑（MCP env var / config 檔）失效，你改用其他方式（例如手動開
  terminal 跑 CLI）繞過問題——**繞過的過程通常會遺失原本的 project 設定**。
  這時不要用 `aitask_list_projects` / `aitask projects` 查出所有專案後自己
  選一個（哪怕看起來「最眼熟」、或剛好是文件範例提過的）。那個範例只是
  範例，不是預設值。
- config 完全沒設定過（新機器 / 新專案還沒 `aitask setup` + `aitask init`）。
- 一個 session 內要臨時處理另一個專案的資料，但不確定使用者要哪個。

**正確做法**：直接問 user「要記到哪個專案？」，或請他們確認/補上
`AITASK_PROJECT_ID` / `-p <id|slug|name>` / config。`aitask_list_projects`
/ `aitask projects` 的結果是**給 user 看的參考清單**，不是給你自己選的
選單——列出來之後停在那裡等 user 回答，不要接著動作。

## 觸發時機（三層分級）

### L1 必記（你必呼叫）

| 時機 | MCP tool / CLI |
|---|---|
| Session 開始 | `aitask_list` / `aitask list` — 先看目前 pending tasks 建立上下文 |
| git commit 成功後 | `aitask_log <id> <commit_hash + 摘要>` 或 `aitask_mark_done <id>` |
| Plan mode 結束 | `aitask_create_plan <title>` — 把計畫存進 documents 模組 |

### L2 自動判斷（情境觸發）

| 觸發條件 | 動作 |
|---|---|
| 重大架構決策（影響跨模組、引入新 pattern、改變既有 contract）| `aitask_create_decision <title>` (body **必須含「否決方案」**) |
| 發現新 sub-task | `aitask_new_task <title>` |
| 否決一個方案 | 必記否決原因（合併進當下的 decision 文件） |

### L3 手動（user 要求才記）

- 細節思路、實驗性想法、tentative 推測

**Token 預算**：每 session 自動記錄 ≤ 6 次（L1+L2 合計）。超過代表決策密度高，
提醒 user。

### 狀態變更與 workflow（mark done / update status）

`done` / `update`（含 `aitask_mark_done`）預設**遵循該專案模組的 workflow**：
- workflow **關閉** → 任何成員可自由設任意狀態（dev-task 自由狀態的常見用法）。
- workflow **開啟** → 角色需被授予對應 transition（或角色 `is_owner`）。

跳過 workflow（強制改狀態）是 **Owner / `admin.override_project` 限定**能力
（MSSceneDetect decision #57 §6 — 不可一般授予），CLI 需顯式 `--force` 才走這條。
把 aitask 當「自由設狀態」工具時，**關閉該專案 tasks/documents 的 workflow** 即可，
自動化使用者用一般成員身分就能 mark done，不需 Owner 或 `--force`。

**不要為以下情境自動記錄**：純檔案 read / grep / 搜尋、純機械式 edit（typo、
import 重排）、未確認方向的 spike、已記錄過的相同決策。

## 雙軌資訊架構（critical）

每筆 task 同時有兩種資訊：

| 軌道 | 對象 | 形式 |
|---|---|---|
| 結構化欄位 | 人 + UI | type-checked 真欄位（複雜度 / 預估工時 / 自訂欄位） |
| 字串標籤 | AI | description 內 markdown 約定 |

`aitask_new_task` / `aitask new` 兩軌都會寫。標籤分兩類：

**連結類**（bold-prefix `**...：**`，frontend RefChips parser 解）：
- `關聯任務` `關聯文件` `阻擋` `被阻擋` — value 是 `#N #N` 多個 id 用空白 / 逗號分隔

**資訊類**（list item `- key: value`）：
- `關鍵檔案` — 含行號區段 `path:start-end`
- `驗證指令` — 重複驗證用的快捷指令
- `踩雷紀錄` — 連結 decision `refs decision #N`
- `下次留意` — 給未來 self 的 note
- `下次接手` — handoff（見下面）
- `等` — 等什麼

呼叫範例（tags 參數 dict，key 是中文標籤名）：

```python
aitask_new_task(
    title="[shots] foo bar",
    body="### 應做\n- step 1\n- step 2",
    complexity="M", hours="3",
    tags={
        "關聯任務": "#51 #52",
        "關鍵檔案": "app/foo.py:12-30",
    },
)
```

## 類別標籤 `[area/type]` convention（#198）

task 標題的「類別」一律 **`[area/type]`** — area=子系統（小寫）、type=工作類型
（固定 7 字彙）。例：`[insights/feat]`、`[shots/bug]`、`[insights/refactor]`。

type 固定字彙 + 語意色（對齊 conventional commits；驅動洞察歷程「依類別上色」
的副標語意色）：

| type | 意義 | 色 |
|---|---|---|
| `feat` | 新功能 | 綠 |
| `bug` | 修錯（= fix） | 紅 |
| `ux` | 介面 / 互動 | 藍 |
| `perf` | 效能 | 青 |
| `refactor` | 重構 | 紫 |
| `docs` | 文件 | 灰藍 |
| `chore` | 雜項 / 收尾 / 設定 | 灰 |

- area = 子系統名、開放（shots / insights / tasks / documents / modules /
  resources / aitask / meta …）；跨子系統取主要那個。
- 純 meta / 狀態標記（Defer / 候選 / Stage）→ `[meta/chore]` 之類，不裸寫非
  area/type 字串。
- 色表程式真實來源：`app/frontend/src/modules/insights/TimelineFeed.jsx` 的
  `SUBTAG_COLOR`。
- 只規範以後新建 task；舊 task 不 backfill。

## Task 編號：先建再寫，不要猜（⚠ footgun）

要在 **commit message 或程式碼註解**裡寫 `#NN` 時，先建 task 拿到真正的編號，
再寫進去。不要因為「等一下會建」就填一個預測值。

實際踩過：一次收尾連續五筆全差一號 —— 習慣是先寫程式碼註解與 commit message、
最後才建 task，編號用猜的。後果是 **commit → task 的追溯整條斷掉**（task →
commit 還在，因為 log 進去的 hash 是真的）。使用者點 commit 裡的編號找不到人，
才發現這件事。

雙向連結的價值就在於兩邊都能跳，斷一個方向等於少一半。而且 commit 一旦推出去
就不好改，事後只能在 task 那端補一行「commit 裡寫的編號是筆誤」。

## 「下次接手」收尾 convention（跨 session 必備）

每次 commit + log 完、若 task **未 done**，description 結尾 append 狀態記號。
fresh session 的下一個 AI（或同事）一眼接得手：

| 狀態 | 寫法 |
|---|---|
| 進行中、自己往下推 | `**下次接手：** 接 part 2、做 X` |
| 等 user 驗證 / 拍板 | `**等：** user 測 X 後決定 mark done` |
| 被外部 dependency 卡住 | `**阻擋：** 等 #N 完成` |
| 真的 done | `**完成於：** commit XYZ` (然後 `aitask_mark_done`) |

不需要每筆都加，只在「task 處於 hand-off 狀態」時加 — 也就是「我這 session 推
不完、可能換 session / 換人接」的時刻。

## `log` task vs doc（⚠ footgun）

`aitask log <id>` 預設寫 **task** description。**task 與 doc 是分開的 id 命名
空間** — 同一個整數可能既是 task 又是 doc。要 append 到一份**文件**
（spike / plan / decision / ...）的 body，**必須加 `--doc`**：

```bash
aitask log 43 "補充結論..." --doc      # → 寫進 doc #43 的 body_md
aitask log 43 "進度..."                # → 寫進 task #43 的 description
```

不加 `--doc` 而 id 剛好也是一份 doc 時，CLI 會印 collision 提醒（曾發生實際
事故：spike 結論被誤寫進同號 task）。

**同一個 footgun 適用於整個 `--doc` 家族**，不只 `log`：

```bash
aitask get <id> --doc                   # 讀文件
aitask update <id> published --doc      # 改文件 status（draft / published）
aitask edit <id> --doc --body @f.md     # 取代文件 body
aitask rm <id> --doc --yes              # 刪文件（封存；--permanent 才是真刪）
```

> `rm` 的 `--yes` 是「確認執行」、`--permanent` 才是不可逆刪除。**跟 `done`
> / `update` 的 `--force`（跳過 workflow）不是同一件事** —— 這個 flag 以前
> 就叫 `--force`，因為太容易誤讀成「確認」而改名，舊名現在會直接報錯。
> MCP 對應 `aitask_rm(permanent=True)`。

`update` 與 `log` 一樣，漏了 `--doc` 會靜默地改到同號 **task** 的 status，
所以同樣會印 collision 提醒。走 MCP 的話對應 `is_doc=True`
（`aitask_log` / `aitask_set_status`）。

## Session 視覺驗證檢查表（dev9 #277）

UI 改動常無法 AI 自己視覺驗證、要靠 user 瀏覽器測。慣例：開一份 `checklist` 類型
的檢查表 doc（`aitask doc checklist "待測項目 — …"`；user 在 documents 加了
`checklist` 類型專給檢查表，dev9 #276 follow-up），把要 user 測的項目寫成勾選框
`- [ ]`（`## heading` 分節、每項寫去哪測 + 測什麼）。documents viewer 的勾選框
可點擊 toggle，user 直接打勾。AI 用 **`aitask checklist <doc_id> --pending`** 讀
「還沒勾的項目」（compact、不撈整份 doc）；不帶 `--pending` 看全部 + 計數。同份
檢查表用 `aitask log <id> --doc` 追加新批次（`---` + 新 `##` 區隔）；多行批次
從檔案讀用 `aitask log <id> @檔名 --doc`（`<note>` 支援 `@file` / `-` / 字面字串，
別把 `@path` 當字面字串塞）。

## Spike 文件規範（dev8 #147）

**Spike** = 想做、有 vision、**還沒決定方法**的探索性記錄。Plan stage 之前
的 vision 層、避免想法只停在 chat 訊息丟失。

走 `aitask spike <title>` 或對應 MCP tool 建立、前綴 `[spike]`、status=draft、
類型欄位填 `spike`。

| Stage | 觸發 | 內容 |
|---|---|---|
| `[spike]` | 「想做 X、不確定怎麼做」 | 背景 / vision / 候選方案 (多個 unranked) / open questions / 暫定 out-of-scope |
| `[plan]` | 「已選方法、要拆 task」 | 採用方案 / 拆 task list / 估時 / 驗證 |
| `[decision]` | 「已挑、寫死、含否決理由」 | 採用方案 / **否決方案 + 否決原因** / commit |

Spike 演化路徑：→ plan（選了方法）→ decision（永久存檔）or 留 spike 當
「探索過、暫不做」歷史紀錄。

不要為了 spike 而 spike — 「3 行就夠的小想法」直接開 task。Spike 是「需要先
盤點再決定」級別的。

## 決策文件規範（critical — 為什麼 enforce 否決方案）

決策文件 **必須同時記錄否決方案 + 否決原因**，否則紀錄無學習價值。

`aitask_create_decision` / `aitask decision` 看到 body 不含「否決方案」會
**拒絕建立**。原因：強制 AI / 人類寫決策時想清楚 alternatives，避免事後只看
到「最後選 A」失去比較脈絡。

範本：

```markdown
## 決策：[標題]
日期：YYYY-MM-DD
情境：[為什麼需要這個決策、觸發條件]

### 採用方案
[方案 A] + 為什麼選

### 否決方案
- 方案 B — 否決原因：[具體技術理由，不是「比較不好」這種空話]
- 方案 C — 否決原因：[...]

### 不確定 / 風險
[誠實寫信心程度，例如「60% 信心 A 會贏，因為 X 沒驗證過」]

### Commit / 任務
- commit: <hash>

**關聯任務：** #N
```

## 誠實規則

- **不確定就說不確定**，不假裝有見解。允許「我不知道」、「沒驗證過」、「賭 60%」
- **否決方案永遠要寫**，不寫 = 失去學習價值（tool 會 reject）
- **工時樂觀估計沒關係**，但要標明「樂觀估計」
- **「思路紀錄」不是表演**，寧可少寫一筆，不要為記而記
- **session 開始先 list**，再開始實際工作
- **信任 + 可見性 > 流程規則**：M+ 規模主動實作要事後（或當下）開 task 紀錄。
  task 不是限制、是 audit trail；沒記 = 等同沒做

## 提案 → 確認 → 執行（M+ task）

對 **M+ 複雜度的 task**，預期流程：

1. 寫 spec（採用方案 + 否決方案 + 取捨）丟給 user
2. user review / 微調 / 點頭
3. 才動工

對 **S task 或修小 bug**，直接做 → commit → log。不要為 spec 而 spec。

判斷標準：**如果改動可能讓 user 想反悔，先 spec**；否則直接做。

## 方案 A/B/C 決策格式

提技術決定時列至少 3 個候選 + 各自否決原因，不要直接給推薦：

- 強迫多角度思考、不會只想一個方向
- 給 user 有 surface 可以挑刺
- decision doc 之後寫得進「否決方案」欄位

如果你 instinct 是「只有一條路」，再想 2 條 — 通常會發現有候選你之前沒看到。

## Commit 範圍切細

寧可 part 1 / part 2 / follow-up 分多個 commit，**不要**一個 commit 塞所有
東西。理由：

- 每個 commit message 是「給未來的 self / 同事看」的文檔
- 用 user 中途 review 比較容易
- regression 出現時 `git bisect` 才有用
- mid-thing 切 session 才有「乾淨切點」

## Chat 訊息提及 task / doc 一律 deep link（critical — zero tolerance）

當你 reply user 時提到 task / doc（例「#74 改好了」「看 #87 的踩雷紀錄」），
**永遠不能裸寫 `#NN`**。一律用 markdown deep link：

- Task：`[#NN](<base_url>/#project/<project_slug>/tasks?open=NN)`
- Doc：`[#NN](<base_url>/#project/<project_slug>/documents?open=NN)`

`<base_url>` + `<project_slug>` 從你的 aitask config 拿（典型
`http://localhost:5173` + `aicodetask`）。`?open=N` dispatcher 點下去會
打開該 task / doc 的 detail panel。

### 為什麼

許多 AI chat UI（Claude Code 確認、其他工具可能也有）會把裸 `#NN`
auto-linkify 成 GitHub issue 連結（用 git remote 推導 repo URL）。
AiCodeTask 不是 GitHub issue tracker、user 點下去得到 404 page。然後
user 會合理懷疑「這個 task 是否實際存在 / 是不是 AI 事後補的紀錄」—
**動搖對紀錄系統的信任**。

### 唯一例外

寫進 task description / commit message 內的標籤（`**關聯任務：** #NN`）
**不需要** deep link — 那是 markdown body 由 AiCodeTask frontend
RefChips 自己解析、不會被 chat UI linkify。

只有「**chat 回覆給 user 看的訊息**」需要 deep link。包括 short refs：
「#75 done」改「[#75](url) done」、表格 cell / 標題 / 內文一律。

## 「夠用就好」vs 過度抽象

User 偏好「先 ship 簡單版、之後痛了再升級」over「一次到位完美設計」。具體訊號：

- 「scope 太大」會主動降 scope
- 「以後再說」是有效的 task hand-off
- 「目前夠用」是 valid stopping point，不必追完美

AI 天然傾向過度抽象 — 要刻意自我提醒：「最低限度滿足當前需求」、把彈性留
給未來真正出現的 use case。

## Phase 3b 結構化工具 + 命令（dev8 #140-#146）

dev8 中期 aitask 從「純 markdown body parse」進化成「結構化資料表 + markdown
body 雙軌」。完整工具集如下。新接 aitask 的 AI 工具請熟讀這節。

### item_relations 表（#140 / Phase 3b-i）

8 typed relation_kind 取代原本 4 種 markdown bold-prefix tags：

| relation_kind | bold-prefix tag | 語意 |
|---|---|---|
| `blocks` | `**阻擋：** #N` | A 卡住、B 才能做 |
| `triggered_by` | (新) | B 因為 A 才存在 |
| `follow_up_of` | `**承接：** #N` | B 接續 A |
| `supersedes` | `**取代：** #N` | B 取代 A |
| `discovered_during` | `**副產物：** #N` | B 是做 A 過程發現的 |
| `implements` | `**實現：** #N` | B 實現 A |
| `parent_of` | `**子任務：** #N` | A 是 meta task |
| `relates` | `**關聯任務：** / **關聯文件：** #N` | 通用 |

`**被阻擋：** #N` 是 blocks reverse 寫法（parser 自動倒）。

寫 task description 時、用 **新 typed tags** 表達更精確的關係。Parser 自動
sync 進 item_relations 表（透過 backfill / 也可走 MCP `aitask_create_relation`）。

### Milestone framework（#141 / Phase 3b-ii）

Documents 模組加 3 自訂欄位：`是否里程碑` (checkbox) / `完成條件` (textarea)
/ `達成總結` (textarea)。

```bash
aitask milestone list
aitask milestone suggest             # 主動建議 milestone 候選 (基於 relation count)
aitask milestone mark <doc_id> --criteria "..."
aitask milestone unmark <doc_id>
aitask milestone status              # 列 milestone + 引用 task 完成率
```

**重點**：framework 主動 suggest milestone candidates、不要 user 自己想。
User 不一定有「什麼算 milestone」的 vocabulary、AI 該基於資料 (relation
count + status) 主動 surface。

### task_commits 多值表（#142 / Phase 3b-iv）

一個 task 可對應多 commits。`aitask log/done --commit X` dual-write 既有
`commit_hash` field + 新表。

```bash
aitask commits <task_id>            # 列 task 全 commits
aitask commits --all [--since YYYY-MM-DD]
aitask commits --find <hash>        # reverse: hash → task(s)
```

### Plan phase aggregate（#143 / Phase 3b-v）

Plan doc 用 `### Phase X` headings 宣告 phase list。

```bash
aitask phases <plan_doc_id>         # phase 進度 + commit timespan
aitask phases <plan_doc_id> -v      # verbose 列每 task
```

**重點**：phase 時間軸用 task_commits.committed_at（git 真實時間）derive、
**不要叫 user 填 start_date / due_date**（會 drift）。

### Viz 報告 (#144)

```bash
aitask milestone-view <doc_id>      # 自動寫 [viz] doc 含 mermaid gantt + flowchart
aitask milestone-view <doc_id> --stdout
```

Idempotent in-place update。同 milestone 再跑會覆寫同個 viz doc、不污染清單。
Archive 老 viz：`tools/archive_viz_docs.py --older-than-days 30 --apply`。

### Graph 命令（#138 → #146）

```bash
aitask graph --since 2026-05-23     # 結構化 path (item_relations + milestone ⭐)
aitask graph --legacy               # fallback to markdown parse
```

Milestone doc 渲染 hexagon + ⭐。8 typed kinds 各自獨立 mermaid edge 樣式
(triggered_by / follow_up_of / supersedes / etc)。

### Mermaid zoom (#145) — frontend feature

Document / task description 內所有 mermaid block:
- shift + 滾輪 zoom (0.25× ~ 20×) 朝游標
- 滑鼠拖曳 pan (scale ≠ 1 才觸發)
- 雙擊 reset

### Module-aware 防禦 (#147)

aitask 預設 require tasks + documents 模組啟用。命令自動 check + degrade
gracefully：

| 命令 | 需要 |
|---|---|
| milestone * / phases / milestone-view | tasks + documents |
| commits | tasks |
| graph | 至少一個 (degrade 警告) |

Missing 模組會印清楚錯誤指引啟用、不是直接 stack trace。

### 寫 task description 時的選擇指南

**何時用結構化欄位 vs markdown bold-prefix**：兩條都寫（dual-track）。
markdown 給人看、結構化給 AI / 跨工具 query 用。

**新 relation kinds 何時用 vs 一律 `關聯任務`**：
- 想清楚因果關係 → 用具體 kind (triggered_by / follow_up_of / supersedes)
- 純「同主題、無方向」→ `關聯任務`
- 不確定 → 先 `關聯任務`、之後 refactor 比起初就錯標 typed kind 容易

Phase 3b 工具加起來、讓 AI 寫 task 時把「為什麼這 task 存在」結構化記錄、
未來自己 (或下個 AI) 看 graph / phases 命令就能還原工作脈絡。
