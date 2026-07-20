# 前後端串接指南（fulilian-backend ⇄ 中控台前端）

> 給後端／串接同學的單一入口文件。讀完本檔即可知道：前端從哪裡打 API、哪些端點已串、哪些還是 mock、要換成真後端時改哪幾行。
> 最後更新：2026-07-18

---

## 1. 架構總覽

```
頁面元件 (src/pages, src/components)
   │  ── 禁止直接 fetch／axios（專案鐵律）
   ▼
hooks (src/hooks)        EventsProvider＝事件狀態的唯一擁有者
   │                     useEventSocket＝SSE 即時推播
   ▼
api 層 (src/api)         ★ 所有前後端接縫都集中在這一層
   │                     介面一律 async；mock 與真實 API 同介面
   ▼
fulilian-backend
```

**串接原則：只改 `src/api/` 內的實作，呼叫端（頁面／hooks）不需要動。**
所有 api 函式已刻意做成 `async`，即使目前實作是 localStorage／常數，之後換成 `fetch` 呼叫端零修改。

型別全部集中在 [src/types/index.ts](src/types/index.ts)（全案唯一定義處），後端欄位有異動先改這裡再往下追。

---

## 2. 環境設定

| 項目 | 位置 | 說明 |
|---|---|---|
| API base URL | 環境變數 `VITE_API_BASE` | 未設定時預設 ngrok 測試網址，見 [src/api/client.ts](src/api/client.ts) |
| ngrok header | `client.ts` 的 `NGROK_HEADERS` | ngrok 免費版須帶 `ngrok-skip-browser-warning: true` 繞過攔截頁；正式部署後可整組移除 |
| Auth header | `client.ts` 的 `authHeader()` | 自動從 localStorage 讀 token 塞 `Authorization: Bearer <token>`，各 api 模組不必自行處理 |

本機開發：在 `frontend/.env.local` 放 `VITE_API_BASE=http://localhost:8000`（依後端實際 port）。

---

## 3. 已串接的後端端點（現在就會真的打）

| 端點 | 呼叫處 | 說明 |
|---|---|---|
| `GET /stream?token=...`（SSE） | [src/hooks/useEventSocket.ts](src/hooks/useEventSocket.ts) | 事件即時推播，具名事件 `event_created`／`event_updated`。用 `@microsoft/fetch-event-source`（原生 EventSource 帶不了 ngrok header） |
| `POST /events/{id}/ack` | [src/api/events.ts](src/api/events.ts) `acknowledgeEvent` | **送達確認**（非「接手」）。前端一收到 SSE 事件就自動打，關掉後端每 10 秒最多 3 次的重送 |
| `PATCH /events/{id}/verdict` | `submitEventFeedback` | 標記誤報：body `{ verdict: 'false_alarm' }` |
| `PATCH /events/{id}/resolve` | `submitEventFeedback` | 誤報標記後接著結案 |

登入（email OTP）目前是**純前端 mock**（見 §5），SSE 的 token 也就是 mock token；後端若要驗 token，登入串接要先完成。

---

## 4. SSE 事件契約（RawEventPayload）

前端所有事件（SSE、測試注入）都經 [src/api/events.ts](src/api/events.ts) `parseRawEvent()` 轉成前端 `CareEvent`，**全案只有這一套轉換**。後端欄位如下：

| 欄位 | 型別 | 前端處理 |
|---|---|---|
| `event_id` | string | → `id` |
| `device_id` / `device_name` | number / string | → `camera.id` / `camera.name` |
| `location` | string **或** `{ zone, floor }` | 兩種格式都吃（runtime 判斷）；格式定案後可簡化 |
| `event_type` | string | `'hazard'` → 潛在危險（物件偵測）；其餘一律當跌倒 `'fall'` |
| `hazard_object` | string \| null（選填） | 危險物品類型；只收白名單值（刀具/熱源/藥品/玻璃碎片/積水/其他，見 `HAZARD_OBJECTS`），其餘轉 null。**後端實際欄位名未定，定案後對齊** |
| `status` | string | 已對齊三態 `pending / in_progress / resolved`，不轉換 |
| `verdict` | string \| null | 已對齊 `true_alarm / false_alarm / null` |
| `detected_at` | ISO string | **若無時區標記自動補 `+08:00`**（後端曾漏帶時區；帶 Z 或 ±hh:mm 則原樣） |
| `yolo_score` / `yolo_threshold` | number | → `confidence` |
| `vlm_summary` | string、物件 或 null | null＝YOLO 高信心直通；字串當 description；物件取 confidence/description/suggestion |
| `severity` | string \| null | 中英都吃（高/high、中/mid/medium、低/low），未知值 fallback「中」並 console.warn |
| `clip_path` / `snapshot_path` | string \| null | 原樣帶入，播放器／縮圖用 |
| `staff_id` | number \| null | 暫以「員工 #<id>」顯示，待 staff 名單端點 |
| `notified_at` / `company_id` | — | 前端目前未使用 |

**hazard 事件的前端行為**：不跳全螢幕警示、不進事件中心「事件」清單、不可寫通報單；只進「潛在危險」分頁＋首頁計數＋log。分流邏輯在 [src/hooks/EventsProvider.tsx](src/hooks/EventsProvider.tsx) `handleIncomingEvent`。

---

## 5. 尚未串接（mock）模組與替換點

每一項都只需改所列檔案內的函式實作。

| 模組 | 檔案 | 現況 | 換成後端時 |
|---|---|---|---|
| 事件初始清單 | `api/events.ts` `getEvents()` | 回空陣列，事件全靠 SSE | `GET /events` → 逐筆 `parseRawEvent` |
| 鏡頭清單 | [src/api/cameras.ts](src/api/cameras.ts) | 讀 `api/mock/cameras.json` | `GET /devices`；`updateCameraName` 目前只印 log |
| 通報單 | [src/api/reports.ts](src/api/reports.ts) | localStorage（key `fulilian_reports`），每事件一份**清單**（初報/續報/結報各自獨立一筆） | `GET/POST /events/{id}/reports`；三支函式 `saveReport / getStoredReports / getLatestReport` 已 async，呼叫端不用動 |
| 使用者管理 | [src/api/users.ts](src/api/users.ts) | localStorage（key `fulilian_users`，首次由 `mock/users.json` seed）；密碼 demo 明文暫存 | `GET /users`、`PATCH /users/{id}`；**密碼一律後端雜湊，前端不留存** |
| KPI 摘要 | [src/api/kpi.ts](src/api/kpi.ts) | 回全 0 | 後端 KPI 端點 |
| 登入（email OTP） | [src/api/auth/emailOtp.ts](src/api/auth/emailOtp.ts) | 寫死帳號＋驗證碼 `123456`，發 mock token | 換成真 OTP 端點；回傳形狀維持 `AuthSession { token, role, display_name }` |
| 登入（工號密碼） | `api/auth/employeePassword.ts` | 空殼（介面已定，throw） | 實作後把 [src/config/app.ts](src/config/app.ts) 的 `AUTH_MODE` 切成 `employee_password` |
| 潛在危險「已排除」 | `api/events.ts` `clearHazardEvent()` | stub 只印 log | 端點定案後填入實際呼叫（候選：與誤報共用 `PATCH /events/{id}/resolve`） |

### 後端目前「沒有端點、由前端記憶體暫代」的行為

以下都在 [src/hooks/EventsProvider.tsx](src/hooks/EventsProvider.tsx)，後端補端點後在該函式內加 API 呼叫即可：

| 行為 | 函式 | 備註 |
|---|---|---|
| 接手（護理人員確認前往處理） | `acknowledgeEvent` | ⚠ 與 §3 的送達確認 ack 是兩回事；前端轉 `in_progress` 並起算 24h 結案時限 |
| 復原接手 | `undoAcknowledge` | 純前端回滾 |
| 通報狀態（已初報/已續報/已結報） | `updateReportStage` | 由通報單「儲存」觸發；續報期限（+5 工作日，排除週末）也在前端算 |
| 誤報事件恢復 | `restoreEvent` | 誤報紀錄拉回處理中 |
| 首頁 log（接手/誤報/潛在危險） | `alertLog` state | 純前端記憶體，重整即清空 |

---

## 6. localStorage 使用一覽

| key | 內容 | 串接後 |
|---|---|---|
| `fulilian_auth_session` | 登入 session（token/role/display_name） | 保留（token 存放處） |
| `fulilian_reports` | 通報單，`Record<eventId, SavedReport[]>` | 改後端後移除（讀取程式相容舊單筆格式） |
| `fulilian_users` | 使用者清單（demo 含明文密碼） | 改後端後移除 |

---

## 7. 串接步驟建議（checklist）

1. [ ] `frontend/.env.local` 設 `VITE_API_BASE` 指向後端
2. [ ] 串登入：改寫 `api/auth/emailOtp.ts`（或實作 employeePassword 並切 `AUTH_MODE`）→ 拿到真 token 後，§3 的四個既有端點與 SSE 立即可用
3. [ ] 確認 SSE payload 與 §4 欄位表一致；`location`／`vlm_summary`／`severity`／`hazard_object` 格式定案後回頭簡化 `parseRawEvent` 防呆
4. [ ] `GET /events` 就緒 → 改 `getEvents()`，重整頁面即有歷史事件
5. [ ] `GET /devices` 就緒 → 改 `api/cameras.ts`
6. [ ] 通報單端點就緒 → 改 `api/reports.ts` 三支
7. [ ] 接手／通報狀態／已排除端點就緒 → 在 `EventsProvider` 對應函式補 API 呼叫
8. [ ] 全部串完後：刪 `api/mock/`、清 §6 的暫存 key、移除 `NGROK_HEADERS`（若不再走 ngrok）

---

## 8. 給後端同學的注意事項

- 前端顯示文字全走對照表（`STATUS_LABEL`、`EVENT_TYPE_LABEL`…），**後端請回英文枚舉值**（`pending`、`fall`、`hazard`…），不要回中文。
- `vlm_result: null` 是合法狀態（YOLO 高信心直通），所有 VLM 欄位前端都做了 null 防呆。
- 時間欄位請帶時區（ISO 8601 含 `Z` 或 `+08:00`）；不帶時區前端會當台灣時間補 `+08:00`。
- 事件重送安全：前端以 `event_id` 去重（upsert），同一事件重推不會出現重複卡片或重複彈窗。
- API 回應可以是空 body（204）；`client.ts` 已容忍，不會誤判失敗。
