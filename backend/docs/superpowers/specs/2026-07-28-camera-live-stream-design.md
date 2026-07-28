# 攝影機即時串流（A 階段）設計規格

日期：2026-07-28

## 目標

讓登入者在中控台看到鏡頭即時畫面，並可切換「即時（原味）」與「偵測（AI 畫框）」兩種畫面。
本階段（A）只求區網內畫面通，不做身分驗證、不做跨網路觀看。

## 範圍

| 做 | 不做（後續階段） |
| --- | --- |
| 首頁四宮格 ＋ 點擊放大 | 串流身分驗證（下一階段，A 通了立刻做） |
| 鏡頭彈窗即時畫面 | 跨網路 / 雲端中繼觀看 |
| 即時／偵測切換（頁面右上角一組，四格一起切） | HTTPS 與自簽憑證（除非前端跑在 https） |
| 後端回傳兩條串流網址 | `PATCH /devices/{id}` 改名接真後端 |
| 本機假攝影機環境（ffmpeg 推 mp4） | 錄影、截圖、多於四格的版面 |
| 清除未使用的 `stream_source` 型別 | 監控頁表格清單加縮圖（維持文字表格） |

## 架構

```
攝影機 / mp4 檔 ──→ MediaMTX ── cam_in ──→ AI 推論 ──→ cam_out
                        │                                 │
                        └──────── WebRTC (WHEP) ──────────┘
                                       ↓
                                  瀏覽器 <video>

FastAPI 後端 ── GET /devices ──→ 只回網址字串，全程不碰影像
```

影像不經過後端。後端的唯一職責是告訴前端「MediaMTX 在哪、要看哪個頻道」。

## 頻道命名

採用 albert（AI 端）既有命名：

| 頻道 | 內容 | 對應 UI |
| --- | --- | --- |
| `cam_in` | 進 AI 前的原始畫面 | 即時 |
| `cam_out` | AI 畫上偵測框後的畫面 | 偵測 |
| `phone_a` / `phone_b` / `phone_c` | 手機推流，未經 AI | 即時（無對應偵測頻道） |

程式碼與設定檔註解須註明：傑雅版原本叫 `my_camera_tapo`，語意等同 `cam_in`；
改名理由是 `cam_in` / `cam_out` 描述的是「在 AI 的哪一端」，換攝影機廠牌不會過期。

此命名需要 albert 與傑雅兩邊的 MediaMTX 設定配合對齊。

## 後端設計

### core/config.py

新增 `MEDIAMTX_BASE_URL`，讀 `.env`，預設空字串。值須含協定與埠號，例如
`http://192.168.1.108:8889`。前端若跑在 https，此處須改為 `https://`。

### core/models.py

`devices` 表最終有兩個串流欄位（皆 `String(255)`, nullable）：

| 欄位 | 內容 |
| --- | --- |
| `stream_channel` | 原味頻道名（`cam_in`） |
| `stream_channel_detect` | 偵測頻道名（`cam_out`），沒接 AI 的鏡頭為 NULL |

兩欄存的都是**頻道名**，不是完整網址。

> 執行過程中這兩欄原名為 `stream_url` / `stream_url_detect`（沿用既有欄位），
> 但「叫 url、裡面裝頻道名」誤導過填資料的人（301～304 曾被填成
> `rtsp://127.0.0.1:8554/cam301`，該位址只在填寫者本機有效）。
> 2026-07-28 已 `RENAME COLUMN` 改為現名，資料未變動，API 鍵名亦未變動。

**這裡改的是程式端的欄位定義，不等於真實資料庫多了一欄，兩件事都要做：**

| 動作 | 影響誰 | 少了會怎樣 |
| --- | --- | --- |
| 改 `models.py` | 程式端（ORM 認不認得這一欄） | 資料庫有欄位，但程式讀不到也寫不進去 |
| 下 `ALTER TABLE` | 既有 RDS（實際多一欄） | 程式去讀 → 報 `column does not exist` |

測試環境不需要 `ALTER TABLE`：`conftest.py` 每次都用記憶體 SQLite 現建全新的表，
直接照 `models.py` 建出來，兩邊天生一致。只有既有的 RDS 需要另外補。

### devices/router.py

`serialize_device` 回傳**兩種形式**，因為兩邊消費者的協定不同：

```json
{
  "device_id": 1,
  "device_name": "交誼廳-01",
  "location": "交誼廳",
  "floor": null,
  "stream_channel":        "cam_in",
  "stream_channel_detect": "cam_out",
  "stream_url":        "http://192.168.1.108:8889/cam_in/whep",
  "stream_url_detect": "http://192.168.1.108:8889/cam_out/whep",
  "status": "active"
}
```

| 欄位 | 消費者 | 用途 |
| --- | --- | --- |
| `stream_channel` / `stream_channel_detect` | AI 端 | 原始頻道名，AI 端自己接上本機 base 組成 `rtsp://<自己的MediaMTX>:8554/<頻道名>`。albert 的推論是「讀 `cam_in` → 畫框 → 推 `cam_out`」，兩個名字都要 |
| `stream_url` / `stream_url_detect` | 瀏覽器 | 組好的 WHEP 網址。瀏覽器只看得懂 WebRTC，讀不了 RTSP |

WHEP 網址組合規則：

- `MEDIAMTX_BASE_URL` 為空 → 兩者皆 `null`
- 該裝置對應的頻道名為空 → 該欄位 `null`
- 兩者皆有 → `{base}/{頻道名}/whep`

`null` 的意義是「這個環境沒有這條串流」，前端據此隱藏對應按鈕或退回占位框。
原始頻道名不受 `MEDIAMTX_BASE_URL` 影響，有填就回。

DB 欄位名與 API 的原始頻道名鍵一致（皆為 `stream_channel` / `stream_channel_detect`），
直接對資料庫下 SQL 與讀 API 用同一組名稱，不需換算。

`RENAME COLUMN` 屬無緩衝的硬切換——執行當下所有尚未更新程式的後端行程，`GET /devices`
會立即 500（找不到欄位）。因此改名必須與後端部署貼近執行，並事先通知全隊。
2026-07-28 執行時已與 AI 端協調時間；API 鍵名未變，AI 端與前端皆無需改動程式。

### init_db.py：本輪不動

`init_db.py` 只有 `create_tables()`（`Base.metadata.create_all`）＋ 兩段種子。
`create_all` 只建立不存在的表，**不會為既有的表新增欄位**，因此它幫不上既有 RDS 的忙。
（`CLAUDE.md` 描述的「補舊表欄位」步驟在程式碼中不存在，屬過時敘述，另案修正。）

種子改動同樣沒有意義：全隊共用同一個 RDS，`devices` 表已有資料，種子判斷式
（`if db.query(Device).first() is None`）永遠會跳過；測試環境走 `conftest.py` 的
記憶體 SQLite，自行建表、不經 `init_db`。

因此新欄位與新資料一律以下方一次性 SQL 處理。若日後有人另建全新資料庫，
需自行把種子補到 4 台，或直接沿用同一段 SQL。

### .env.example

新增 `MEDIAMTX_BASE_URL`，註明何時要改成 `https://`。

## 一次性資料庫調整（對現有 RDS 執行）

全隊共用同一個 AWS RDS，此段由一人執行一次，所有人同步生效。
新欄位只能由此處的 `ALTER TABLE` 加上——`init_db.py` 的 `create_all` 不會為既有表補欄位。

### RDS 實際現況（2026-07-29 查核）

規格初稿假設 `devices` 只有 1、2 兩台，實際查核後為 7 台，且 301～304 已被填入完整 RTSP 網址：

| device_id | device_name | stream_url |
| --- | --- | --- |
| 1 | 交誼廳-01 | NULL |
| 2 | 走廊-01 | NULL |
| 101 | VLM測試裝置-101 | NULL |
| 301 | 寢室-301 | `rtsp://127.0.0.1:8554/cam301` |
| 302 | 寢室-302 | `rtsp://127.0.0.1:8554/cam302` |
| 303 | 寢室-303 | `rtsp://127.0.0.1:8554/cam303` |
| 304 | 寢室-304 | `rtsp://127.0.0.1:8554/cam301` |

因此**不新增裝置**，直接沿用 301～304 作為四宮格，把值改為頻道名。
`127.0.0.1` 只有填入者本機連得到，且 304 與 301 指向同一條，屬測試殘留。

### SQL

兩段依序執行，`ALTER TABLE` 必須在最前面，否則 `UPDATE` 會因欄位不存在而失敗。

實際執行順序（2026-07-28 全部完成）：

```sql
-- ⓪ 先加欄位
ALTER TABLE devices ADD COLUMN stream_url_detect VARCHAR(255);

-- ① 四台填入頻道名（301 接真攝影機，其餘接手機推流）
-- 包在同一個 transaction：避免只改到一半、四台新舊混雜的狀態
BEGIN;
UPDATE devices SET stream_url='cam_in',  stream_url_detect='cam_out' WHERE device_id=301;
UPDATE devices SET stream_url='phone_a', stream_url_detect=NULL      WHERE device_id=302;
UPDATE devices SET stream_url='phone_b', stream_url_detect=NULL      WHERE device_id=303;
UPDATE devices SET stream_url='phone_c', stream_url_detect=NULL      WHERE device_id=304;
COMMIT;

-- ② 手機三路的偵測頻道（AI 端確認四路可行後補上，等待其推流實作）
BEGIN;
UPDATE devices SET stream_url_detect='phone_a_out' WHERE device_id=302;
UPDATE devices SET stream_url_detect='phone_b_out' WHERE device_id=303;
UPDATE devices SET stream_url_detect='phone_c_out' WHERE device_id=304;
COMMIT;

-- ③ 欄位改名（值不變，API 鍵名不變）
BEGIN;
ALTER TABLE devices RENAME COLUMN stream_url        TO stream_channel;
ALTER TABLE devices RENAME COLUMN stream_url_detect TO stream_channel_detect;
COMMIT;
```

**日後查詢一律使用改名後的 `stream_channel` / `stream_channel_detect`。**

### 執行時機的相依

`UPDATE` 必須在 **albert 改讀 `stream_channel` 之後**才執行。他的程式目前把 `stream_url` 的值
當完整 RTSP 位址直接使用，一旦換成 `cam_in` 這種頻道名，他會立即連不到來源。
`ALTER TABLE` 無此顧慮（純新增，不影響任何既有讀取），可先執行。

albert 另提出 AI 端加**相容模式**（值以 `http`/`rtsp` 開頭視為完整網址，否則視為頻道名），
如此新舊資料可並存、兩邊不必同秒部署。採納，但屬**暫時橋接**：
`UPDATE` 完成並確認四台正常後即移除該分支，避免 `stream_url` 的混合語意長期存在。

## 前端設計

### 新增檔案

| 檔案 | 職責 |
| --- | --- |
| `src/api/streams.ts` | `negotiateWhep(whepUrl, offerSdp)`：POST SDP offer、回傳 answer。WHEP 的 fetch 只存在於此檔，遵守「元件內禁止直接 fetch」鐵律 |
| `src/components/LiveStream.tsx` | 吃單一 `whepUrl`，建立 / 關閉 WebRTC 連線並播放 |
| `src/components/StreamModeToggle.tsx` | 「即時 / 偵測」兩顆按鈕 |

`negotiateWhep` 不走 `client.ts`：目標是 MediaMTX 而非後端，不帶登入 token，
Content-Type 為 `application/sdp` 而非 JSON。

### LiveStream 行為

| 狀態 | 畫面 |
| --- | --- |
| `whepUrl` 為 `null` | 灰色占位框，文字由 `emptyLabel` prop 決定，預設為 `CAMERA_LABEL.LIVE_PLACEHOLDER` |
| 連線中 | 黑底 ＋ 連線中提示 |
| 已連線 | 影像 |
| 失敗 / 斷線 | 灰底 ＋ 錯誤訊息 ＋「重新連線」按鈕 |

連線流程：`RTCPeerConnection` → `addTransceiver('video', {direction:'recvonly'})`
→ `createOffer` → `setLocalDescription` → 等 ICE 收集完成 → `negotiateWhep`
→ `setRemoteDescription`。

必須做到：

- 元件卸載時 `pc.close()` 並清空 `video.srcObject`
- `whepUrl` 改變時關閉舊連線、重建新連線

### 首頁（Home.tsx）

- 單一大框改為 2×2 四宮格
- 點任一格 → 該格放大為單一大畫面；再點一次 → 回四宮格
- **放大時其餘三格的連線保留**（以 CSS 隱藏而非卸載）。理由：連線數上限與四宮格模式相同，
  但切換不需重連，無黑畫面
- 每格左上角保留鏡頭名稱浮貼標籤
- 格子以 `<button>` 包裹，可鍵盤操作
- 刪除切鏡頭下拉選單：手機版、桌機版右欄、`CameraSelect` 元件本體
- 四格取 `GET /devices` 回傳順序（依 `device_id`）的前 4 台；不足 4 台時，空格顯示灰色占位框

### 即時／偵測切換

`StreamModeToggle` 一組，位於首頁右上角（彈窗內則位於彈窗右上角），四格一起切換。
切換即是把傳給各 `LiveStream` 的網址在 `stream_url` 與 `stream_url_detect` 之間替換。

- 目前模式對應的網址為 `null` 的鏡頭，該格顯示占位框，`emptyLabel` 傳入「此鏡頭無 AI 偵測」
  （與一般占位框的「鏡頭即時影像」區分，讓使用者知道是未接 AI 而非故障），其他格不受影響
- 四台鏡頭皆無 `stream_url_detect` 時，整組切換鈕不顯示

### 鏡頭彈窗（CameraDetailModal.tsx）

灰色占位框改為 `LiveStream`，右上角同一組 `StreamModeToggle`。

### api/cameras.ts

`getCameras()` 從 mock 改為呼叫 `GET /devices`。不改則 `stream_url` 永遠是 `null`。
刪除「後端無此端點」的過時註解。

欄位對照：

| 後端 | 前端 |
| --- | --- |
| `device_id` | `id` |
| `device_name` | `name` |
| `location` | `zone` |
| `floor` | `floor` |
| `stream_url` | `stream_url` |
| `stream_url_detect` | `stream_url_detect` |
| `status: active` | `online` |
| `status: inactive`（人為停用） | `disabled` |
| `status: fault`（故障） | `offline` |

`updateCameraName` 本輪不動。

### types/index.ts

- `Camera` 新增 `stream_url_detect: string | null`
- **刪除 `stream_source` 欄位與 `StreamSource` 型別**。全站 grep 確認零讀取（僅 3 處賦 `null`：
  `mock/cameras.json`、`api/events.ts`），且 `types/index.ts:226` 的註解指向 `CameraDetailModal`
  中不存在的渲染分支。保留會與 `stream_url_detect` 在語意上重疊、造成混淆

### frontend/CLAUDE.md

「即時影像一律灰色占位框、不接真串流」已過期，改為：首頁四宮格與鏡頭彈窗接 WebRTC 真串流；
事件快照仍為占位框，兩者語意不共用。

## 串流環境（新增 streaming/）

| 檔案 | 內容 |
| --- | --- |
| `mediamtx.yml.example` | 以傑雅 `mediamtx-local.yml.example` 為底，移除 HTTPS 與驗證，頻道名改 `cam_in` / `cam_out` ＋ 三個手機頻道 |
| `start-fake-camera.ps1` | ffmpeg 循環推 mp4 至 `rtsp://localhost:8554/cam_in`，供無 AI、無攝影機時使用 |
| `README.md` | 啟動步驟、Windows 防火牆排查（見下）、切換真攝影機的方法、手機推流 App 設定 |

`mediamtx.exe` 與含攝影機帳密的真實設定檔不進 git。

demo 當天切換真攝影機只需改 `mediamtx.yml` 的 `source` 一行，前後端與資料庫不動。

### 四宮格影像來源

| 格 | 來源 | 原味頻道 | 偵測頻道 |
| --- | --- | --- | --- |
| 1 | Tapo 攝影機（RTSP） | `cam_in` | `cam_out` |
| 2-4 | 手機推流 App（如 Larix Broadcaster，走 RTSP） | `phone_a` / `phone_b` / `phone_c` | 無 |

手機採推流 App 而非瀏覽器 `/publish`：瀏覽器開啟裝置鏡頭需要 HTTPS 安全環境，
會把自簽憑證與逐機安裝的流程拉進 A 階段；推流 App 直接推 RTSP 至
`rtsp://<電腦IP>:8554/<頻道名>`，不需 HTTPS。

AI 推論只處理 `cam_in`，因此手機三格的 `stream_url_detect` 為 `null`，
切換至「偵測」時顯示「此鏡頭無 AI 偵測」占位框。

開發期若手邊沒有攝影機與手機，四個頻道皆可用 ffmpeg 推不同 mp4 檔替代。

### ffmpeg 推流參數（來源：albert `start_all.sh`）

`start-fake-camera.ps1` 沿用其低延遲設定，並於註解說明各參數作用：

| 參數 | 作用 |
| --- | --- |
| `-tune zerolatency` | 編碼器不囤積影格，影響延遲最大 |
| `-g 30` | 每 30 影格一個關鍵影格；決定觀眾接上後多久出現畫面（約 1 秒） |
| `-preset ultrafast` | 編碼求快不求小，串流不需省空間 |
| `-an` | 不含音訊，少一條軌即少一種編碼相容問題 |
| `-c:v copy` | 影片檔來源不轉碼，CPU 負擔近零 |
| `-re -stream_loop -1` | 以真實速率播放並無限循環 |
| `-rtsp_transport tcp` | 走 TCP，避免 UDP 掉包造成畫面破格 |

### 防火牆排查（來源：傑雅實測筆記）

- 需開放 TCP 8889（WHEP）、UDP 8189（WebRTC ICE 媒體）
- Windows Defender 會自動為 `mediamtx.exe` 建立兩條 **Block** 規則，
  且封鎖規則優先於允許規則。手動加的 Allow 規則無效時，須停用該 Block 規則
- 手機首次連線時 Chrome 會詢問「允許尋找區域網路上的裝置」，必須允許

## 驗證方式

前端無測試框架（package.json 無 vitest / jest），故分層如下：

| 層 | 方式 |
| --- | --- |
| 後端 | `uv run pytest`：網址組合規則（有無 base × 有無頻道名）、`GET /devices` 回傳結構 |
| 前端 | `npm run build`（tsc + ESLint）通過 |
| 端到端 | 手動：起 MediaMTX ＋ ffmpeg → 首頁四格有畫面 → 切「偵測」→ 點一格放大 → 再點還原 → 開鏡頭彈窗有畫面 → 關閉彈窗後確認 MediaMTX log 顯示讀取者離開 |

## 部署組合：前後端在雲端、MediaMTX 留在本機

此組合可行，且為本設計的預設假設。瀏覽器同時連得到兩邊即可：連雲端網站走網際網路，
連 MediaMTX 走區網（瀏覽器本身就在現場那台電腦上）。

連線方向（決定此組合可行的關鍵）：

| 方向 | A 階段 | 加驗證後 |
| --- | --- | --- |
| 後端 → MediaMTX | 無 | 無。後端只組字串回傳，從不連 MediaMTX |
| MediaMTX → 後端 | 無 | **有**。MediaMTX 由本機主動打向雲端後端問授權，屬對外連線，NAT 不擋 |

因此 MediaMTX 設定需知道後端位址（`authHTTPAddress` 由傑雅版的 `127.0.0.1:8000`
改為雲端位址），反之後端不需知道 MediaMTX 位於何處。串流權杖由後端自簽自驗、
MediaMTX 僅負責轉交，兩者不需共享金鑰。

加驗證後的取捨：雲端後端不可用時，現場將無法觀看任何畫面（每次觀看都需經其授權）。
A 階段沒有此耦合。

### ⚠ 雲端後端的 `.env` 必須設 `MEDIAMTX_BASE_URL`

**demo 前必做，且極易遺漏。** WHEP 網址是由「回應這次請求的那台後端」組出來的，
因此前端連哪台後端，就由哪台後端的 `.env` 決定畫面看不看得到：

| 前端連的後端 | 該後端的 `MEDIAMTX_BASE_URL` | 結果 |
| --- | --- | --- |
| 開發者本機 | 已設 | 有畫面 |
| 雲端 VM | **未設**（2026-07-28 現況） | `stream_url` 回 `null`，前端顯示占位框 |

值填**當天實際跑 MediaMTX 那台電腦的區網 IP**（換場地、換電腦、換 Wi-Fi 都會變），
改完需重啟後端容器。前端不必重新 build。

此設定不影響 AI 端——AI 端讀的是 `stream_channel`（原始頻道名），不經此組合。

**前提：雲端前端必須維持 `http://`。** 目前雲端為純 IP 的 http（`http://35.221.135.197`），
組合成立。若日後為網站加上網域與 HTTPS 憑證，本機的 http MediaMTX 會被瀏覽器以混合內容
封鎖，畫面停在「連線中」、錯誤只出現在 Console，現場極難排查。屆時 MediaMTX 必須一併改用
HTTPS（傑雅的 `mediamtx/generate_cert.py` 與相關流程可直接沿用）。

## 已知限制

1. **觀看者必須與 MediaMTX 在同一個區域網路。** 後端上雲端不影響此限制，因為影像不經後端。
2. **前端若跑在 `https://`，MediaMTX 必須同為 https**，否則瀏覽器以混合內容為由封鎖，無例外可開。
3. **無任何身分驗證。** 同網段任何人知道網址即可觀看即時畫面。僅適用於開發與受控環境。
4. 四宮格 = 同時 4 條 WebRTC 連線，低階機器解碼負擔較高。
5. 頻道名對齊需要 albert 與傑雅配合；未對齊前只有本機假攝影機可測。
6. demo 形式已確認：**現場同一個 Wi-Fi、以團隊自己的電腦展示給評審看，評審不自行連線**。
   因此限制 1 不構成問題，跨網路觀看不在需求內。
7. **AWS RDS 的安全群組可能限制來源 IP，demo 現場能否連上尚未確認。** 連不上會導致整個系統
   （登入、事件、裝置清單）失效，不只串流。須於 demo 前實地驗證或準備備援。
8. 目前 AI 推論只處理 `cam_in` 一條，手機三格暫時沒有偵測畫面。albert 端增加處理路數後，
   只需在資料庫填入對應的偵測頻道名，本專案程式不需改動。

## 下一階段

A 通過後緊接著做串流驗證：MediaMTX `authMethod: http` → `POST /streams/auth`，
前端以登入 JWT 換 60 秒短命串流權杖（`scope=stream`、綁定 path）。
傑雅已有可運作實作可參考，屆時主要工作是改寫成現行專案結構。
須同時處理 AI 端讀取 `cam_in` 的放行（`authHTTPExclude` 或給 AI 端專屬憑證）。

AI 端若增加推論路數、讓手機頻道也有偵測畫面，本專案只需在資料庫填入對應頻道名，程式不需改動；
成本落在 AI 端（每多一路即多一份推論運算，albert 現行設定為單路 `batch-size=1`、`num-sources=1`）。

## 參考來源

| 來源 | 位置 | 用途 |
| --- | --- | --- |
| 傑雅 MediaMTX 筆記 | `AIPE03-3/aipe03-3` 分支 `jieya_hsu`：`RTSP.MediaMTX_20260723/` | 防火牆排查、WebRTC 最小可行網頁 |
| 傑雅完整實作 | 同分支 `kelly_liu/aipe03-3-kelly_liu-mediamtx_20260725/` | `whep.ts` 連線邏輯、`streams/router.py` 驗證、`generate_cert.py` |
| albert AI pipeline | 分支 `albert_chiang`：`start_all.sh`、`Fall/tools/inference_test.py` | `cam_in` / `cam_out` 頻道約定、ffmpeg 推流指令 |

傑雅的實作建立在 2026-07-24 重構前的專案結構上（`backend.core.xxx`、根目錄 `.venv`），
且串流網址走前端 `.env`（build 時寫死，docker 與雲端情境不適用）。
本專案採「參考其做法、程式碼自行撰寫」。
