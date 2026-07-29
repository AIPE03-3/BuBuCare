# 串流身分驗證實作計畫（B 階段）

> **執行方式：** 使用 superpowers:executing-plans 逐 Task 執行。步驟用 `- [ ]` 追蹤。
> **本計畫刻意精簡**（使用者 2026-07-29 核准）：每個 Task 只寫「改哪些檔案／要測什麼／怎麼算完成」，
> 不預先貼實作程式碼。理由是由掌握完整脈絡的同一人接續執行，非交接給無背景的人。

**Goal:** 讓即時影像只有登入中的使用者看得到——前端以登入 JWT 換 60 秒串流權杖，MediaMTX 收到觀看請求後回頭向後端驗票。

**Architecture:** 新增 `backend/streams/` 功能資料夾提供發票（需登入）與驗票（公開，供 MediaMTX 呼叫）兩個端點；MediaMTX 開啟 `authMethod: http` 指向驗票端點；前端在 WHEP 協商前先換票並以 `Authorization: Bearer` 帶上。

**Tech Stack:** FastAPI / python-jose / pytest（後端）、React + TypeScript（前端）、MediaMTX external HTTP auth、nginx。

**Spec:** `backend/docs/superpowers/specs/2026-07-29-stream-auth-design.md`

## Global Constraints

- 權杖 payload 固定為 `{"sub": 員編, "scope": "stream", "path": 頻道名, "exp": 現在+STREAM_TOKEN_EXPIRE_SECONDS}`
- `STREAM_TOKEN_EXPIRE_SECONDS` 預設 `60`，置於 `core/config.py`，`.env` 不需填
- 端點路徑寫全、`APIRouter()` 不加 prefix（同 `events/router.py` 慣例）
- 所有 uv／pytest 指令一律先 `cd backend`
- **不驗證頻道是否存在於資料庫**（spec 決定 3）
- **推流不驗證**，由 MediaMTX 的 `authHTTPExclude` 放行（spec 決定 1）
- **AI 端 RTSP 讀取走專屬帳密** `STREAM_RTSP_USER` / `STREAM_RTSP_PASS`，
  未設定即拒絕（fail-closed）（spec 決定 2）
- git commit 由使用者決定，不自行執行

## 檔案結構

| 檔案 | 責任 |
| --- | --- |
| `backend/streams/router.py` | 全部串流驗證邏輯（兩個端點 + request model），本功能唯一新檔 |
| `backend/core/auth.py` | 新增 `create_stream_token`，與 `create_access_token` 同檔——兩者共用 `SECRET_KEY`，放一起才看得出為何需要 `scope` 區分 |
| `backend/core/dependencies.py` | 新增 scope 反向檢查，全站門禁 |
| `backend/tests/test_streams.py` | 本功能全部後端測試 |

## Task 切線

Task 1-5 今天可完成（無需攝影機，用 `start-fake-camera.ps1` 推 mp4）。
Task 6 需真攝影機，明天執行。

---

### Task 1：串流權杖產生 + 發票端點

**Files:**
- Create: `backend/streams/__init__.py`（空）、`backend/streams/router.py`、`backend/tests/test_streams.py`
- Modify: `backend/core/config.py`（新增 `STREAM_TOKEN_EXPIRE_SECONDS`）、`backend/core/auth.py`（新增 `create_stream_token`）、`backend/main.py`（掛 router）

**Produces:**
- `create_stream_token(channel: str, sub: str) -> str`
- `POST /streams/{channel}/token` → `{"token": str, "expires_in": int}`

- [ ] **Step 1：寫測試（先全部寫完再跑）**

`backend/tests/test_streams.py`，用現成 fixture `client` / `auth_headers`：

| 測試 | 斷言 |
| --- | --- |
| `test_issue_token_requires_login` | 不帶 header → 401 |
| `test_issue_token_returns_token_and_expiry` | 200，回應含 `token`、`expires_in == 60` |
| `test_issue_token_payload_fields` | `decode_access_token(token)` 得 `sub == "alice"`、`scope == "stream"`、`path == "cam_in"` |
| `test_issue_token_binds_requested_channel` | 換頻道 `cam_out` 發票，payload 的 `path` 隨之改變 |

- [ ] **Step 2：跑測試確認失敗**

`cd backend; uv run pytest tests/test_streams.py -v` → 全數 FAIL（404 或 import error）

- [ ] **Step 3：實作**

`config.py` 加設定值（含註解說明為何刻意短命）；`auth.py` 加 `create_stream_token`；
`streams/router.py` 加發票端點（`Depends(get_current_user)`）；`main.py` 掛 router。

- [ ] **Step 4：跑測試確認通過**

`cd backend; uv run pytest tests/test_streams.py -v` → 全數 PASS

**完成標準：** 上表 4 個測試通過，且 `uv run pytest -v` 整體無新失敗。

---

### Task 2：驗票端點 `/streams/auth`

**Files:**
- Modify: `backend/streams/router.py`、`backend/tests/test_streams.py`、
  `backend/core/config.py`（加 `STREAM_RTSP_USER` / `STREAM_RTSP_PASS`）、`.env.example`

**Consumes:** Task 1 的 `create_stream_token`、`POST /streams/{channel}/token`
**Produces:** `POST /streams/auth`，回 204（放行）或 401（拒絕）

兩條分支，**順序不可對調**（先判協定，再驗票）：

```
protocol == "rtsp" and action == "read"  →  比對 STREAM_RTSP_USER / PASS   ← AI 端
其餘                                      →  比對短命權杖（要求 read + webrtc）← 瀏覽器
```

- [ ] **Step 1：寫測試（權杖分支）**

| 測試 | 送什麼 | 期待 |
| --- | --- | --- |
| `test_auth_allows_valid_token` | `cam_in` 的票 + `action=read` + `path=cam_in` + `protocol=webrtc` | 204 |
| `test_auth_rejects_garbage_token` | `token="not-a-jwt"` | 401 |
| `test_auth_rejects_login_token` | 用 `staff_token`（登入 JWT，無 `scope`） | 401 |
| `test_auth_rejects_wrong_channel` | `cam_in` 的票，`path=cam_out` | 401 |
| `test_auth_rejects_publish_action` | 有效票，`action=publish` | 401 |
| `test_auth_token_not_usable_over_rtsp` | 有效票，`protocol=rtsp`，**不帶帳密** | 401 |
| `test_auth_rejects_expired_token` | 測試裡直接 `jwt.encode` 一張 `exp` 已過去的票（**不要 monkeypatch `STREAM_TOKEN_EXPIRE_SECONDS`**：`auth.py` 用 `from core.config import ...` 在 import 當下就綁定了值，patch 不到） | 401 |
| `test_auth_accepts_null_optional_fields` | `{"action":"read","path":...,"protocol":"webrtc","token":...,"id":null,"query":null,"user":null,"password":null,"ip":null,"userAgent":null}` | **不得回 422**（204 即可） |
| `test_auth_requires_no_login` | 不帶 `Authorization` header 打此端點 | 不是 401「未登入」，而是走正常驗票邏輯 |

⚠ `test_auth_accepts_null_optional_fields` 是傑雅實際踩過的坑：MediaMTX 會送 `null`，
request model 除 `action` 外每個欄位都必須可為 `None`，否則 Pydantic 直接 422、驗證整個失效。

- [ ] **Step 2：寫測試（AI 端 RTSP 分支）**

`streams/router.py` 必須 `from core import config` 匯入**模組**（非 `from core.config import ...`），
否則 `monkeypatch` 換不掉值——`devices/router.py` 當初就是為此才這樣寫。

| 測試 | 送什麼 | 期待 |
| --- | --- | --- |
| `test_rtsp_read_allows_correct_credentials` | `protocol=rtsp` + `action=read` + 正確 `user`/`password` | 204 |
| `test_rtsp_read_rejects_wrong_password` | 同上但密碼錯 | 401 |
| `test_rtsp_read_rejects_missing_credentials` | 同上但 `user`/`password` 為 `null` | 401 |
| `test_rtsp_read_denied_when_env_unset` | `monkeypatch` 把兩個值設成 `""` | 401（fail-closed，不得因未設定而全放行） |

- [ ] **Step 3：跑測試確認失敗**

`cd backend; uv run pytest tests/test_streams.py -v` → 新增的 13 個 FAIL

- [ ] **Step 4：實作**

`config.py` 加兩個環境變數（預設空字串）；`.env.example` 同步並註明用途；
`streams/router.py` 加 `MediaMTXAuthRequest`（除 `action` 外全部 `| None = None`）與
`authorize_mediamtx`（`status_code=204`，兩條分支，帳密以 `hmac.compare_digest` 比對）。

⚠ 本機 `.env` 也要填入這兩個值，否則 Task 5 的假偵測腳本會讀不到 `cam_in`。

- [ ] **Step 5：跑測試確認通過**

`cd backend; uv run pytest tests/test_streams.py -v` → 全數 PASS

**完成標準：** 17 個測試全過。特別確認兩題：null 欄位不是 422、未設定帳密時是 401 不是 204。

---

### Task 3：`get_current_user` 反向拒絕串流權杖

⚠ 本 Task 動到**全站共用門禁**，是整個計畫風險最高的一步。

**Files:**
- Modify: `backend/core/dependencies.py`、`backend/tests/test_streams.py`

**Consumes:** Task 1 的 `create_stream_token`

- [ ] **Step 1：寫測試**

| 測試 | 斷言 |
| --- | --- |
| `test_stream_token_rejected_by_normal_api` | 拿串流權杖打 `GET /me` → 401 |
| `test_stream_token_rejected_by_events_api` | 拿串流權杖打 `GET /events` → 401 |
| `test_stream_token_cannot_issue_another_token` | 拿串流權杖打 `POST /streams/cam_in/token` → 401 |
| `test_login_token_still_works` | 一般登入 JWT 打 `GET /me` → 200（確認沒把正常路徑一起擋掉） |

- [ ] **Step 2：跑測試確認失敗**

前三個 FAIL（目前會回 200）、第四個已 PASS。

- [ ] **Step 3：實作**

`get_current_user` 在 `payload is None` 檢查之後，加上「`payload.get("scope") == "stream"` 即 401」。

- [ ] **Step 4：跑全部測試**

`cd backend; uv run pytest -v`

**完成標準：** 新增 4 個測試通過，且**既有測試零新增失敗**（改動前的基準數量先記下來再比對）。
任何既有測試變紅都必須停下來查清楚原因，不得直接改測試遷就。

---

### Task 4：前端先換票再連線

**Files:**
- Modify: `frontend/src/types/index.ts`、`frontend/src/api/cameras.ts`、`frontend/src/api/streams.ts`、
  `frontend/src/components/LiveStream.tsx`、`frontend/src/pages/Home.tsx`、
  `frontend/src/components/CameraDetailModal.tsx`、`frontend/CLAUDE.md`

**Consumes:** Task 1 的 `POST /streams/{channel}/token`

前端無測試框架（同 A 階段），以 `npm run build` + ESLint + 手動驗收把關。

- [ ] **Step 1：型別與資料層**

`Camera` 介面加 `stream_channel: string | null` 與 `stream_channel_detect: string | null`
（後端 `GET /devices` 早已回傳，目前被 `api/cameras.ts` 丟棄）；`api/cameras.ts` 透傳。

- [ ] **Step 2：`api/streams.ts`**

新增 `fetchStreamToken(channel: string): Promise<string>`（走 `apiClient`，自動帶登入 token）；
`negotiateWhep(whepUrl, offerSdp, streamToken)` 增收第三參數，加上 `Authorization: Bearer` header。

- [ ] **Step 3：`LiveStream.tsx`**

props 增 `channel: string | null`；在 `waitForIceGathering(pc)` **之後**呼叫 `fetchStreamToken(channel)`
再協商（ICE 收集約需一至兩秒，越晚換票剩餘壽命越長）。
換票失敗時走既有的 `setState('failed')` 路徑，重試按鈕自動換新票。

- [ ] **Step 4：傳遞 channel**

`Home.tsx` 四宮格與 `CameraDetailModal.tsx` 依目前的即時／偵測模式傳對應的
`stream_channel` 或 `stream_channel_detect`（與 `whepUrl` 同一個模式，兩者必須配對，不可一個即時一個偵測）。

- [ ] **Step 5：同步 `frontend/CLAUDE.md`**

更新該檔內的 `Camera` 介面定義（前端唯一權威規範，不同步會與程式碼打架）。

- [ ] **Step 6：建置檢查**

`cd frontend; npm run build` → 通過，ESLint 無錯。

**完成標準：** build 與 lint 通過。此時 MediaMTX 尚未開驗證，畫面應**仍然正常**——
前端多帶一個 header 不影響尚未啟用驗證的 MediaMTX。這是刻意的：Task 4 與 Task 5 之間任一步都不該讓畫面消失。

---

### Task 5：MediaMTX 開啟驗證 + 端到端驗證（本階段主驗收）

**Files:**
- Modify: `streaming/mediamtx.yml.example`、本機的 `streaming/mediamtx.yml`（不進 git）、
  `streaming/start-fake-detect.ps1`（讀取網址帶帳密）、`frontend/nginx.conf`

**Consumes:** Task 2 的 `POST /streams/auth`、Task 4 的前端

- [ ] **Step 1：驗證前先取得「改動前」對照**

在還沒開驗證時，複製一條 WHEP 網址貼到新分頁確認**看得到**。
這是本功能效果的前後對比證據，錯過就要重來（開了驗證再關掉會中斷所有連線）。

- [ ] **Step 2：修 nginx 前綴地雷**

`frontend/nginx.conf` 的 `location /api/stream` 改為 `location = /api/stream`。
（目前 `/api/streams/auth` 會被它前綴命中，重寫結果碰巧正確，屬巧合。
`gcp_vm_environment/default.conf` 無此問題，不需改。）

- [ ] **Step 3：改 MediaMTX 設定**

`mediamtx.yml.example` 與本機 `mediamtx.yml` 加入 `authMethod: http`、
`authHTTPAddress: http://127.0.0.1:8000/streams/auth`（雲端位址以註解保留）、
`authHTTPExclude`（`publish` / `api` / `metrics` / `pprof`）。

⚠ 存檔即觸發熱重載，中斷全部現有連線。改完再一次重啟推流腳本，不要邊測邊改。

- [ ] **Step 4：啟動並端到端驗證**

啟動順序：後端 `uv run uvicorn main:app --reload` → MediaMTX → `start-fake-camera.ps1` → 前端 `npm run dev`

| 驗收項 | 期待 |
| --- | --- |
| 登入後首頁四宮格 | 有畫面 |
| **複製 WHEP 網址貼新分頁（不帶權杖）** | **看不到（401）** ← 本功能核心證明 |
| 登出後重新整理 | 無畫面 |
| 切「偵測」模式 | 重新換票，有畫面 |
| 「重新連線」按鈕 | 有效 |
| 瀏覽器 Console | 無 CORS 預檢錯誤（多帶 `Authorization` 會觸發 OPTIONS，需確認 MediaMTX 放行） |
| 後端終端機 | 每開一格畫面就看到一筆 `POST /streams/auth 204` |

- [ ] **Step 5：手機推流仍可用**

Larix 推 `phone_a` → 確認**不需要帳密**（驗證 `authHTTPExclude: action: publish` 生效）。

- [ ] **Step 6：AI 端讀取路徑驗證（用假偵測腳本代打）**

`start-fake-detect.ps1` 的讀取網址改成 `rtsp://<STREAM_RTSP_USER>:<STREAM_RTSP_PASS>@127.0.0.1:8554/cam_in`。

| 驗收項 | 期待 |
| --- | --- |
| 帶正確帳密啟動腳本 | 讀得到 `cam_in`，`cam_out` 有紅框畫面 |
| **故意把密碼改錯再啟動** | **讀不到，ffmpeg 報 401** ← 證明 RTSP 那條路真的擋住了 |
| VLC 開 `rtsp://127.0.0.1:8554/cam_in`（不帶帳密） | 開不起來 |

這一步等於預先替 AI 端測完那條路，他們只要照同樣格式改網址即可。

**完成標準：** 上表全數通過。特別是這三項，分別驗證了 spec 的目標與決定 1、決定 2：

- 瀏覽器貼網址看不到 → 目標達成
- 手機推流不用改設定 → 決定 1 生效
- VLC 開 RTSP 開不起來、但帶帳密的腳本讀得到 → 決定 2 生效

---

### Task 6：真攝影機驗證 + 文件收尾（需攝影機，明天執行）

**Files:**
- Modify: `streaming/README.md`、根目錄 `CLAUDE.md`

- [ ] **Step 1：真攝影機驗證**

接上 Tapo 攝影機，確認開啟驗證後 `cam_in` 仍有畫面。

這是 spec 標記「未實測」的最大風險：MediaMTX 是**主動外連**去攝影機拉畫面（`source: rtsp://...`），
推論上不受 external auth 管轄，但未經證實。
若真的被擋，於 `authHTTPExclude` 加對應例外即可，**不需回頭改任何程式碼**。

- [ ] **Step 2：`streaming/README.md`**

新增三節：「驗證開啟後的啟動步驟」（後端必須先起，否則 MediaMTX 問不到人）、
「RTSP 讀取端要帶帳密」（`.env` 的兩個值、網址格式、給 AI 端的說明）、
「退路：如何關掉驗證」（註解掉三個設定 + 重啟，約 30 秒）。

- [ ] **Step 3：演練退路一次**

實際把驗證關掉、確認畫面回來、再開回去。demo 當天不能是第一次做。

- [ ] **Step 4：根目錄 `CLAUDE.md`**

API 路由表新增 `POST /streams/{channel}/token` 與 `POST /streams/auth`；
檔案結構表新增 `backend/streams/router.py`；`core/config.py` 說明補上串流權杖設定值。

- [ ] **Step 5：全測試 + 建置**

`cd backend; uv run pytest -v`、`cd frontend; npm run build` 皆通過。

**完成標準：** 真攝影機有畫面、退路演練過、兩份 CLAUDE.md 與 README 皆已同步。

---

## 完成後

- 提醒使用者 commit 並開 PR 進 main
- 通知 AI 端（**兩件事，一件要改一件不用**）：
  - ✅ **推流不受影響**——推 `cam_out` 照舊，不需帳密、不需改設定
  - ⚠ **讀取要改一行**——`rtsp://<host>:8554/cam_in` 改成 `rtsp://<帳號>:<密碼>@<host>:8554/cam_in`，
    帳密另外私下給（不進 git）。跟他的登入 JWT 無關，不要去動登入那條路
  - ✅ `/login` 表單格式、`access_token` 欄位名、`GET /devices` 回應格式**皆未變動**
- 更新記憶 `camera-live-stream-state`：B 階段完成、demo 待辦新增「退路演練」與「AI 端帳密同步」
