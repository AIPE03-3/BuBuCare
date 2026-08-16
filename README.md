# merge/cutover-and-netdata（整合分支，尚未併入 main，先單獨留著）

這不是單一功能分支，是把 5 個已經各自做完、驗證過的功能疊在一起的**整合分支**，
先在這裡跑過一輪再考慮要不要正式對 main 發 PR。目前**刻意不合併**，純粹保留內容。

## 裡面裝了什麼（依時間順序）

| 功能 | commit | 說明 |
|---|---|---|
| agent consumer 一次只取一則 | `ab1c485` | 修四台相機量大時，consumer 被 Kafka 踢出 group 的缺陷（`max_poll_records=1`） |
| VLM 二審判讀事後補寫 | `69f1cf1` | 判讀結果補寫回同一筆事件，前端警示視窗就地更新 |
| 四宮格 demo 影片牆 | `117abae` | 四台各播各的 `test_demo` 影片，串流斷線自動重連 |
| Netdata 機器層監控 | `a71fcc7` | 記錄原生 Netdata 安裝與 Triton 指標接線的文件 |
| 二審 cutover 到 LangGraph | `9242aa0` | 原 PR #36（已關閉）的內容——正式二審從 `ai/vlm_worker.py` 換成 `agent/`，並修掉快照全空白、多人跌倒分不清人數這兩個 cutover 後一定會壞的點 |

領先 main 11 顆 commit、落後 main 3 顆。原本各自獨立的 5 支來源分支
（`feat/agent-cutover`、`fix/agent-poll-records`、`feat/alert-vlm-enrichment`、
`feat/demo-video-wall`、`feat/netdata-machine-monitoring`）內容已完整收在這裡，
那幾支分支已刪除，不會遺失任何東西。

## 跟目前 main 的關係，有一點要注意

落後的那 3 顆 main commit 裡包含 2026-08-10 移除 `al_curator` 主動學習節點的重構
（PR #38）。這支分支是在那之前分岔出去的，所以還帶著 `agent/nodes/al_curator.py`
等舊檔案。用 `git merge-tree` 模擬過真的合併進 main：**沒有文字衝突**（兩邊改到
`agent/schemas.py`、`agent/main.py` 的地方剛好是不同段落），但**合乾淨不等於語意對**——
真要合併前務必照專案慣例跑一次 `agent` pytest + `backend` pytest +
`python3 scripts/check_guardrails.py`，再實際起服務打一次 API 驗證。

## 之後真的要推進

從這支對 main 開 PR（會涵蓋上面 5 項功能），不用再回頭處理已刪除的那 5 支來源分支。

---

專案完整說明請看 main 分支的 [README.md](../../blob/main/README.md) 與
[`CLAUDE.md`](../../blob/main/CLAUDE.md)——這份是分支專屬的狀態說明，不是專案總覽。
