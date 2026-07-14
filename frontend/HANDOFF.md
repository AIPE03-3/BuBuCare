# HANDOFF — 前端 repo 交接文件

更新時間：2026-07-14，由 Claude Code 掃描 repo 產出

> 讀者設定：接手組長（非資深工程師）。專有名詞第一次出現時會用一句話解釋。
> 本文件只記「實際程式碼 vs 規格文件」的比對結果，**不代表任何規格已變更**。
> ⚠ 兩個後端 repo（凱莉／宗翰）本機沒有整合包，**後端現況未能實機比對，一律以 `docs/現行規格/04_後端現況與規格落差.md`（下稱 04 檔）記載為準**。
> 檔案路徑一律從專案根目錄（`fulilian_iniSpan/`，即本檔所在位置）起算。

---

## 一、專案現況一句話總覽

**一句話**：畫面骨架與八成頁面已完成、事件推播（SSE）與三支事件端點已接真後端，但「事件詳情頁、結案視窗（含草稿保護）、設定頁」還是空殼，且登入目前仍走 mock 驗證碼（帳密登入程式已寫好、開關沒切）。

### 各頁面實作狀態

| 頁面（IA 編號） | 檔案 | 狀態 | 備註 |
|---|---|---|---|
| 登入 | [src/pages/Login.tsx](src/pages/Login.tsx)、[src/components/LoginForm.tsx](src/components/LoginForm.tsx) | ⚠ 雙軌 | Email 驗證碼（mock，demo 碼 123456）流程完整；帳密登入表單（LoginForm.tsx:225）已寫好，但 `AUTH_MODE` 未切換（見第二節 B-2） |
| 首頁總覽（1） | [src/pages/Home.tsx](src/pages/Home.tsx) | ✅ 大致完成 | 版面 B 三分區＋KPI×4＋全螢幕警示；細節落差見第三節 |
| 即時監控（2-1/2-3 部分） | [src/pages/Monitoring.tsx](src/pages/Monitoring.tsx) | 🔶 半成品 | 總覽牆（下拉篩區域＋2 欄縮圖＋偵測中紅框）完成；**單路詳情頁與 Debug 資訊卡（2-2/2-4）完全沒做**（[CameraCard.tsx:15](src/components/CameraCard.tsx#L15) 留 TODO） |
| 事件中心・即時處理（3-1） | [src/pages/EventCenterLive.tsx](src/pages/EventCenterLive.tsx) | 🔶 半成品 | 清單＋狀態篩選有了；缺「誤報」獨立篩選、時間／區域篩選、派工追蹤欄位（見第三節 #12） |
| 事件中心・歷史查詢（3-7） | [src/pages/EventCenterHistory.tsx](src/pages/EventCenterHistory.tsx) | ✅ 完成 | 30 天堆疊圖＋安靜版篩選＋頁碼分頁；「處理耗時」欄暫顯「—」（等後端結案時間欄位） |
| 事件詳情（3-2） | [src/pages/EventDetail.tsx](src/pages/EventDetail.tsx) | ❌ 空殼 | 只有標題／狀態標籤／發生時間。03 檔 §10 規格的影片播放器、VLM 複判卡、三顆操作鈕、派工升級區塊**全部沒做** |
| 結案視窗＋草稿保護（03 檔 7-補） | 無對應檔案 | ❌ 未做 | 「回報完成」按鈕目前只印 console.log（[InProgressRow.tsx:38](src/components/InProgressRow.tsx#L38)）；全案 grep 不到 `draft:` localStorage 邏輯 |
| 環境安全總覽／詳情（4-1~4-5） | [src/pages/EnvSafety.tsx](src/pages/EnvSafety.tsx)、[src/pages/EnvScoreDetail.tsx](src/pages/EnvScoreDetail.tsx) | ✅ 完成 | 不對稱版面、離線歸「需要注意」、四向度進度條、趨勢＋異常紀錄都有 |
| 歷史紀錄（7-2/7-3/7-4 三頁籤） | [src/pages/History.tsx](src/pages/History.tsx)、[EnvScoreHistory.tsx](src/pages/EnvScoreHistory.tsx)、[NotificationHistory.tsx](src/pages/NotificationHistory.tsx)、[MediaDownloads.tsx](src/pages/MediaDownloads.tsx) | ✅ 完成 | 評分歷史含離線虛線橋接／空心圓；通報紀錄 admin 限定；影像下載含批次勾選 |
| MLOps 面板 4 頁籤（6-1~6-7） | [src/pages/MLOps.tsx](src/pages/MLOps.tsx)＋[src/pages/mlops/](src/pages/mlops/) | ✅ 完成 | 每日效能／HNP／模型版本／固定測試集皆有完整畫面（全 mock） |
| 設定（8） | [src/pages/Settings.tsx](src/pages/Settings.tsx) | ❌ 空殼 | 只有一行標題，8-1~8-7 子功能皆無 |
| 系統（9） | 無檔案、無路由 | ❌ 未做 | 側欄（[AppLayout.tsx:26-59](src/components/AppLayout.tsx#L26-L59)）完全沒有「系統」節點 |
| Agent 洞察（5） | [AppLayout.tsx:49-52](src/components/AppLayout.tsx#L49-L52) | ⬜ 依規格佔位 | 灰階＋「即將推出」，符合規格 |

### 與 03 檔「尚未著手的畫面」清單的落差

03 檔清單有 5 項，實際比對後有 3 項對不上：

| 03 檔說「尚未著手」 | code 實況 | 判定 |
|---|---|---|
| 3-3 標記誤報後的類型選擇子流程「尚未畫」 | **已經做出來了**：[SuppressConfirmModal.tsx](src/components/SuppressConfirmModal.tsx)（影片播畢解鎖＋類型必選＋備註） | 文件過時，建議更新 03 檔 |
| 3-6 冷卻與抑制紀錄「列表頁已預留 admin 入口」 | 事件中心頁面裡**找不到任何 3-6 入口**（[EventCenter.tsx](src/pages/EventCenter.tsx) 只有兩個模式頁籤） | 文件與 code 不符，待確認 |
| 登入頁「依帳號密碼方式設計尚未畫」 | 帳密登入表單已實作（[LoginForm.tsx:225-295](src/components/LoginForm.tsx#L225-L295)），只是未啟用 | 文件過時 |

另外兩個**該列而沒列**的缺口：事件詳情頁（上表 ❌）與結案視窗（上表 ❌），03 檔把它們寫成已定案規格，但 code 尚未動工，接手者容易誤以為做完了。

---

## 二、尚未拍板定案／待討論清單

### A. 04 檔 C 段開放問題 #1–#24 逐條對 code

（「卡在哪」欄用白話說明：這題不解決，畫面或功能會停在什麼狀態）

| # | 問題（白話） | code 目前怎麼頂著 | 不解決會卡在哪 | 待誰 |
|---|---|---|---|---|
| 1 | 評分歷史聚合前端算還是後端算 | 前端自己聚合（取最低分）：[src/api/envScores.ts:155-195](src/api/envScores.ts#L155-L195)＋[src/utils/envOfflinePeriods.ts:8-15](src/utils/envOfflinePeriods.ts#L8-L15) | 接真後端時不知道該傳參數還是繼續前端算，資料層要重寫一次 | 後端 |
| 2 | Zone 與後端 location 表是否同一件事 | `Camera.zone` 就是一個字串（[src/types/index.ts:46](src/types/index.ts#L46)）；SSE 進來的 `location` 字串直接當 zone 用（[src/api/events.ts:54-60](src/api/events.ts#L54-L60)，字串／物件兩種格式都先接住） | 區域篩選、分組全靠這個字串，格式一變全頁面跟著變 | 後端 |
| 3 | floors 是否多租戶 | `floor` 全部 null、demo 一律不顯示（mock/cameras.json 全 null；有值才顯示的邏輯在 [MediaDownloads.tsx:45-49](src/pages/MediaDownloads.tsx#L45-L49)） | 目前不卡畫面，只卡未來多樓層機構 | 後端 |
| 4 | 換新機是同一實體還是獨立實體 | 前端暫定「同一顆延續」，寫在 [src/utils/envOfflinePeriods.ts:40-41](src/utils/envOfflinePeriods.ts#L40-L41) 的 TODO | 評分歷史序列的連續性；若後端判獨立實體，歷史圖要切斷重畫 | 產品／後端 |
| 5 | devices.status 有沒有分「離線／已停用」 | 前端先做三態（[src/types/index.ts:41](src/types/index.ts#L41)）；mock 資料兩種都有；選擇器排除 disabled（[EnvScoreHistory.tsx:43](src/pages/EnvScoreHistory.tsx#L43)、[CameraPickerWithAll.tsx:17](src/components/CameraPickerWithAll.tsx#L17)）；監控牆兩者都當離線畫（[CameraCard.tsx:10-11](src/components/CameraCard.tsx#L10-L11)） | 接真裝置清單時若後端只有一種「不在線」，排除邏輯會失準 | 後端 |
| 6 | ~~四或五向度~~ | ✅ 已解除；code 已是四向度（[src/types/index.ts:115-120](src/types/index.ts#L115-L120)、[EnvScoreDetail.tsx:16-21](src/pages/EnvScoreDetail.tsx#L16-L21)） | — | — |
| 7 | 「較昨日降 N 分」基準是否對齊 score_drop | 總覽卡用 mock 的 `previous_score` 自算（[src/utils/envScore.ts:10-14](src/utils/envScore.ts#L10-L14)）；⚠ 另外發現 mock 與顯示層對 score_drop 正負號定義相反（見第三節 #1，是 bug） | 數字方向可能顯示相反，誤導值班判斷 | 後端＋前端 |
| 8 | 模型版本要不要加「訓練中」狀態 | 型別先鎖三態並註記（[src/types/index.ts:229-230](src/types/index.ts#L229-L230)）；手動觸發 Fine-tune 只彈 toast（[ModelVersionsTab.tsx:96-99](src/pages/mlops/ModelVersionsTab.tsx#L96-L99)） | 觸發後畫面看不出「正在訓練」，使用者會重複按 | 後端 |
| 9 | ~~警示蓋掉處置紀錄怎麼辦~~ | 04 檔標「✅ 已解除（localStorage 草稿）」，**但 code 完全沒有實作**：全案 grep 不到草稿邏輯，結案視窗本身也不存在 | 規格拍板了、東西沒做，接手者要把它排進開發序 | 前端（排程） |
| 10 | 判斷中角標要不要顯示信心變化 | 角標是寫死的假資料，只列兩個地點（[JudgingBadge.tsx:3](src/components/JudgingBadge.tsx#L3)） | 只是展示假象，不卡其他功能 | 產品 |
| 11 | 離線歸「需要注意」與 IA 4-1 矛盾 | code 照新決策：離線歸需要注意區（[src/utils/groupEnvScores.ts:14](src/utils/groupEnvScores.ts#L14)、[EnvSafety.tsx:28](src/pages/EnvSafety.tsx#L28)） | 純文件同步問題，不卡 code | 產品／IA 維護者 |
| 12 | 環境評分要不要做真分數版 | 全 mock 有分數；型別容忍 `total_score: null` 過渡（[src/types/index.ts:114](src/types/index.ts#L114)） | 後端如果維持二分文字，整個環境安全頁只能繼續 demo | 組長 |
| 13 | 多人同時看警示，A 確認後 B 會不會同步關 | **不會**：警示清單是各瀏覽器本地 state，SSE 的 event_updated 只更新列表、不會移除已彈出的警示（[EventsProvider.tsx:63-71](src/hooks/EventsProvider.tsx#L63-L71) 只在 pending 時加入，沒有移除分支） | 多站點值班時 B 的警示會殘留，可能兩人重複出動 | 產品／前端 |
| 14 | resolve 是否接受處置紀錄內文與「已送醫」旗標 | 結案只打空 body 的 `PATCH /events/{id}/resolve`（[src/api/events.ts:215](src/api/events.ts#L215)）；誤報的類型／備註先印 log 不上傳（[events.ts:209-214](src/api/events.ts#L209-L214)） | 結案視窗做出來後，內容沒地方送 | 後端（凱莉） |
| 15 | /me 端點與員工編號 | `employeeCode` 固定 null（[src/hooks/useCurrentUser.ts:13-15](src/hooks/useCurrentUser.ts#L13-L15)）；姓名暫用 JWT 的 `sub`（[employeePassword.ts:57](src/api/auth/employeePassword.ts#L57)） | 首頁「值班中：姓名（員工編號）」顯示不完整；也卡 v1.43 開發排序第③項 | 後端（凱莉） |
| 16 | REGULATED 列管狀態 | 完全未實作（型別、UI 都沒有），符合「提案階段暫不開發」 | 重大事件通報追蹤整條路徑沒有 | 後端（凱莉）＋產品 |
| 17 | 推播最終走 WS 還是 SSE；升級通知離線可達管道 | 已實作 SSE：`GET /stream?token=...`（[src/hooks/useEventSocket.ts:39](src/hooks/useEventSocket.ts#L39)，用 fetch-event-source 繞 ngrok 攔截頁） | SSE 已能動；升級通知管道（#24）仍空白 | 後端（凱莉） |
| 18 | 草稿要不要後端同步 | 未實作（連前端 localStorage 版都還沒有，見 #9） | 同 #9 | 後端（凱莉） |
| 19 | 「通知人員前往」無後端端點 | 佔位函式只印 log（[src/services/eventActions.ts:2-4](src/services/eventActions.ts#L2-L4)）；按了跳「功能串接中」toast（[FullScreenAlert.tsx:177-181](src/components/FullScreenAlert.tsx#L177-L181)） | 警示三顆按鈕的中間那顆是假的 | 後端（凱莉） |
| 20 | ~~五態↔三態映射~~ | ✅ 已解除（採對齊三態）；「需要行動」改判 `pending 且 assignee 為 null`（[src/utils/groupEventsForHome.ts:13](src/utils/groupEventsForHome.ts#L13)），「曾升級」降為旗子（[src/utils/eventFlags.ts:3-5](src/utils/eventFlags.ts#L3-L5)） | — | — |
| 21 | 列管觸發條件 | 未實作（同 #16） | 同 #16 | 產品 |
| 22 | 監控頁骨架／追蹤框與 Debug 卡 | 紅框＋「偵測中」標籤有做（[CameraCard.tsx:21-25](src/components/CameraCard.tsx#L21-L25)）；**Debug 文字資訊卡沒做、keypoints/bbox 欄位也沒預留**（types 裡找不到），與 04 檔 #22 寫的暫行方案不符 | 04 檔說好的 MVP 內容缺一半；staff/admin 的 Debug 權限規則也無從掛 | 產品／前端 |
| 23 | 監控頁版面與 stream_url 聯合型別 | ✅ 照決策做：`StreamSource` 型別（[src/types/index.ts:34-37](src/types/index.ts#L34-L37)）、只實作 null 占位分支（[CameraCard.tsx:27-32](src/components/CameraCard.tsx#L27-L32)）、下拉篩選＋固定 2 欄（[Monitoring.tsx:34-46, 58](src/pages/Monitoring.tsx#L34-L58)） | 待後端定串流格式後補 snapshot/hls 分支 | 前端 |
| 24 | Web Push 範圍限縮 | 前端沒有任何 Web Push 實作（無 service worker）；通報紀錄頁全 mock | 通報紀錄頁只能展示假資料；升級通知管道懸空 | 產品／組長 |

### B. 04 檔已記、code 佐證「還沒動」的兩件事（04 檔 B/F 段）

| 項 | code 現況 |
|---|---|
| B-2／F-b：AUTH_MODE 未切帳密 | `AUTH_MODE = 'email_otp'`（[src/config/app.ts:2](src/config/app.ts#L2)）。帳密 provider（真後端 `/login`，OAuth2 form）已完成於 [src/api/auth/employeePassword.ts](src/api/auth/employeePassword.ts)，改一行常數即可切換 |
| F-a：alerted_at 徽章語意 | 實作其實**已用 v1.43 新判定**（alerted_at 或 escalated_to 任一非 null，[src/utils/eventFlags.ts](src/utils/eventFlags.ts)），但 CLAUDE.md:161 與 [src/types/index.ts:75](src/types/index.ts#L75) 的註解還是舊語意文字，待同步 |

### C. 04 檔沒記、掃 code 新發現的待拍板項

| # | 新發現 | 位置 | 不解決會卡在哪 | 建議找誰 |
|---|---|---|---|---|
| N1 | **mock 登入的 token 會拿去連真後端 SSE**：目前登入發的是 `mock-token-…`（[emailOtp.ts:30](src/api/auth/emailOtp.ts#L30)），而 SSE 與 /ack、/verdict、/resolve 都帶這個 token 打真後端 | [useEventSocket.ts:39](src/hooks/useEventSocket.ts#L39)、[client.ts:11-20](src/api/client.ts#L11-L20) | 後端驗 JWT 的話，即時推播與三支事件端點在 demo 環境全部失效；本質上就是「B-2 何時切換」要先拍板 | 組長 |
| N2 | 事件初始清單仍走 mock，沒接已存在的 `GET /events`：04 檔 G 段說端點可用（一次全撈），code 註解也自己承認「待就緒再切」 | [EventsProvider.tsx:52-58](src/hooks/EventsProvider.tsx#L52-L58)、[events.ts:180-197](src/api/events.ts#L180-L197) | 重新整理頁面後看到的是假事件，只有 SSE 新推的是真的，兩邊會混在同一張清單 | 組長＋凱莉（確認端點真的可撈） |
| N3 | 標記誤報實際打的是 `PATCH /events/{id}/verdict`＋`/resolve` 兩支，但 02 檔 API 清單寫的是 `POST /events/{id}/feedback`，04 檔 G 段也沒列 verdict 端點 | [events.ts:214-215](src/api/events.ts#L214-L215) | 哪個端點才存在？接錯就 404 | 凱莉 |
| N4 | 「接手」沒有後端端點：`/ack` 是送達確認不是接手（code 註解寫得很清楚），接手目前純前端改狀態，「復原」也只是前端回滾 | [EventsProvider.tsx:103-137](src/hooks/EventsProvider.tsx#L103-L137)；02 檔有 `PATCH /acknowledge` 但 04 檔 G 段未確認 | 換人接手、跨裝置同步、重整頁面後接手狀態全部消失 | 凱莉 |
| N5 | 警示「逾時自動收合」與「延遲 10 秒跳出」未實作：03 檔 §7 寫的常數 `ESCALATION_OVERDUE_MS`、`CONFIRMED_ALERT_DELAY_MS` 在 code 裡**不存在**（grep 無），只有 `ACK_DEADLINE_OFFSET_MS = 90000`（[events.ts:148](src/api/events.ts#L148)）與 `ACK_TOAST_DURATION_MS = 10000`（[EventsProvider.tsx:11](src/hooks/EventsProvider.tsx#L11)） | [FullScreenAlert.tsx](src/components/FullScreenAlert.tsx)（無倒數收合邏輯） | 警示永遠不會自動收合進「需要行動」區，03 檔寫的完整流程走不通；03 檔「程式碼常數現值」的描述也是錯的 | 組長（排程）＋文件更新 |
| N6 | SSE 進來的 pending 事件**立刻**觸發全螢幕警示，沒有區分規格的「階段一判斷中／階段二已確認」 | [EventsProvider.tsx:68-70](src/hooks/EventsProvider.tsx#L68-L70) | 若後端會推「還在 VLM 複判中」的事件，值班人員會被未確認事件的全螢幕警示轟炸 | 凱莉（確認後端只推已確認事件）＋產品 |
| N7 | 技術堆疊文件過時：package.json 實際是 React 19.2 與 react-router-dom 7.18，CLAUDE.md 與 00 檔寫 React 18＋router v6 | [package.json](package.json) | 新人照文件查 API 版本會查錯；升級是否刻意為之需確認 | 組長 |
| N8 | HNP「匯出全部」被做成 disabled（提示「後端資料飛輪管道尚未就緒」），但 03 檔 13-補 說「MVP 先觸發 mock 檔案下載」 | [HardNegativePoolTab.tsx:134-142](src/pages/mlops/HardNegativePoolTab.tsx#L134-L142) | demo 時這顆按鈕按不了；兩份文件（00 動工決策 vs 03）指示互相矛盾 | 組長 |

---

## 三、程式碼小瑕疵清單

（規格文件不會寫的東西：不一致、沒做完、疑似 bug。**皆未動手修**，附建議修法供排單。）

### 疑似 bug（優先看）

| # | 位置 | 問題 | 影響（白話） | 建議修法 |
|---|---|---|---|---|
| 1 | [src/api/envScores.ts:184-185](src/api/envScores.ts#L184-L185) vs [src/pages/EnvScoreHistory.tsx:384-391](src/pages/EnvScoreHistory.tsx#L384-L391) | `score_drop` 正負號兩邊定義相反：mock 算的是「本次−前次」（漲分為正），表格顯示卻把正值畫成「-N」、負值畫成「+N」 | 評分歷史表的「較前次變化」欄**漲跌方向顯示顛倒**，值班者會把惡化看成改善 | 兩邊擇一定義（建議跟後端 score_drop 定義一起定，見第二節 #7），再統一顯示邏輯 |
| 2 | [src/utils/groupEventsForHome.ts:16-17](src/utils/groupEventsForHome.ts#L16-L17) | 「今日已結案」「今日另有 N 筆誤報」實際**沒有過濾日期**，撈的是清單裡所有 resolved（mock 資料橫跨 6/11–7/9，沒有一筆是今天） | 首頁「今日」區塊顯示的是歷史事件，數字全錯 | 加上 occurred_at 為當日的過濾條件 |
| 3 | [src/pages/EventDetail.tsx:57](src/pages/EventDetail.tsx#L57) | StatusTag 沒傳 `verdict`，誤報事件在詳情頁會顯示綠底「已結案」而非灰框「誤報」 | 同一筆事件在清單標「誤報」、點進詳情變「已結案」，前後矛盾 | 補傳 `verdict={event.verdict}`（比照 [EventCenterHistory.tsx:198](src/pages/EventCenterHistory.tsx#L198)） |

### 元件／行為不一致

| # | 位置 | 問題 | 影響 | 建議修法 |
|---|---|---|---|---|
| 4 | [HardNegativePoolTab.tsx:26](src/pages/mlops/HardNegativePoolTab.tsx#L26) vs [EventCenterHistory.tsx:39-43](src/pages/EventCenterHistory.tsx#L39-L43)、[NotificationHistory.tsx:36-40](src/pages/NotificationHistory.tsx#L36-L40) | 時間篩選「今天」定義不一致：HNP 頁＝「過去 24 小時」，其他頁＝「當日 00:00 起」 | 同一個「今天」選項在不同頁撈到的資料範圍不同 | 抽共用的 `rangeToDates` util（目前這段程式在 3 個頁面各複製一份） |
| 5 | [EventCenterHistory.tsx:37-54](src/pages/EventCenterHistory.tsx#L37-L54)、[NotificationHistory.tsx:34-51](src/pages/NotificationHistory.tsx#L34-L51)、[HardNegativePoolTab.tsx:24-31](src/pages/mlops/HardNegativePoolTab.tsx#L24-L31) | 「今天／近 7 天／近 30 天／自訂」整組篩選 UI＋換算邏輯複製了 3 份（環境歷史頁又是第 4 種寫法） | 改一處漏三處；上面 #4 就是這樣長出來的 | 抽成共用元件＋util |
| 6 | [EnvScoreHistory.tsx:32-90](src/pages/EnvScoreHistory.tsx#L32-L90)（頁內私有 CameraPicker） vs [CameraPickerWithAll.tsx](src/components/CameraPickerWithAll.tsx) | 兩個幾乎一樣的攝影機選擇器：一個在頁面檔內、一個是共用元件（只差「全部攝影機」選項） | 樣式改版要改兩處 | 讓 EnvScoreHistory 改用 CameraPickerWithAll（加 prop 隱藏「全部」選項）或反向合併 |
| 7 | [HardNegativePoolTab.tsx:95](src/pages/mlops/HardNegativePoolTab.tsx#L95) | 誤報類型篩選用 QuietFilterPills（攤開膠囊），但 03 檔 13-補與通則都說「數量會持續成長的選項用**下拉**」 | 類型變多會跑版；與規格明文不符 | 改安靜版下拉，或請組長改規格 |
| 8 | [MediaDownloads.tsx:51-74](src/pages/MediaDownloads.tsx#L51-L74)、[HardNegativePoolTab.tsx:22](src/pages/mlops/HardNegativePoolTab.tsx#L22)、[ModelVersionsTab.tsx:8-12](src/pages/mlops/ModelVersionsTab.tsx#L8-L12) | 三處自己手刻狀態標籤樣式（複製 StatusTag 的視覺），沒共用元件 | StatusTag 配色規則改版時這三處不會跟著動 | 把「灰字空心外框」等樣式抽成共用 Tag 元件或常數 |
| 9 | [MediaDownloads.tsx](src/pages/MediaDownloads.tsx)（無分頁） vs 其他回顧頁皆有靜態頁碼 | 影像片段下載頁沒有分頁，資料多了會無限長 | 與「回顧頁用靜態頁碼」通則不一致 | 比照其他頁補 10 筆分頁 |
| 10 | [EventCenterHistory.tsx:226-239](src/pages/EventCenterHistory.tsx#L226-L239) 等 4 處分頁 | 頁碼按鈕一律全展開（1,2,3,…,N），無省略號 | 頁數多時按鈕列爆版 | 共用一個分頁元件並加省略邏輯（分頁 UI 目前也是 4 處複製） |
| 11 | [FullScreenAlert.tsx:145-151](src/components/FullScreenAlert.tsx#L145-L151) | 「誤報」按鈕做成純文字（text-muted 無邊框），03 檔 §7 寫「--offline **外框**」 | 視覺權重比規格更低，可能被忽略 | 加 offline 色外框 |
| 12 | [EventCenterLive.tsx:9](src/pages/EventCenterLive.tsx#L9)＋[src/types/index.ts:26](src/types/index.ts#L26) | 即時處理篩選只有「全部／處理中／已結案」，缺規格明訂的「誤報」獨立篩選（誤報混在已結案裡）；也沒有時間／區域篩選、派工追蹤欄位（IA 3-1／3-4） | 值班者無法只看誤報、無法按區域篩事件 | 補 verdict 篩選膠囊與時間／區域條件 |
| 13 | [ActionRequiredCard.tsx:50](src/components/ActionRequiredCard.tsx#L50)、[EventCard.tsx:67](src/components/EventCard.tsx#L67) | 「接手」按鈕用 `--brand`；CLAUDE.md 色彩規則說「具語意的按鈕永遠用語意色」（確認前往＝success 填色。FullScreenAlert 的同語意按鈕就是 success） | 同一個動作兩種顏色，語意色規則被稀釋 | 統一為 success（或請組長認定「接手」屬中性操作） |
| 14 | [EventCard.tsx:44-53](src/components/EventCard.tsx#L44-L53) | 事件中心卡片同時顯示「通報時間（絕對）」＋「距今已過（相對）」＋信心分數；03 檔 §1 對首頁卡片明訂移除絕對時間與信心分數，事件中心卡是否比照未寫明 | 卡片資訊密度與首頁瘦身原則不一致 | 標「待確認」：請組長定事件中心卡欄位 |

### 文案／格式不一致

| # | 位置 | 問題 | 影響 | 建議修法 |
|---|---|---|---|---|
| 15 | [Home.tsx:43](src/pages/Home.tsx#L43) | 頁標寫「首頁儀表**版**」（應為「儀表板」）；側欄又叫「回首頁/總覽」（[AppLayout.tsx:27](src/components/AppLayout.tsx#L27)），規格名稱是「總覽儀表板」 | 錯字直接掛在首頁大標 | 統一為「總覽儀表板」 |
| 16 | [AppLayout.tsx:76-83](src/components/AppLayout.tsx#L76-L83) | 值班者身分顯示「您好！{姓名}」，03 檔 §1 明訂「值班中：{姓名}（{員工編號}）」（員工編號卡 #15 可先留空） | 與規格文字不符 | 改文案；員工編號留待 #15 |
| 17 | [NotificationHistory.tsx:17-18](src/pages/NotificationHistory.tsx#L17-L18) | 篩選選項硬編碼「已送達／發送失敗」，沒用已存在的 `NOTIFICATION_STATUS_LABEL`（[types/index.ts:203-205](src/types/index.ts#L203-L205)）；同類問題：[MediaDownloads.tsx:13,56](src/pages/MediaDownloads.tsx#L13)、[EventCenterHistory.tsx:17-20](src/pages/EventCenterHistory.tsx#L17-L20) 各自硬編碼「誤報」 | 改標籤文字時會漏改（正是 STATUS_LABEL 鐵律要防的事，見第四節第 3 條） | 一律引用 types 的對照表；「誤報」建議在 types 加 `VERDICT_LABEL` |
| 18 | [EventDetail.tsx:37](src/pages/EventDetail.tsx#L37)「載入中...」（三個半形點） vs [EnvScoreDetail.tsx:89](src/pages/EnvScoreDetail.tsx#L89)「載入中…」（省略號） | 載入文案兩種寫法 | 小，但看得出來沒共用 | 統一字元，順手抽共用 Loading 元件 |
| 19 | [src/utils/time.ts](src/utils/time.ts) 有共用 util，但 [FullScreenAlert.tsx:11-14](src/components/FullScreenAlert.tsx#L11-L14) 自己另寫 `formatTimeWithSeconds`；`formatDate` 只輸出 MM/DD 無年份，跨年資料無法分辨 | 時間格式化沒有全案單一出口 | 跨年後歷史頁日期會混淆 | 把含秒版收進 time.ts；formatDate 支援帶年 |
| 20 | [types/index.ts:30](src/types/index.ts#L30) `FalseReportLabel` 與 [types/index.ts:132](src/types/index.ts#L132) `HnpLabel` | 同一組值（坐地／伸展／彎腰／攙扶／其他）定義了兩個型別，DoD 明訂「無重複型別定義」 | 未來加類型要改兩處 | 併成一個（或 `type FalseReportLabel = HnpLabel`） |
| 21 | [EnvDangerCard.tsx:9](src/components/EnvDangerCard.tsx#L9)、[EnvScoreDetail.tsx:12](src/pages/EnvScoreDetail.tsx#L12)、[EnvScoreHistory.tsx:15](src/pages/EnvScoreHistory.tsx#L15) | `DANGER_THRESHOLD = 39` 複製三份（其中一份註解還自我提醒「全案一致」） | 門檻調整要改三處 | 移到 utils/envScore.ts 匯出 |
| 22 | [styles/tokens.css:7-8](src/styles/tokens.css#L7-L8) | `--info` 註解仍寫「新事件提示條」（CLAUDE.md 已改為「用途待定」）；`--overlay` 是 CLAUDE.md 色票表**沒有**的新 token | 色票唯一權威表跟實際檔案不同步 | 更新 tokens.css 註解；--overlay 補進 CLAUDE.md（走 DoD 同步流程） |
| 23 | [NewEventBanner.tsx](src/components/NewEventBanner.tsx)＋[EventsProvider.tsx:161-163](src/hooks/EventsProvider.tsx#L161-L163) | `incomingEvent` 恆為 null，新事件提示條是永遠不會出現的死程式碼（規格保留給「斷線重連補資料」情境，但該情境沒實作）；橫幅文字還寫死「有 1 筆」 | 無害但誤導接手者 | 實作重連補資料情境，或先移除並記錄 |
| 24 | [JudgingBadge.tsx:3](src/components/JudgingBadge.tsx#L3) | 「系統判斷中」角標的地點清單寫死在元件內，不像其他假資料放 `src/api/mock/` | 之後接真資料時容易被漏掉 | 資料搬到 api/mock，介面走 src/api |

### 狀態處理與響應式（逐頁盤點）

- **Loading**：只有 [EventDetail.tsx:36-38](src/pages/EventDetail.tsx#L36-L38) 與 [EnvScoreDetail.tsx:88-90](src/pages/EnvScoreDetail.tsx#L88-L90) 有「載入中」。其餘頁面（Home、EnvSafety、History 三頁籤、MLOps 四頁籤、Monitoring）都是資料到了才渲染或直接空白（如 [FixedTestSetTab.tsx:13](src/pages/mlops/FixedTestSetTab.tsx#L13) `if (!data) return null`）。mock 幾乎即時所以看不出來，接真 API 後會有閃爍或白畫面。
- **空狀態**：普遍有做（各清單頁都有「沒有符合…」文案），✅ 這塊做得一致。惟 [EventCenterLive.tsx:37](src/pages/EventCenterLive.tsx#L37) 空狀態文案寫「今日已完成」但篩選邏輯並沒有限「今日」，文字與行為不符。
- **錯誤狀態**：**全案沒有任何 API 失敗的 UI**。所有 `getXxx().then(...)` 都沒有 `.catch`（client.ts 失敗會 throw），SSE 失敗只有 console.warn。接真後端後只要一支 API 掛掉，頁面就是永遠的空白／載入中。建議至少加一個共用的錯誤提示區塊。
- **響應式（03 檔明訂 50%／100%／150% 縮放皆須可讀）**：靜態掃描可確認的部分——全螢幕警示已照規格用相對單位（`w-[78vw] max-h-[90vh]`，[FullScreenAlert.tsx:62](src/components/FullScreenAlert.tsx#L62)），彈窗類也都有 `max-h-[90vh]`。但整體版面固定值不少：側欄固定 `w-[220px]`（[AppLayout.tsx:43](src/components/AppLayout.tsx#L43)）、首頁 KPI 固定 `grid-cols-4`（[Home.tsx:51](src/pages/Home.tsx#L51)）、監控牆固定 `grid-cols-2`、登入卡固定 `w-[380px]`，全案除 flex-wrap 外**沒有任何斷點（sm:/md:/lg:）**。⚠ 是否在三種縮放下實測過，**無法純靠讀 code 驗證**，repo 內也沒有相關測試紀錄——建議接手後實機開 50%／150% 各過一輪，特別是 KPI 四欄與表格頁。
- 其他：建置會警告單一 chunk 770kB 超過 500kB（`npm run build` 輸出），demo 可忽略，正式部署建議 code-split。

---

## 四、CLAUDE.md 四條鐵律遵循檢查

（檢查方式：全案 grep＋逐檔人工確認，2026-07-14）

| 鐵律 | 結果 | 說明 |
|---|---|---|
| 1. 元件內禁止直接 fetch/axios | ⚠ 一處邊界案例 | 元件層（pages/components）**已檢查，符合**——資料都經 src/api/。唯 [src/hooks/useEventSocket.ts:39](src/hooks/useEventSocket.ts#L39) 在 hook 層直接呼叫 `fetchEventSource` 開 SSE 連線（未經 src/api/）。SSE 本來就不是一般 fetch、CLAUDE.md 也指名由 useEventSocket 負責推播，**是否算違規請組長認定**；合法使用另有 [api/client.ts:23](src/api/client.ts#L23) 與 [api/auth/employeePassword.ts:44](src/api/auth/employeePassword.ts#L44)（皆在 api 層，符合） |
| 2. 禁止寫死色碼 | ⚠ 一個灰色地帶 | hex／rgb：**已檢查，符合**（只存在於 tokens.css）。Tailwind 色名：全案有 16 處 `text-white`（如 [FilterChips.tsx:30](src/components/FilterChips.tsx#L30)、[FullScreenAlert.tsx:134](src/components/FullScreenAlert.tsx#L134)……），全部用在「語意色／brand 填色鈕的白字」上——這是 CLAUDE.md 自己要求的視覺（「success 填色白字」），但嚴格讀「禁止 Tailwind 色名」就是違規。建議定案：在 tokens 加 `--text-on-fill: #FFFFFF` 統一引用，或在 CLAUDE.md 明文豁免 white |
| 3. 事件狀態文字必走 STATUS_LABEL | ⚠ 三處繞過 | 主元件 [StatusTag.tsx](src/components/StatusTag.tsx) 正確引用 STATUS_LABEL；但「誤報」一詞沒有進對照表，散落硬編碼：[StatusTag.tsx:12](src/components/StatusTag.tsx#L12)（元件內常數，勉強可接受）、[MediaDownloads.tsx:13,56](src/pages/MediaDownloads.tsx#L13)、[EventCenterHistory.tsx:17-20](src/pages/EventCenterHistory.tsx#L17-L20)（各寫一份）。另 [NotificationHistory.tsx:17-18](src/pages/NotificationHistory.tsx#L17-L18) 繞過 NOTIFICATION_STATUS_LABEL（通報狀態非事件狀態，屬同精神違規）。建議在 types/index.ts 增設 VERDICT_LABEL 收斂 |
| 4. 登入元件禁止 import 具體 auth provider | ✅ 已檢查，符合 | [LoginForm.tsx:4](src/components/LoginForm.tsx#L4) 只 import `authProvider`（來自 src/api/auth/index.ts）；emailOtp／employeePassword 僅在 [api/auth/index.ts](src/api/auth/index.ts) 被引用 |

**DoD 附帶檢查**：`npm run build` ✅ 通過、`npm run lint` ✅ 通過（2026-07-14 實跑）。但 DoD 的「型別同步 CLAUDE.md」未完全達成：code 的 `EnvScore`、`StreamSource`、`ModelDailyMetric`、`DownloadableMedia`、`EventHistoryQuery`、`DETECTING_LABEL` 等定義（[src/types/index.ts](src/types/index.ts)）都不在 CLAUDE.md 型別區；CLAUDE.md 的 `Camera` 也缺 `stream_source` 欄位。

---

## 五、各頁面資料來源對照表

「真後端」指凱莉的 fulilian-backend（經 [src/api/client.ts](src/api/client.ts)，baseURL 目前寫死一個 ngrok 網址，[client.ts:2](src/api/client.ts#L2)，可用環境變數 `VITE_API_BASE` 覆蓋——⚠ 04 檔 G 段寫 `http://host:8000`，實際預設值是 ngrok，部署時記得設環境變數）。

| 頁面／功能 | 目前資料來源 | 對應規格章節 | 備註 |
|---|---|---|---|
| 登入 | mock（[api/auth/emailOtp.ts](src/api/auth/emailOtp.ts)，寫死兩帳號＋驗證碼 123456） | 04 檔 B-2 | ⚠ **真後端 `POST /login` 已可接**（[employeePassword.ts](src/api/auth/employeePassword.ts) 已寫好），只差切 [config/app.ts:2](src/config/app.ts#L2) 的 AUTH_MODE——**規格已定帳密、code 沒跟上** |
| 事件即時推播 | ✅ 真後端 SSE `GET /stream`（[useEventSocket.ts](src/hooks/useEventSocket.ts)），收到自動回 `POST /events/{id}/ack` 送達確認 | 04 檔 G 段 | event_created／event_updated 都吃、event_id 去重 |
| 事件初始清單／詳情 | mock（[api/mock/events.json](src/api/mock/events.json) 33 筆，經 [api/events.ts:172-197](src/api/events.ts#L172-L197)） | 04 檔 G 段 | ⚠ **04 檔 G 段說 `GET /events` 已存在（一次全撈），code 仍走 mock——沒跟上**（見第二節 N2） |
| 標記誤報／結案 | ✅ 真後端 `PATCH /events/{id}/verdict`＋`/resolve`（[api/events.ts:209-216](src/api/events.ts#L209-L216)） | 02 檔 API 清單 | ⚠ 02 檔寫的是 `/feedback`，端點名對不上（N3）；誤報類型／備註尚無欄位可送 |
| 接手／通知人員前往 | 純前端 state／console 佔位（[EventsProvider.tsx:103](src/hooks/EventsProvider.tsx#L103)、[eventActions.ts](src/services/eventActions.ts)） | 04 檔 #19 | 後端無端點 |
| 首頁 KPI ×4 | mock（[api/mock/kpi.json](src/api/mock/kpi.json)） | 03 檔 §1 | 「今日誤報率」03 檔要求改由 events 即時計算，目前直接顯示 mock 數字（[Home.tsx:53](src/pages/Home.tsx#L53)），待確認 |
| 攝影機清單（監控／各選擇器） | mock（[api/mock/cameras.json](src/api/mock/cameras.json) 12 台） | 04 檔 A-8 | 後端無 /devices 端點（[api/cameras.ts:4](src/api/cameras.ts#L4) 註明） |
| 環境安全總覽／詳情 | mock（[api/mock/envScores.json](src/api/mock/envScores.json)，相對天數展開） | 03 檔 §11、04 檔 A-6 | 後端只有二分文字無分數，卡 04 檔 #12 |
| 環境評分歷史 7-2 | mock（[api/mock/envScoreHistory.json](src/api/mock/envScoreHistory.json) 壓縮規格展開＋前端聚合） | 03 檔 §8、04 檔 C-1 | 同上 |
| 通報紀錄 7-3 | mock（[api/mock/notifications.json](src/api/mock/notifications.json)） | 03 檔 §8 | 02 檔說 notifications 表已存在，但無查詢 API 記載；Web Push 本身未實作（#24） |
| 影像片段下載 7-4 | mock（[api/mock/downloadableMedia.json](src/api/mock/downloadableMedia.json)） | 04 檔 H 段 | 待後端 expires_at／下載清單 API |
| MLOps 每日效能 6-1 | mock（[api/mlops.ts](src/api/mlops.ts) 用亂數產生器現做 30 天資料） | 03 檔 §13、04 檔 A-7 | 後端表與 API 不存在 |
| Hard Negative Pool 6-2 | mock（[api/mock/hardNegatives.ts](src/api/mock/hardNegatives.ts) 產生 18 筆） | 03 檔 13-補、04 檔 H 段 | 「人工標記」語意未拍板 |
| 模型版本管理 6-3~6-6 | mock（[api/mock/modelVersions.ts](src/api/mock/modelVersions.ts) 4 版）；promote／rollback 只印 log（[api/modelVersions.ts:10-20](src/api/modelVersions.ts#L10-L20)） | 03 檔 §13 | 後端 API 不存在 |
| 固定測試集 6-7 | mock（[api/mock/fixedTestSet.ts](src/api/mock/fixedTestSet.ts)） | 03 檔 §13 | 唯讀，後端 API 不存在 |
| 影片播放（HNP 回放／警示內嵌） | 佔位框或 public/videos/fall-demo.mp4（[FullScreenAlert.tsx:21](src/components/FullScreenAlert.tsx#L21)） | CLAUDE.md「不接真串流」 | 符合規範 |

**總結「規格說可接、code 還走 mock」的清單（接手後優先串接順序建議）**：①登入 `/login`（改一行開關＋確認 N1）→ ②事件初始清單 `GET /events`（N2）→ 其餘皆為後端未就緒，非前端沒跟上。

---

## 六、該找誰討論清單

（沿用 04 檔的人名／角色分類；粗體為本次掃描新發現，其餘為 04 檔既有項的 code 佐證）

### 找組長拍板
- B-2：AUTH_MODE 何時切帳密登入（**含新發現 N1：不切的話 SSE 與事件端點拿 mock token 打真後端，demo 會斷**）
- **N2**：事件初始清單何時從 mock 切到 `GET /events`
- **N5**：警示「逾時自動收合／延遲跳出」要不要做？不做請同步修 03 檔 §7 的常數描述
- **N7**：React 19／router 7 與文件寫 React 18／v6 的落差，是否追認升級並更新 CLAUDE.md、00 檔
- **N8**：HNP「匯出全部」要 disabled 還是 mock 下載（00 與 03 檔矛盾）
- #12：環境評分真分數版要不要做（連動宗翰）
- 第四節鐵律 2 的 `text-white` 灰色地帶、鐵律 1 的 useEventSocket 邊界案例，請認定是否違規
- 第三節 #13／#14：「接手」按鈕顏色語意、事件中心卡片欄位是否比照首頁瘦身
- CLAUDE.md 型別區與 code 的同步缺口（第四節 DoD 附帶檢查）＋ 03 檔「尚未著手」清單過時三項（第一節）

### 找後端凱莉
- **N3**：標記誤報到底是 `/verdict`＋`/resolve` 還是 `/feedback`？請給最終 API 清單
- **N4**：「接手」端點（02 檔的 `PATCH /acknowledge`）到底有沒有？沒有的話接手狀態只活在單一瀏覽器
- **N6**：SSE 會不會推「尚未確認」的事件？前端目前 pending 一律彈全螢幕警示
- #14：resolve 可否帶處置紀錄內文＋「已送醫」旗標
- #15：`/me` 端點與員工編號欄位（卡值班者身分顯示）
- #16／#17／#18／#19：列管狀態機、升級通知管道、草稿同步、「通知人員前往」端點
- #1／#2／#3／#5／#7：評分聚合參數、location／zone、floors、devices.status 三態、score_drop 定義（**連動第三節 bug #1 的正負號**）

### 找後端宗翰
- #12（與組長合議）：環境評分有沒有機會出真分數＋四向度＋risk_factors（環境安全整區資料層都在等這個）
- 04 檔 A-7：MLOps 三張表（env_safety_scores／model_versions／model_daily_metrics）與對應 API 何時有（MLOps 面板四頁籤全部走 mock 在等）
- 04 檔 H 段：Hard Negative 收集方式（YOLO 自動 vs 人工標記）與檔案存放，影響 HNP 頁全部欄位語意

### 找產品
- #4：攝影機換新機的實體認定（評分歷史序列要不要切斷）
- #10：判斷中角標要不要顯示信心變化
- #11：IA 4-1「正常含離線」要不要回頭改
- **#13＋N6**：多人同時值班的警示同步策略（A 接手後 B 的警示要不要自動關）
- #21／#24：列管觸發條件、Web Push 範圍與升級通知管道
- #22：監控頁 Debug 資訊卡與 keypoints 預留欄位（04 檔寫的暫行方案 code 只做了一半）

### 前端自己可先排單（不用等人）
- 第三節疑似 bug #1（score_drop 顯示方向——修顯示層前先跟凱莉對定義）、#2（今日未過濾）、#3（詳情頁誤報標籤）
- 第三節 #4／#5／#6／#10：時間篩選、分頁、攝影機選擇器的重複程式收斂
- 錯誤狀態 UI（全案缺）＋ Loading 一致化
- 50%／100%／150% 縮放實測（03 檔明訂，repo 內看不到測過的痕跡）
- 事件詳情頁、結案視窗＋草稿保護（規格已定案、純前端可動工，只有送出 API 的欄位要等 #14）

---

*本文件由程式碼靜態掃描產出，行號以 2026-07-14 的工作區狀態為準；後續 commit 後行號可能位移，請以檔名＋描述為主要定位依據。*
