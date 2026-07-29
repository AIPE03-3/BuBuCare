# 串流身分驗證設計（攝影機即時串流 B 階段）

日期：2026-07-29
前一階段：`2026-07-28-camera-live-stream-design.md`（A 階段，畫面通，已完成上 main）

## 目標

讓即時影像只有「目前登入中的使用者」看得到。做法是前端以登入 JWT 換取 60 秒短命串流權杖，
MediaMTX 收到觀看請求後回頭向後端驗證該權杖。

## 為什麼登入驗證不夠

登入驗證保護的是後端。影像不經過後端——瀏覽器直接連 MediaMTX 的 8889 埠取得畫面，
MediaMTX 是獨立軟體，不知道本系統有登入機制。

現況：同網段任何人知道網址即可觀看。網址取得成本極低（前端網路請求可見、頻道名可猜、
MediaMTX 內建播放頁 `http://<host>:8889/cam_in` 直接可播）。
結果是保護最嚴的是文字資料，完全未保護的是住民即時影像。

## 範圍

| 做 | 不做 |
| --- | --- |
| 瀏覽器觀看（WebRTC read）需短命權杖 | 推流（publish）驗證 |
| | RTSP 讀取驗證——刻意放行，理由見「設計決定」第 2 條 |
| | 每人只能看指定鏡頭的授權模型 |
| `POST /streams/{channel}/token` 發票 | HTTPS／傳輸加密 |
| `POST /streams/auth` 供 MediaMTX 驗票 | 踢掉已建立的連線 |
| `get_current_user` 反向拒絕串流權杖 | 跨網路觀看 |
| MediaMTX `authMethod: http` 設定 | |

## 架構

```
① 前端 ──POST /streams/cam_in/token（帶登入 JWT）──> 後端 ──> 回 60 秒串流權杖
② 前端 ──POST {mediamtx}/cam_in/whep（帶串流權杖）──> MediaMTX
③                          MediaMTX ──POST /streams/auth──> 後端 ──> 204 / 401
④ MediaMTX ──WebRTC 影像──> 前端
```

連線方向：MediaMTX 主動打向後端。後端從不主動連 MediaMTX。
因此「後端在雲端、MediaMTX 在現場區網」的組合可行（現場往外連不受 NAT 影響）。

四宮格＝四張票，各自綁自己的頻道。切「偵測」模式重新換 `*_out` 頻道的票。

## 設計決定

### 1. 只擋觀看，推流放行

`authHTTPExclude` 列入 `action: publish`。理由：手機 Larix、AI 端的 ffmpeg、
`start-fake-camera.ps1` / `start-fake-detect.ps1` 全都不需改設定，demo 前不必重設三支手機。
代價：同網段可推垃圾畫面蓋掉 `cam_out`，demo 情境風險可接受。

### 2. RTSP 讀取一律放行（2026-07-29 改版，原訂走專屬帳密）

AI 端的推論程式「讀 `cam_in` → 畫框 → 推 `cam_out`」，其中**讀**走 RTSP、非 WebRTC，
不可能持有瀏覽器才拿得到的短命權杖。若不處理，開啟驗證即中斷整條偵測管線。

做法：`/streams/auth` 對 `protocol == "rtsp" and action == "read"` 直接回 204，
不檢查任何憑證。AI 端與 `start-fake-detect.ps1` 都沿用原本的網址，零改動。

**代價**：同網段以 VLC 開 `rtsp://<host>:8554/cam_in` 即可觀看，等於只擋瀏覽器。
正當化前提是**內網信任**——攝影機／MediaMTX／AI 主機屬同一受控網段。
正式環境應將三者切到獨立 VLAN，該前提才成立；目前 demo 跑在共用 Wi-Fi 上並不成立，
接受此風險的理由是 demo 為受控展示、評審不自行連線。

**原訂做法（已改）**：比對 `.env` 的 `STREAM_RTSP_USER` / `STREAM_RTSP_PASS`
（`hmac.compare_digest`，未設定即 fail-closed）。改掉的理由是每個 RTSP 讀取端都要改網址、
多一個跨組協調與 demo 當天出錯的環節，而受控內網下該保護的邊際價值有限。

**想鎖回去**：`.env` 加回那兩個變數，`streams/router.py` 的 RTSP 分支改成比對
`body.user` / `body.password`，並把所有讀取端網址改為 `rtsp://<帳號>:<密碼>@<host>:8554/<頻道>`。

### 3. 發票時不驗證頻道是否存在於資料庫

給什麼頻道名就發什麼票。省一次查詢；權杖僅能觀看 MediaMTX 上已存在的頻道，
且該頻道必須已在 `mediamtx.yml` 的 `paths:` 下宣告，未宣告者 MediaMTX 本就拒收。

### 4. `scope: "stream"` 雙向檢查

登入 JWT 與串流權杖以同一把 `SECRET_KEY` 簽署，外觀無從分辨，故以 `scope` 欄位區隔：

| 檢查點 | 規則 | 擋掉什麼 |
| --- | --- | --- |
| `POST /streams/auth` | 無 `scope=stream` → 401 | 拿一整天有效的登入 JWT 當串流票用 |
| `get_current_user` | 有 `scope=stream` → 401 | 拿串流票呼叫 `/events`、`/users` 等一般 API |

第二項動到全站共用的 `core/dependencies.py`，現有全部測試須重跑。
實際風險不大（串流權杖無 `role`，admin 端點仍被 `require_admin` 擋），
但權杖會寫入 MediaMTX 與 nginx 存取紀錄，外流後 60 秒內可冒用。

### 5. 權杖有效 60 秒

`STREAM_TOKEN_EXPIRE_SECONDS` 置於 `core/config.py`，預設 60，`.env` 不需填。
短命是刻意的：權杖會出現在存取紀錄中，過期越快、外流可用時間越短。
60 秒足夠完成一次 WHEP 協商。

### 6. 後端位址：本機先測完再改雲端

`mediamtx.yml` 的 `authHTTPAddress` 本機與雲端不同，且**發票與驗票必須是同一個後端**
（`SECRET_KEY` 不同則驗不過）。設定檔保留兩行、註解切換：

```yaml
authHTTPAddress: http://127.0.0.1:8000/streams/auth
# 雲端 demo：http://35.221.135.197/api/streams/auth
```

`mediamtx.yml` 本就不進 git（含攝影機帳密），手改一行成本低，不另做兩份範本。

## 端點規格

### `POST /streams/{channel}/token`（需登入）

回應：`{"token": "<jwt>", "expires_in": 60}`

權杖內容：`{"sub": 員編, "scope": "stream", "path": channel, "exp": 現在+60秒}`

### `POST /streams/auth`（公開）

由 MediaMTX 呼叫，不能要求登入。安全性來自「無有效權杖必回 401」。
公開暴露的資訊僅有「某權杖有效與否」，無其他內容。

請求（MediaMTX 送出，部分欄位可能為 `null`，request model 除 `action` 外全部須可為 None）：

```json
{"action": "read", "path": "cam_in", "protocol": "webrtc", "token": "eyJ...",
 "ip": "...", "user": "", "password": "", "id": null, "query": "", "userAgent": ""}
```

兩條分支，回 204（放行）或 401（拒絕）：

**分支一：`protocol == "rtsp" and action == "read"` → 直接放行**

不檢查任何憑證（決定 2）。**只有「讀」放行**，RTSP 推流會落進分支二被擋。

**分支二：其餘一律走短命權杖**

| 條件 | 用意 |
| --- | --- |
| 權杖簽名有效且未過期 | 基本驗證 |
| `scope == "stream"` | 不是登入 JWT |
| `payload["path"] == body.path` | 票綁死頻道，換頻道無效 |
| `action == "read"` | 觀看票不能用於推流 |
| `protocol == "webrtc"` | 只有瀏覽器路徑能用權杖 |

分支順序不可對調：先判協定再驗票，否則 AI 端的 RTSP 請求會落入分支二被 `protocol` 條件擋下。

## 改動清單

### 後端

| 檔案 | 動作 |
| --- | --- |
| `backend/streams/__init__.py` | 新增（空） |
| `backend/streams/router.py` | 新增：兩個端點 |
| `backend/core/auth.py` | 新增 `create_stream_token(channel, sub)` |
| `backend/core/config.py` | 新增 `STREAM_TOKEN_EXPIRE_SECONDS`（預設 60） |
| `backend/core/dependencies.py` | `get_current_user` 拒絕 `scope=stream` |
| `backend/main.py` | 掛 `stream_router` |

端點路徑寫全、`APIRouter()` 不加 prefix，同 `events/router.py` 慣例。

### 前端

前端手上只有完整 WHEP 網址，換票需要頻道名。`GET /devices` 本就同時回 `stream_channel`，
目前被前端丟棄——撿回使用即可，後端不需改動。

| 檔案 | 動作 |
| --- | --- |
| `types/index.ts` | `Camera` 加 `stream_channel` / `stream_channel_detect` |
| `api/cameras.ts` | 透傳上述兩欄 |
| `api/streams.ts` | 新增 `fetchStreamToken(channel)`；`negotiateWhep` 增收 token 參數 |
| `components/LiveStream.tsx` | prop 增 `channel`；ICE 收集完成後換票再協商 |
| `pages/Home.tsx` | 四宮格傳 channel |
| `components/CameraDetailModal.tsx` | 彈窗傳 channel |
| `frontend/CLAUDE.md` | 同步 `Camera` 介面定義（該檔為前端唯一權威規範） |

換票排在 ICE 收集之後：ICE 需一至兩秒，越晚換票剩餘壽命越長。
「重新連線」按鈕重跑整段 effect，自動換新票，不會使用過期票。

### MediaMTX（`streaming/mediamtx.yml.example`）

```yaml
authMethod: http
authHTTPAddress: http://127.0.0.1:8000/streams/auth
# 雲端 demo：http://35.221.135.197/api/streams/auth
authHTTPExclude:
  - action: publish
  - action: api
  - action: metrics
  - action: pprof
```

### 串流腳本

`streaming/start-fake-detect.ps1`（讀 `cam_in` 畫紅框推 `cam_out`）與 `start-fake-camera.ps1`
皆不需修改：讀取已放行、推流本就免驗證。

### nginx

`frontend/nginx.conf` 的 `location /api/stream`（SSE 用）會前綴命中 `/api/streams/auth`。
目前重寫結果碰巧正確，但屬巧合。改為 `location = /api/stream` 精確比對。

`gcp_vm_environment/default.conf` 無此問題（`location /api/` 加 `rewrite` 剝除前綴）。

### 文件

| 檔案 | 動作 |
| --- | --- |
| 根目錄 `CLAUDE.md` | API 路由表新增兩個端點、檔案結構新增 `backend/streams/`、`config.py` 說明補設定值 |
| `streaming/README.md` | 新增「驗證開啟後的啟動步驟」與「退路：如何關掉驗證」 |

## 已知限制

1. **權杖僅在建立連線時驗證一次**，之後 MediaMTX 不再詢問後端。
   故權杖過期、使用者登出、帳號被停用，皆不會中斷已建立的連線。
   擋的是「新連線」，非「踢掉現有觀看者」。此為 MediaMTX 行為，無法改變。
2. **後端不可用即完全無畫面**。A 階段無此耦合（影像不經後端，後端掛掉照播）。
   現場網路連不上雲端後端時四格全失敗。退路見下節。
3. 推流仍不設防（決定 1）。同網段可推垃圾畫面蓋掉 `cam_out`。
   RTSP **讀取**也不設防（決定 2）：同網段用 VLC 開 `rtsp://<host>:8554/cam_in` 就看得到。
   受保護的只有瀏覽器那條路。
4. 換票與 WHEP 協商走 http 明文，同網段抓封包可撿得權杖並於 60 秒內冒用。
   WebRTC 影像本身為 DTLS-SRTP 加密，不受影響。此非新增問題——登入密碼與登入 JWT
   在 A 階段即為明文傳輸。根治需整套上 HTTPS，屬後續階段。
5. 觀看者仍須與 MediaMTX 同網段，A 階段限制不變。

## 退路

demo 現場後端不可用時，將 `mediamtx.yml` 的 `authMethod` / `authHTTPAddress` /
`authHTTPExclude` 註解掉並重啟 MediaMTX，即退回 A 階段行為（約 30 秒）。
須寫入 `streaming/README.md` 並事先演練一次。

⚠ 重啟與存檔 `mediamtx.yml` 都會中斷全部現有連線（設定檔熱重載），A 階段已記錄此行為。

## 驗證方式

### 後端 pytest

| 案例 | 期待 |
| --- | --- |
| 未登入換票 | 401 |
| 登入後換票 | 200，權杖含 `sub` / `scope=stream` / `path`，`expires_in=60` |
| 有效權杖驗票 | 204 |
| 竄改或格式錯誤的權杖 | 401 |
| 以登入 JWT 當串流權杖 | 401 |
| 以串流權杖呼叫一般 API | 401 |
| `cam_in` 的票用於 `cam_out` | 401 |
| `action=publish` | 401 |
| RTSP 讀取（不帶任何憑證） | 204（刻意放行） |
| RTSP 推流 | 401（只有「讀」放行） |
| 請求欄位含 `null` | 不得 422 |
| 過期權杖 | 401 |

現有全部測試須重跑（改動 `core/dependencies.py`）。

### 前端手動驗收（前端無測試框架，同 A 階段做法）

1. 登入 → 四宮格有畫面
2. 複製 WHEP 網址貼入新分頁（不帶權杖）→ 看不到。**改動前後各做一次，前後對比即為本功能的效果證明**
3. 登出後重新整理 → 無畫面
4. 切「偵測」模式、按「重新連線」→ 皆正常

### 需實測確認的風險

| 風險 | 說明 | 何時可測 |
| --- | --- | --- |
| MediaMTX 拉取真攝影機是否受驗證影響 | `source: rtsp://...` 是 MediaMTX 主動外連，推論不受 auth 管轄，未實測 | 攝影機到位後 |
| 瀏覽器 CORS 預檢是否放行 `Authorization` | 多帶該 header 會觸發 OPTIONS 預檢，傑雅版實測可行但設定不同 | 立即 |
| 設定檔熱重載中斷連線 | 已知行為，驗證順序須排定，不可邊測邊改 | — |

無攝影機期間可用 `start-fake-camera.ps1` 推 mp4 完成除「真攝影機」外的全部驗證。

## 參考

傑雅實作：`AIPE03-3/aipe03-3` 分支 `jieya_hsu`，
`kelly_liu/aipe03-3-kelly_liu-mediamtx_20260725/backend/streams/router.py`、`MEDIAMTX_JWT_SETUP.md`。
建立於 2026-07-24 重構前的結構（`backend.core.xxx`），本專案僅參考驗證邏輯與 Pydantic 欄位可空的踩坑經驗。
