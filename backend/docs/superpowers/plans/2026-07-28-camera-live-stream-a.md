# 攝影機即時串流（A 階段）實作計畫

> **給執行者：** 本計畫以 superpowers:executing-plans 逐步執行。步驟用 `- [ ]` 追蹤。
> 依使用者慣例：**測試相關步驟可連續跑；寫正式檔案前、以及每個 Task 做完後要停下來確認。**
> **commit 一律由使用者自己執行**，計畫只提供建議訊息。

**目標：** 讓登入者在首頁四宮格與鏡頭彈窗看到 MediaMTX 的即時畫面，並可切換「即時（原味）／偵測（AI 畫框）」。

**架構：** 影像走 `攝影機/手機 → MediaMTX → 瀏覽器 WebRTC`，全程不經後端。
後端唯一職責是把資料庫裡的**頻道名**接上 `.env` 的 MediaMTX 主機位址，組成 WHEP 網址回給前端。

**技術：** FastAPI + SQLAlchemy（後端）、React 19 + TypeScript + Tailwind v4（前端）、MediaMTX + WebRTC/WHEP、ffmpeg。

設計依據：`backend/docs/superpowers/specs/2026-07-28-camera-live-stream-design.md`

## Global Constraints

- 後端指令一律先 `cd backend`；測試用 `uv run pytest`。
  PowerShell 工具（全新 session）改用 `Push-Location backend; & "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest -v; Pop-Location`
- 前端指令一律先 `cd frontend`；驗證用 `npm run build`（含 tsc 與 ESLint）。**前端無測試框架，不要假裝有。**
- 前端鐵律：元件內禁止直接 `fetch`／`axios`；禁止寫死色碼（含 Tailwind 色名如 `red-500`），一律用 `var(--token)`。
- 前端文字一律繁體中文（台灣用語）。
- 頻道名採 AI 端命名 `cam_in`（原味）／`cam_out`（AI 畫框後）；程式碼註解須註明「傑雅版原本叫 `my_camera_tapo`，語意等同 `cam_in`」。
- 頻道名存資料庫，**主機位址存 `.env`**，兩者由後端在執行時組合，不得在前端 build 時寫死。
- commit 訊息結尾**不要**加任何模型署名或 Co-Authored-By。

---

## 檔案結構

| 檔案 | 責任 | 動作 |
| --- | --- | --- |
| `backend/core/config.py` | 新增 `MEDIAMTX_BASE_URL` | 修改 |
| `backend/core/models.py` | `Device` 新增 `stream_url_detect` 欄位 | 修改 |
| `backend/devices/router.py` | `whep_url()` 組網址、`serialize_device` 回兩條 | 修改 |
| `backend/tests/test_devices.py` | 既有斷言補新欄位 | 修改 |
| `backend/tests/test_devices_stream_url.py` | 網址組合規則的測試 | 新增 |
| `.env.example` | 新增 `MEDIAMTX_BASE_URL` 範例 | 修改 |
| `streaming/mediamtx.yml.example` | MediaMTX 設定範本（無 HTTPS、無驗證） | 新增 |
| `streaming/start-fake-camera.ps1` | ffmpeg 推 mp4 當假攝影機 | 新增 |
| `streaming/README.md` | 啟動步驟、防火牆排查、手機推流設定 | 新增 |
| `frontend/src/api/streams.ts` | `negotiateWhep()`，WHEP 的 fetch 只存在此檔 | 新增 |
| `frontend/src/components/LiveStream.tsx` | 吃單一網址、建立／關閉 WebRTC 並播放 | 新增 |
| `frontend/src/components/StreamModeToggle.tsx` | 「即時／偵測」切換鈕 | 新增 |
| `frontend/src/types/index.ts` | 加 `stream_url_detect`、刪 `stream_source` 與 `StreamSource` | 修改 |
| `frontend/src/api/cameras.ts` | 改打真實 `GET /devices` | 修改 |
| `frontend/src/api/events.ts` | 移除 `stream_source`、補 `stream_url_detect` | 修改 |
| `frontend/src/pages/Home.tsx` | 四宮格＋點擊放大＋切換鈕，刪下拉選單 | 修改 |
| `frontend/src/components/CameraDetailModal.tsx` | 占位框改真串流＋切換鈕 | 修改 |
| `frontend/CLAUDE.md` | 更新「不接真串流」的過期規範 | 修改 |

---

## Task 1：後端回傳兩條 WHEP 網址

**Files:**
- Modify: `backend/core/config.py`
- Modify: `backend/core/models.py:77`
- Modify: `backend/devices/router.py`
- Modify: `backend/tests/test_devices.py:14-21`
- Create: `backend/tests/test_devices_stream_url.py`
- Modify: `.env.example`

**Interfaces:**
- Consumes: 無（第一個 Task）
- Produces:
  - `core.config.MEDIAMTX_BASE_URL: str`
  - `core.models.Device.stream_url_detect: Optional[str]`
  - `devices.router.whep_url(channel: str | None) -> str | None`
  - `GET /devices` 每筆多兩個鍵：`stream_url: str | None`、`stream_url_detect: str | None`

- [ ] **Step 1：寫失敗測試（網址組合規則）**

建立 `backend/tests/test_devices_stream_url.py`：

```python
# test_devices_stream_url.py
# 測試頻道名 → WHEP 網址的組合規則（MEDIAMTX_BASE_URL 與頻道名任一為空就回 None）

from core import config
from devices.router import whep_url


def test_whep_url_combines_base_and_channel(monkeypatch):
    # 兩者都有 → 組成 {base}/{頻道名}/whep
    monkeypatch.setattr(config, "MEDIAMTX_BASE_URL", "http://192.168.1.108:8889")
    assert whep_url("cam_in") == "http://192.168.1.108:8889/cam_in/whep"


def test_whep_url_strips_trailing_slash(monkeypatch):
    # .env 結尾多打一個斜線也不該組出兩條斜線
    monkeypatch.setattr(config, "MEDIAMTX_BASE_URL", "http://192.168.1.108:8889/")
    assert whep_url("cam_out") == "http://192.168.1.108:8889/cam_out/whep"


def test_whep_url_returns_none_without_base(monkeypatch):
    # 這個環境沒有設 MediaMTX → 沒有串流可看
    monkeypatch.setattr(config, "MEDIAMTX_BASE_URL", "")
    assert whep_url("cam_in") is None


def test_whep_url_returns_none_without_channel(monkeypatch):
    # 這台裝置沒填頻道名 → 這條串流不存在
    monkeypatch.setattr(config, "MEDIAMTX_BASE_URL", "http://192.168.1.108:8889")
    assert whep_url(None) is None
    assert whep_url("") is None
```

- [ ] **Step 2：寫失敗測試（端點回傳兩條網址）**

在同一個檔案續寫：

```python
def test_get_devices_returns_both_stream_urls(client, auth_headers, db_session, monkeypatch):
    # 裝置兩個頻道都有填 → 端點回兩條組好的網址
    from core.models import Device

    monkeypatch.setattr(config, "MEDIAMTX_BASE_URL", "http://192.168.1.108:8889")
    db_session.add(Device(device_id=90, device_name="測試鏡頭",
                          status="active", company_id=1,
                          stream_url="cam_in", stream_url_detect="cam_out"))
    db_session.commit()

    res = client.get("/devices", headers=auth_headers)
    target = next(d for d in res.json() if d["device_id"] == 90)
    assert target["stream_url"] == "http://192.168.1.108:8889/cam_in/whep"
    assert target["stream_url_detect"] == "http://192.168.1.108:8889/cam_out/whep"


def test_get_devices_detect_none_when_channel_missing(client, auth_headers, db_session, monkeypatch):
    # 手機那類鏡頭沒有偵測頻道 → stream_url_detect 回 null，前端據此顯示「此鏡頭無 AI 偵測」
    from core.models import Device

    monkeypatch.setattr(config, "MEDIAMTX_BASE_URL", "http://192.168.1.108:8889")
    db_session.add(Device(device_id=91, device_name="手機鏡頭",
                          status="active", company_id=1,
                          stream_url="phone_a", stream_url_detect=None))
    db_session.commit()

    res = client.get("/devices", headers=auth_headers)
    target = next(d for d in res.json() if d["device_id"] == 91)
    assert target["stream_url"] == "http://192.168.1.108:8889/phone_a/whep"
    assert target["stream_url_detect"] is None
```

- [ ] **Step 3：更新既有測試的完整比對**

`backend/tests/test_devices.py` 第 14-21 行那個 `assert first == {...}` 是逐鍵完全比對，
多一個鍵就會失敗。改成：

```python
    assert first == {
        "device_id": 1,
        "device_name": "交誼廳-01",
        "location": "交誼廳",
        "floor": None,          # 種子 Location 沒設樓層
        "stream_url": None,     # 種子未填頻道名，且測試環境沒設 MEDIAMTX_BASE_URL
        "stream_url_detect": None,
        "status": "active",
    }
```

- [ ] **Step 4：跑測試確認失敗**

```
cd backend
uv run pytest tests/test_devices_stream_url.py tests/test_devices.py -v
```

預期：`ImportError: cannot import name 'whep_url'`，以及 `Device` 沒有 `stream_url_detect` 屬性。

> ⏸ **停下來給使用者確認**：測試看得懂嗎？要不要調整？確認後再往下寫正式檔案。

- [ ] **Step 5：`core/config.py` 新增設定**

在 S3 那一段後面接著加：

```python
# ── 攝影機即時串流（MediaMTX）──
# 值要含協定與埠號，例如 http://192.168.1.108:8889；留空代表這個環境沒有串流。
# 換場地或換電腦只要改這一個值、重啟後端即可，前端不用重新 build、資料庫不用改。
# ⚠ 前端若跑在 https，這裡必須一併改成 https://——瀏覽器不允許 https 頁面載入 http 串流。
MEDIAMTX_BASE_URL = os.getenv("MEDIAMTX_BASE_URL", "")
```

- [ ] **Step 6：`core/models.py` 新增欄位**

在 `Device` 類別的 `stream_url` 那一行（第 77 行）下面加：

```python
    # 兩個串流欄位存的都是「頻道名」（如 cam_in），不是完整網址；主機位址在 .env
    # stream_url        = 原味頻道（進 AI 前）
    # stream_url_detect = 偵測頻道（AI 畫框後），沒接 AI 的鏡頭留 NULL
    stream_url_detect: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
```

> 注意：改這裡只是讓程式認得這一欄，**既有的 RDS 不會因此多出欄位**，那要靠 Task 2 的 `ALTER TABLE`。

- [ ] **Step 7：`devices/router.py` 加組網址函式並改 `serialize_device`**

檔案上方 import 區加 `from core import config`（**import 模組而非 import 常數**，
這樣測試才能用 `monkeypatch.setattr(config, ...)` 換值）。

在 `serialize_device` 上面新增：

```python
def whep_url(channel: str | None) -> str | None:
    """把資料庫裡的頻道名，接上 .env 的 MediaMTX 位址，組成瀏覽器可用的 WHEP 網址。

    頻道名對齊 AI 端命名：cam_in（進 AI 前的原味）／cam_out（AI 畫框後）。
    傑雅版原本叫 my_camera_tapo，語意等同 cam_in；改名理由是 cam_in/cam_out 描述的是
    「在 AI 的哪一端」，換攝影機廠牌也不會過期。

    位址或頻道名任一為空 → 回 None，代表「這個環境沒有這條串流」，前端據此退回占位框。
    """
    if not config.MEDIAMTX_BASE_URL or not channel:
        return None
    return f"{config.MEDIAMTX_BASE_URL.rstrip('/')}/{channel}/whep"
```

`serialize_device` 內兩行改成：

```python
        "stream_url": whep_url(device.stream_url),
        "stream_url_detect": whep_url(device.stream_url_detect),
```

- [ ] **Step 8：跑測試確認全過**

```
cd backend
uv run pytest -v
```

預期：新檔 6 個測試全 PASS，既有測試無退步。

- [ ] **Step 9：`.env.example` 加一行**

```dotenv
# 攝影機即時串流：MediaMTX 所在主機（含協定與埠號），留空代表本環境沒有串流
# 前端若跑在 https，這裡也要改成 https://
MEDIAMTX_BASE_URL=http://192.168.1.108:8889
```

同時把同樣一行加進你自己的 `.env`（值填實際要用的那台電腦 IP）。

- [ ] **Step 10：提醒使用者 commit**

建議訊息：

```
feat(devices): GET /devices 回傳原味與偵測兩條 WHEP 串流網址
```

> ⏸ **Task 1 完成，停下來給使用者確認。**

---

## Task 2：對 RDS 執行一次性資料庫調整

**Files:** 無程式碼變更（純資料庫操作，由使用者在 DB 工具中執行）

**Interfaces:**
- Consumes: Task 1 的 `Device.stream_url_detect` 欄位定義
- Produces: RDS 的 `devices` 表實際多一欄，且四台裝置都有頻道名

> 全隊共用同一個 AWS RDS，**這段只需一個人跑一次，所有人同步生效**。
> `init_db.py` 幫不上忙：`create_all` 只建不存在的表，不會為既有的表加欄位。

- [ ] **Step 1：確認四句 SQL 的內容**

```sql
-- ⓪ 先加欄位（沒有這句，後面的 UPDATE 會報 column does not exist）
ALTER TABLE devices ADD COLUMN stream_url_detect VARCHAR(255);

-- ① 補兩個區域
INSERT INTO locations (location_name, company_id)
VALUES ('房間01', 1), ('房間02', 1);

-- ② 補兩台裝置（device_id 由資料庫自動編號）
INSERT INTO devices (device_name, location_id, status, company_id)
VALUES
  ('房間01-01', (SELECT location_id FROM locations WHERE location_name='房間01'), 'active', 1),
  ('房間02-01', (SELECT location_id FROM locations WHERE location_name='房間02'), 'active', 1);

-- ③ 四台填入頻道名（用 device_name 比對，因為新裝置的編號由資料庫決定）
UPDATE devices SET stream_url='cam_in',  stream_url_detect='cam_out' WHERE device_name='交誼廳-01';
UPDATE devices SET stream_url='phone_a', stream_url_detect=NULL      WHERE device_name='走廊-01';
UPDATE devices SET stream_url='phone_b', stream_url_detect=NULL      WHERE device_name='房間01-01';
UPDATE devices SET stream_url='phone_c', stream_url_detect=NULL      WHERE device_name='房間02-01';
```

- [ ] **Step 2：使用者執行並確認結果**

跑完用這句檢查：

```sql
SELECT device_id, device_name, stream_url, stream_url_detect FROM devices ORDER BY device_id;
```

預期看到 4 列，第一列 `cam_in` / `cam_out`，其餘三列 `phone_a`/`phone_b`/`phone_c` 且偵測欄為 NULL。

- [ ] **Step 3：用後端實際確認**

啟動後端後（`cd backend; uv run uvicorn main:app --reload`），登入取得 token，
呼叫 `GET /devices`，確認四台都回了組好的網址。

> ⏸ **Task 2 完成，停下來給使用者確認。**

---

## Task 3：串流環境（假攝影機可以出畫面）

**Files:**
- Create: `streaming/mediamtx.yml.example`
- Create: `streaming/start-fake-camera.ps1`
- Create: `streaming/README.md`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: 無
- Produces: `http://<電腦IP>:8889/cam_in/whep` 等四個可播放的 WHEP 端點

> 這個 Task 排在前端之前，是因為**沒有畫面來源就無法驗證前端**。

- [ ] **Step 1：建立 `streaming/mediamtx.yml.example`**

```yaml
# MediaMTX 設定範本（A 階段：區網、無 HTTPS、無驗證）
# 用法：複製成 mediamtx.yml，放在 mediamtx.exe 旁邊，然後 .\mediamtx.exe .\mediamtx.yml
#
# 頻道命名對齊 AI 端：cam_in（進 AI 前的原味）／cam_out（AI 畫框後）。
# 傑雅版原本叫 my_camera_tapo，語意等同 cam_in。

webrtc: yes
webrtcAddress: :8889          # 瀏覽器來報到用（WHEP）
webrtcLocalUDPAddress: :8189  # 影像實際流動用（ICE），防火牆兩個都要開
webrtcAllowOrigins: ["*"]     # A 階段全開；正式環境改成前端網址白名單
webrtcIPsFromInterfaces: yes

rtsp: yes
rtspAddress: :8554            # ffmpeg 與手機推流 App 往這裡推

paths:
  # 真攝影機：demo 當天把 source 換成下面註解那行即可，前後端與資料庫都不用動
  cam_in:
    source: publisher
    # source: rtsp://<攝影機帳號>:<攝影機密碼>@<攝影機IP>:554/stream2
    # rtspTransport: tcp

  # AI 畫框後推回來的頻道（albert 的推論程式負責推流）
  cam_out:
    source: publisher

  # 手機推流 App（Larix Broadcaster 之類）推到這三個
  phone_a:
    source: publisher
  phone_b:
    source: publisher
  phone_c:
    source: publisher
```

- [ ] **Step 2：建立 `streaming/start-fake-camera.ps1`**

```powershell
# 用一支 mp4 假裝成攝影機，推進 MediaMTX 的指定頻道。
# 用法：.\start-fake-camera.ps1 -Video ..\frontend\public\videos\fall-demo.mp4 -Channel cam_in
#
# 參數說明（沿用 albert start_all.sh 的低延遲設定）：
#   -re              用真實速度播放（不加會用最快速度衝完）
#   -stream_loop -1  無限循環
#   -an              不要聲音：少一條軌就少一種編碼相容問題
#   -c:v copy        完全不轉碼，CPU 負擔近乎零（前提是來源已是 H.264）
#   -rtsp_transport tcp  走 TCP，避免 UDP 掉包造成畫面破格
param(
    [Parameter(Mandatory = $true)][string]$Video,
    [string]$Channel = "cam_in",
    [string]$MediaMtxHost = "localhost"
)

if (-not (Test-Path $Video)) {
    Write-Error "找不到影片檔：$Video"
    exit 1
}

$target = "rtsp://${MediaMtxHost}:8554/${Channel}"
Write-Host "推流中：$Video -> $target（Ctrl+C 停止）"

ffmpeg -nostdin -re -stream_loop -1 -i $Video -an -c:v copy -rtsp_transport tcp -f rtsp $target
```

> 若來源 mp4 不是 H.264，`-c:v copy` 會失敗。改用這組轉碼參數（同樣抄自 albert）：
> `-an -c:v libx264 -preset ultrafast -tune zerolatency -g 30 -r 30`
> 其中 `-tune zerolatency`（編碼器不囤積影格）與 `-g 30`（每秒一張完整影格，
> 決定觀眾接上後多久看到畫面）對延遲影響最大。

- [ ] **Step 3：建立 `streaming/README.md`**

````markdown
# 串流環境（MediaMTX）

影像走 `攝影機/手機 → MediaMTX → 瀏覽器`，**完全不經過後端**。
後端只負責告訴前端「MediaMTX 在哪、要看哪個頻道」。

## 頻道

| 頻道 | 內容 | 誰推進來 |
| --- | --- | --- |
| `cam_in` | 原始畫面 | Tapo 攝影機，或 ffmpeg 推 mp4 |
| `cam_out` | AI 畫框後 | albert 的推論程式 |
| `phone_a` / `phone_b` / `phone_c` | 手機畫面 | 手機推流 App |

（傑雅版原本叫 `my_camera_tapo`，語意等同 `cam_in`。）

## 啟動步驟

1. 下載 MediaMTX（Windows 版），解壓到本資料夾，**`mediamtx.exe` 不進 git**
2. `Copy-Item mediamtx.yml.example mediamtx.yml`，需要接真攝影機時再改 `cam_in` 的 `source`
3. `.\mediamtx.exe .\mediamtx.yml`，看到 `[WebRTC] started with listeners on :8889` 就是成功
4. 查自己的區網 IP：

   ```powershell
   Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -like '192.168.*' } |
     Select-Object InterfaceAlias, IPAddress
   ```

5. 把 IP 填進後端 `.env` 的 `MEDIAMTX_BASE_URL=http://<你的IP>:8889`，重啟後端

## 沒有攝影機時：用影片檔當假攝影機

```powershell
.\start-fake-camera.ps1 -Video ..\frontend\public\videos\fall-demo.mp4 -Channel cam_in
```

四個頻道要都有畫面就開四個視窗、各推一個頻道。

## 手機當鏡頭

手機裝推流 App（如 Larix Broadcaster），推流位址填：

```
rtsp://<電腦IP>:8554/phone_a
```

> 不要用手機瀏覽器的 `/publish` 頁面——那需要 HTTPS 與自簽憑證（每支手機都要安裝並信任），
> A 階段刻意不做。

## 防火牆（來源：傑雅實測筆記，這一段能省你好幾小時）

手機或別台電腦看不到畫面時，依序檢查：

| Protocol | Port | 用途 |
| --- | ---: | --- |
| TCP | 8889 | WHEP 報到 |
| UDP | 8189 | WebRTC 影像流動 |
| TCP | 8554 | RTSP 推流 |

```powershell
New-NetFirewallRule -DisplayName "MediaMTX WHEP 8889" -Direction Inbound -Protocol TCP -LocalPort 8889 -Action Allow
New-NetFirewallRule -DisplayName "MediaMTX ICE 8189" -Direction Inbound -Protocol UDP -LocalPort 8189 -Action Allow
New-NetFirewallRule -DisplayName "MediaMTX RTSP 8554" -Direction Inbound -Protocol TCP -LocalPort 8554 -Action Allow
```

**⚠ 加了 Allow 規則還是不通，而且 MediaMTX 的 log 連一筆請求都沒有？**

Windows Defender 會**自動**為 `mediamtx.exe` 建立兩條 **Block** 規則，
而**封鎖規則優先於允許規則**。到「具進階安全性的 Windows Defender 防火牆 → 輸入規則」，
找到名稱含 MediaMTX、動作為「封鎖」的兩條，**停用它們**（建議停用不要刪除）。

另外手機第一次連線時，Chrome 會問「允許尋找區域網路上的裝置」，必須按允許。

## 常見狀況

| 現象 | 原因 |
| --- | --- |
| 畫面一直停在「連線中」 | 頻道沒有人在推流（MediaMTX log 沒有 `is available and online`） |
| WHEP 回 404 | 頻道名打錯，或該頻道目前沒有來源 |
| WHEP 回 201 但沒畫面 | UDP 8189 被擋 |
| Console 出現 mixed content | 前端是 https 而 MediaMTX 是 http，必須兩邊一致 |
````

- [ ] **Step 4：`.gitignore` 加排除**

```gitignore
# 串流：執行檔與含攝影機帳密的實際設定不進 git
streaming/mediamtx.exe
streaming/mediamtx.yml
streaming/*.log
```

- [ ] **Step 5：實際跑一次確認出得了畫面**

1. 依 README 啟動 MediaMTX
2. 開一個視窗跑 `start-fake-camera.ps1` 推 `cam_in`
3. 瀏覽器開 `http://<你的IP>:8889/cam_in`，**應該看到影片在播**

這一步是後面所有前端工作的地基，沒過不要往下。

- [ ] **Step 6：提醒使用者 commit**

```
feat(streaming): 新增 MediaMTX 設定範本、假攝影機腳本與啟動說明
```

> ⏸ **Task 3 完成，停下來給使用者確認。**

---

## Task 4：前端資料層接真後端

**Files:**
- Modify: `frontend/src/types/index.ts:209-228`
- Modify: `frontend/src/api/cameras.ts`
- Modify: `frontend/src/api/events.ts:55-66`

**Interfaces:**
- Consumes: Task 1 的 `GET /devices` 回傳格式
- Produces: `Camera.stream_url: string | null`、`Camera.stream_url_detect: string | null`（皆為完整 WHEP 網址）；
  `getCameras(): Promise<Camera[]>` 改為真實資料

- [ ] **Step 1：`types/index.ts` 改型別**

刪掉第 209-214 行的 `StreamSource` 型別（全站 grep 過，零讀取），
`Camera` 介面改成：

```ts
export interface Camera {
  id: number;
  name: string;              // 鏡頭5
  zone: string;              // 活動室A（區域分組，無樓層層）
  floor: string | null;      // demo 一律不顯示
  // 兩條完整的 WHEP 網址，由後端把資料庫的頻道名接上 .env 的 MediaMTX 位址組成。
  // null＝這個環境沒有這條串流（沒設 MEDIAMTX_BASE_URL，或這台鏡頭沒填該頻道）。
  stream_url: string | null;        // 即時（原味）
  stream_url_detect: string | null; // 偵測（AI 畫框後），沒接 AI 的鏡頭為 null
  status: DeviceStatus;      // 取代原本 online 布林，支援離線/已停用分開判斷
}
```

- [ ] **Step 2：`api/cameras.ts` 改打真後端**

整檔換成：

```ts
import { apiClient } from './client';
import type { Camera, DeviceStatus } from '../types';

// 後端 GET /devices 的原始欄位命名，與前端 Camera 不同，須經下方對照轉換。
interface RawDevice {
  device_id: number;
  device_name: string;
  location: string | null;
  floor: string | null;
  stream_url: string | null;
  stream_url_detect: string | null;
  status: 'active' | 'inactive' | 'fault';
}

// 後端字彙 → 前端字彙。inactive＝人為停用、fault＝故障，語意不同不可合併。
const STATUS_MAP: Record<RawDevice['status'], DeviceStatus> = {
  active: 'online',
  inactive: 'disabled',
  fault: 'offline',
};

export async function getCameras(): Promise<Camera[]> {
  const devices = await apiClient.get<RawDevice[]>('/devices');
  return devices.map((d) => ({
    id: d.device_id,
    name: d.device_name,
    zone: d.location ?? '',
    floor: d.floor,
    stream_url: d.stream_url,
    stream_url_detect: d.stream_url_detect,
    status: STATUS_MAP[d.status],
  }));
}

// 改名端點 PATCH /devices/{id} 後端已就緒，但本輪範圍不含它，維持前端 mock 行為。
export async function updateCameraName(id: number, name: string): Promise<void> {
  console.info(`updateCameraName 尚未串接後端，camera id：${id}，新名稱：${name}`);
}
```

- [ ] **Step 3：`api/events.ts` 同步改**

第 55-66 行 `parseRawEvent` 裡組 `Camera` 的地方，把 `stream_source: null` 刪掉、
補上 `stream_url_detect: null`：

```ts
    // 後端事件 payload 無串流網址與在線狀態（僅 GET /devices 有），先固定值，非程式邏輯遺漏。
    stream_url: null,
    stream_url_detect: null,
    status: 'online',
```

- [ ] **Step 4：刪掉 mock 檔的相關欄位**

`frontend/src/api/mock/cameras.json` 三列的 `"stream_source": null` 刪除
（此檔在 `getCameras` 改真後端後已無人引用，但先留著不刪檔，避免其他頁面意外引用時整包炸掉；
若 `npm run build` 顯示它已無任何 import，可一併刪除該檔）。

- [ ] **Step 5：驗證**

```
cd frontend
npm run build
```

預期：通過。若出現 `stream_source` 相關錯誤，代表還有漏改的地方，照錯誤訊息補。

- [ ] **Step 6：跑起來看清單**

`npm run dev`，登入後開監控頁，確認**鏡頭清單顯示的是資料庫那四台**（交誼廳-01、走廊-01、房間01-01、房間02-01），
不再是 mock 的「鏡頭3／鏡頭11／鏡頭7」。

- [ ] **Step 7：提醒使用者 commit**

```
feat(frontend): 鏡頭清單改接真實 GET /devices，移除未使用的 stream_source
```

> ⏸ **Task 4 完成，停下來給使用者確認。**

---

## Task 5：LiveStream 元件（單格能播出畫面）

**Files:**
- Create: `frontend/src/api/streams.ts`
- Create: `frontend/src/components/LiveStream.tsx`

**Interfaces:**
- Consumes: Task 4 的 `Camera.stream_url`
- Produces:
  - `negotiateWhep(whepUrl: string, offerSdp: string): Promise<string>`
  - `<LiveStream whepUrl={string | null} emptyLabel?={string} />`

- [ ] **Step 1：建立 `frontend/src/api/streams.ts`**

```ts
/**
 * 與 MediaMTX 做 WHEP 協商：送出我方的 SDP offer，取回對方的 SDP answer。
 *
 * SDP 可以想成通話前互相交換的「自我介紹小紙條」：寫著我聽得懂哪些編碼、
 * 我的位址是什麼、我只想收不想送。兩邊交換完就知道怎麼傳影像。
 *
 * 不走 client.ts：目標是 MediaMTX 而非本專案後端，不需要帶登入 token，
 * 且內容是純文字 SDP（application/sdp）不是 JSON。
 * 放在 api/ 是為了遵守「元件內禁止直接 fetch」的鐵律。
 */
export async function negotiateWhep(whepUrl: string, offerSdp: string): Promise<string> {
  const res = await fetch(whepUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/sdp' },
    body: offerSdp,
  });
  if (!res.ok) {
    throw new Error(`MediaMTX 回應 ${res.status}`);
  }
  return res.text();
}
```

- [ ] **Step 2：建立 `frontend/src/components/LiveStream.tsx`**

```tsx
import { useEffect, useRef, useState } from 'react';
import { negotiateWhep } from '../api/streams';
import { CAMERA_LABEL } from '../types';

type ConnectionState = 'connecting' | 'connected' | 'failed';

interface LiveStreamProps {
  /** 完整 WHEP 網址；null＝這個環境沒有這條串流，顯示占位框 */
  whepUrl: string | null;
  /** 占位框文字。預設「鏡頭即時影像」；偵測模式下沒有 AI 的鏡頭傳「此鏡頭無 AI 偵測」 */
  emptyLabel?: string;
}

/**
 * 等 ICE candidate 收集完再送出 SDP：一次帶齊所有候選路徑，
 * 省掉逐筆傳送的來回協商（MediaMTX 支援這種一次性做法）。
 */
function waitForIceGathering(pc: RTCPeerConnection): Promise<void> {
  if (pc.iceGatheringState === 'complete') return Promise.resolve();
  return new Promise((resolve) => {
    const onChange = () => {
      if (pc.iceGatheringState !== 'complete') return;
      pc.removeEventListener('icegatheringstatechange', onChange);
      resolve();
    };
    pc.addEventListener('icegatheringstatechange', onChange);
  });
}

export function LiveStream({ whepUrl, emptyLabel = CAMERA_LABEL.LIVE_PLACEHOLDER }: LiveStreamProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [state, setState] = useState<ConnectionState>('connecting');
  // 遞增此值即觸發重新連線（重試按鈕用）
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const video = videoRef.current;
    if (!whepUrl || !video) return;

    let cancelled = false;
    setState('connecting');

    const pc = new RTCPeerConnection({ iceServers: [] });
    // 這個頁面只收影像、不送影像
    pc.addTransceiver('video', { direction: 'recvonly' });

    pc.ontrack = (event) => {
      video.srcObject = event.streams[0] ?? new MediaStream([event.track]);
      // 自動播放被瀏覽器擋下時不需要報錯，畫面停在第一格即可
      void video.play().catch(() => undefined);
    };

    pc.onconnectionstatechange = () => {
      if (cancelled) return;
      if (pc.connectionState === 'connected') setState('connected');
      if (pc.connectionState === 'failed' || pc.connectionState === 'disconnected') setState('failed');
    };

    void (async () => {
      try {
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        await waitForIceGathering(pc);
        const answer = await negotiateWhep(whepUrl, pc.localDescription?.sdp ?? '');
        if (cancelled) return;
        await pc.setRemoteDescription({ type: 'answer', sdp: answer });
      } catch {
        if (!cancelled) setState('failed');
      }
    })();

    // 元件收掉或換頻道時務必關閉：SPA 不關會讓連線一直累積、佔用頻寬與 MediaMTX 讀取者名額
    return () => {
      cancelled = true;
      pc.ontrack = null;
      pc.onconnectionstatechange = null;
      pc.close();
      video.srcObject = null;
    };
  }, [whepUrl, attempt]);

  if (!whepUrl) {
    return (
      <div className="flex h-full w-full items-center justify-center bg-[var(--bg-surface-2)] text-center text-sm text-[var(--text-muted)]">
        {emptyLabel}
      </div>
    );
  }

  return (
    <div className="relative h-full w-full bg-black">
      <video ref={videoRef} autoPlay muted playsInline className="h-full w-full object-contain" />
      {state !== 'connected' && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-[var(--bg-surface-2)] text-sm text-[var(--text-muted)]">
          <span>{state === 'failed' ? '連線失敗' : '連線中…'}</span>
          {state === 'failed' && (
            <button
              type="button"
              onClick={() => setAttempt((n) => n + 1)}
              className="rounded-lg border border-[var(--border)] px-3 py-1 text-[var(--text-secondary)] transition-colors duration-150 hover:bg-[var(--brand-soft)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)]"
            >
              重新連線
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export default LiveStream;
```

> 若 `--brand` / `--brand-soft` 在現行 `styles/tokens.css` 已被改名（例如首頁已改用 `--highlight`），
> 改用該檔實際存在的 token，**不要寫死色碼**。

- [ ] **Step 3：驗證**

```
cd frontend
npm run build
```

- [ ] **Step 4：暫時接到首頁確認能出畫面**

在 `Home.tsx` 現有的灰色占位框 `<div>`（第 144-153 行）裡，暫時把
`{CAMERA_LABEL.LIVE_PLACEHOLDER}` 換成 `<LiveStream whepUrl={cameras[0]?.stream_url ?? null} />`，
跑 `npm run dev` 確認**畫面真的出來**。

確認完先還原（下一個 Task 會正式改這一塊），或直接留著讓 Task 6 接續改。

- [ ] **Step 5：提醒使用者 commit**

```
feat(frontend): 新增 WHEP 協商與 LiveStream 即時畫面元件
```

> ⏸ **Task 5 完成，停下來給使用者確認。這是第一次看到真畫面，值得停久一點。**

---

## Task 6：首頁四宮格與即時／偵測切換

**Files:**
- Create: `frontend/src/components/StreamModeToggle.tsx`
- Modify: `frontend/src/pages/Home.tsx`

**Interfaces:**
- Consumes: Task 5 的 `<LiveStream>`、Task 4 的 `Camera`
- Produces:
  - `type StreamMode = 'live' | 'detect'`
  - `<StreamModeToggle value={StreamMode} onChange={(m: StreamMode) => void} />`

- [ ] **Step 1：建立 `frontend/src/components/StreamModeToggle.tsx`**

```tsx
export type StreamMode = 'live' | 'detect';

// 顯示文字集中一份，元件外禁止另外硬編碼
export const STREAM_MODE_LABEL: Record<StreamMode, string> = {
  live: '即時',
  detect: '偵測',
};

const MODES: StreamMode[] = ['live', 'detect'];

interface StreamModeToggleProps {
  value: StreamMode;
  onChange: (mode: StreamMode) => void;
}

/** 「即時／偵測」切換：即時＝原味畫面（cam_in），偵測＝AI 畫框後（cam_out）。 */
export function StreamModeToggle({ value, onChange }: StreamModeToggleProps) {
  return (
    <div role="group" aria-label="畫面來源" className="flex gap-1">
      {MODES.map((mode) => {
        const active = mode === value;
        return (
          <button
            key={mode}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(mode)}
            className={`rounded-lg px-3 py-1.5 text-sm transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)] ${
              active
                ? 'bg-[var(--brand-soft)] font-medium text-[var(--brand)]'
                : 'text-[var(--text-secondary)] hover:bg-[var(--bg-surface-2)]'
            }`}
          >
            {STREAM_MODE_LABEL[mode]}
          </button>
        );
      })}
    </div>
  );
}

export default StreamModeToggle;
```

- [ ] **Step 2：`Home.tsx` 加入狀態與取網址的邏輯**

在元件內既有的 `useState` 附近加：

```tsx
  // 四宮格固定顯示前四台（GET /devices 依 device_id 排序）
  const gridCameras = cameras.slice(0, 4);
  const [streamMode, setStreamMode] = useState<StreamMode>('live');
  // 被放大的鏡頭 id；null＝四宮格模式
  const [expandedId, setExpandedId] = useState<number | null>(null);

  // 偵測模式取 stream_url_detect，即時模式取 stream_url
  const urlOf = (camera: Camera) =>
    streamMode === 'detect' ? camera.stream_url_detect : camera.stream_url;

  // 四台都沒有偵測頻道就不顯示切換鈕（按了也只會看到四格空白）
  const hasAnyDetect = gridCameras.some((c) => c.stream_url_detect !== null);
```

移除 `selectedCameraId` 與 `selectedCamera` 相關狀態（下拉選單一併刪除）。

- [ ] **Step 3：`Home.tsx` 換掉畫面區塊**

把第 144-157 行（灰色占位框 ＋ 手機版下拉選單）整段換成：

```tsx
          {/* 即時影像：2×2 四宮格。點任一格放大成單一畫面、再點還原。
              放大時其餘三格改用 CSS 隱藏而非卸載——連線數上限與四宮格相同，
              但切換不必重新連線，不會有黑畫面。 */}
          <div className="flex items-center justify-end">
            {hasAnyDetect && <StreamModeToggle value={streamMode} onChange={setStreamMode} />}
          </div>

          <div className={expandedId === null ? 'grid grid-cols-2 gap-3' : 'grid grid-cols-1'}>
            {gridCameras.map((camera) => {
              const expanded = expandedId === camera.id;
              const hidden = expandedId !== null && !expanded;
              return (
                <button
                  key={camera.id}
                  type="button"
                  onClick={() => setExpandedId(expanded ? null : camera.id)}
                  aria-label={expanded ? `縮小 ${camera.name}` : `放大 ${camera.name}`}
                  className={`relative aspect-video w-full overflow-hidden rounded-2xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)] ${
                    hidden ? 'hidden' : ''
                  }`}
                >
                  <LiveStream
                    whepUrl={urlOf(camera)}
                    emptyLabel={
                      streamMode === 'detect' && camera.stream_url_detect === null
                        ? '此鏡頭無 AI 偵測'
                        : undefined
                    }
                  />
                  <span className="absolute left-3 top-3 rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-2 py-0.5 text-xs text-[var(--text-secondary)]">
                    {camera.zone}（{camera.name}）
                  </span>
                </button>
              );
            })}

            {/* 裝置不足 4 台時補空格，維持 2×2 版面 */}
            {expandedId === null &&
              Array.from({ length: Math.max(0, 4 - gridCameras.length) }).map((_, i) => (
                <div
                  key={`empty-${i}`}
                  className="flex aspect-video w-full items-center justify-center rounded-2xl bg-[var(--bg-surface-2)] text-sm text-[var(--text-muted)]"
                >
                  {CAMERA_LABEL.LIVE_PLACEHOLDER}
                </div>
              ))}
          </div>
```

- [ ] **Step 4：刪除下拉選單**

- 刪除桌機版右欄那段（原第 238-241 行的 `<div className="hidden lg:block">` 連同內部 `<CameraSelect>`）
- 刪除檔案上方 `CameraSelect` 函式本體（原第 12 行起）
- 刪除因此不再使用的 import 與狀態

- [ ] **Step 5：驗證**

```
cd frontend
npm run build
```

預期通過且沒有 unused variable 警告。

- [ ] **Step 6：手動確認四項行為**

1. 首頁出現 2×2 四格，都有畫面
2. 點某一格 → 放大成單一畫面；再點 → 回四宮格
3. 右上角切「偵測」→ 交誼廳那格換成有框畫面，另外三格顯示「此鏡頭無 AI 偵測」
4. 切回「即時」→ 四格都恢復

- [ ] **Step 7：提醒使用者 commit**

```
feat(frontend): 首頁改為四宮格即時畫面，支援點擊放大與即時/偵測切換
```

> ⏸ **Task 6 完成，停下來給使用者確認。**

---

## Task 7：鏡頭彈窗與規範更新

**Files:**
- Modify: `frontend/src/components/CameraDetailModal.tsx:105-107`
- Modify: `frontend/CLAUDE.md`

**Interfaces:**
- Consumes: Task 5 的 `<LiveStream>`、Task 6 的 `<StreamModeToggle>`
- Produces: 無（末端消費者）

- [ ] **Step 1：`CameraDetailModal.tsx` 換掉占位框**

在元件內加狀態：

```tsx
  const [streamMode, setStreamMode] = useState<StreamMode>('live');
  const streamUrl = streamMode === 'detect' ? camera.stream_url_detect : camera.stream_url;
```

把第 105-107 行的灰色占位框換成：

```tsx
        <div className="flex items-center justify-end">
          {camera.stream_url_detect !== null && (
            <StreamModeToggle value={streamMode} onChange={setStreamMode} />
          )}
        </div>

        <div className="aspect-video w-full overflow-hidden rounded-xl">
          <LiveStream
            whepUrl={streamUrl}
            emptyLabel={
              streamMode === 'detect' && camera.stream_url_detect === null
                ? '此鏡頭無 AI 偵測'
                : undefined
            }
          />
        </div>
```

- [ ] **Step 2：更新 `frontend/CLAUDE.md` 的過期規範**

「後端銜接注意」那一段裡，把

> 即時影像一律灰色占位框＋「鏡頭即時影像」文字，不接真串流

改成：

```markdown
- 即時影像已接真串流（WebRTC/WHEP，見 `components/LiveStream.tsx`）：
  首頁四宮格與鏡頭彈窗皆播放實際畫面，網址由 `GET /devices` 提供（`stream_url`＝即時、
  `stream_url_detect`＝AI 偵測）。網址為 null 時才退回灰色占位框。
  事件／偵測紀錄的截圖仍是「事件快照（影像片段）」，兩者語意不同、不共用文字。
```

- [ ] **Step 3：驗證**

```
cd frontend
npm run build
```

- [ ] **Step 4：手動確認**

監控頁點任一列 → 彈窗出現即時畫面；有偵測頻道的鏡頭才顯示切換鈕；
**關閉彈窗後，MediaMTX 的 log 應顯示讀取者離開**（確認連線有正確關閉，沒有洩漏）。

- [ ] **Step 5：提醒使用者 commit**

```
feat(frontend): 鏡頭彈窗接上即時串流，更新前端串流規範
```

> ⏸ **Task 7 完成，停下來給使用者確認。**

---

## Task 8：端到端驗收

**Files:** 無變更

- [ ] **Step 1：後端測試全過**

```
cd backend
uv run pytest -v
```

- [ ] **Step 2：前端建置全過**

```
cd frontend
npm run build
```

- [ ] **Step 3：完整流程走一次**

1. 啟動 MediaMTX，四個頻道各推一路來源（或至少 `cam_in`）
2. 啟動後端（`.env` 的 `MEDIAMTX_BASE_URL` 填對）
3. 啟動前端，登入
4. 首頁四格有畫面 → 切「偵測」→ 點一格放大 → 再點還原 → 切回「即時」
5. 進監控頁 → 點一列 → 彈窗有畫面 → 關閉
6. 檢查 MediaMTX log：讀取者數量在關閉頁面後回到 0（**確認沒有連線洩漏**）

- [ ] **Step 4：確認退場行為**

把後端 `.env` 的 `MEDIAMTX_BASE_URL` 清空、重啟後端 → 前端所有畫面應**退回灰色占位框**，
不應出現錯誤或空白破版。這證明沒有 MediaMTX 的環境（例如 CI、其他組員機器）也不會壞。

- [ ] **Step 5：提醒使用者 commit 並更新文件**

若過程中發現 README 有缺漏，補進 `streaming/README.md` 後一併 commit。

> ⏸ **A 階段完成。下一階段是串流身分驗證（`/streams/auth` ＋ 60 秒短命權杖），
> 傑雅已有可參考的實作，屆時另寫計畫。**
