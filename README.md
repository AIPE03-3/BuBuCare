# feat/agent-cutover（已暫緩，不會併入 main）

這支分支原本要把正式二審從 `ai/vlm_worker.py` 換成 `agent/`（LangGraph 版），對應
[PR #36](https://github.com/AIPE03-3/aipe03-3/pull/36)，**PR 已於 2026-08-16 關閉**，
分支本身保留不刪，純粹作為之後要接續這個方向時的參考。

## 為什麼暫緩

這支分支的內容（含順帶修掉的兩個 cutover 後一定會壞的點：前端事件快照全空白、多人
同時跌倒分不出人數）**已經被 `merge/cutover-and-netdata` 分支完整涵蓋**——
`git merge-base --is-ancestor feat/agent-cutover merge/cutover-and-netdata` 驗證
過，這支的每一顆 commit 都是那支的祖先，那支另外還多疊了 `fix/agent-poll-records`、
`feat/alert-vlm-enrichment`、`feat/demo-video-wall`、`feat/netdata-machine-monitoring`
四支分支的後續修正。

## 之後真的要接續 agent cutover 這件事

**不要從這支分支繼續加 commit**，改成：

1. 確認要不要合併的是 `merge/cutover-and-netdata`（內容更完整、更新）
2. 從當下最新的 main 開一支新分支，或直接把 `merge/cutover-and-netdata` 拿去對 main
   重新開 PR
3. 這支 `feat/agent-cutover` 之後可以直接刪，內容不會遺失（已經包含在
   `merge/cutover-and-netdata` 裡）

---

專案完整說明請看 main 分支的 [README.md](../../blob/main/README.md) 與
[`CLAUDE.md`](../../blob/main/CLAUDE.md)——這份是分支專屬的暫緩說明，不是專案總覽。
