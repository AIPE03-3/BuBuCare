# 串流環境（MediaMTX）

## 這在做什麼（先看這段）

把攝影機的畫面送到瀏覽器上，讓護理站看得到即時影像。

```
攝影機 / 手機 ──→ MediaMTX ──→ 瀏覽器
                （這台轉播機器）
```

**影像完全不經過後端。** 後端只做兩件事：告訴前端「MediaMTX 在哪一台、要看哪個頻道」，
以及在有人要看的時候幫忙驗身分。

---

## 名詞白話對照

第一次看這份文件的話，先建立這幾個詞：

| 名詞 | 白話 |
|---|---|
| **MediaMTX** | 一台「影像轉播機」。攝影機把畫面送給它，它再分送給所有想看的瀏覽器 |
| **推流（publish）** | 把畫面**送進**MediaMTX。手機、ffmpeg、攝影機做的就是這件事 |
| **拉流 / 讀取（read）** | 從 MediaMTX **取出**畫面來看。瀏覽器、AI 端做的是這件事 |
| **頻道（path）** | 一條影像通道的名字，例如 `cam_in`。要先在設定檔登記，沒登記的會被拒收 |
| **RTSP** | 攝影機與手機推流用的老牌協定。走 **8554** 埠 |
| **WebRTC / WHEP** | 瀏覽器看即時影像用的協定。報到走 **8889**（TCP），影像本身走 **8189**（UDP） |
| **權杖（token）** | 一張 60 秒的短命門票。瀏覽器要先跟後端換到票，才看得到畫面 |

> **兩個埠都要通**，這是最常見的卡關點：8889 只負責「報到」，
> 真正的影像走 8189/UDP。8189 被擋的話會出現「連上了但沒畫面」。

---

## 頻道一覽

| 頻道 | 內容 | 誰推進來 |
| --- | --- | --- |
| `cam_in` | 原始畫面 | Tapo 攝影機（MediaMTX 主動去拉），或用 ffmpeg 推 mp4 頂替 |
| `cam_out` | 畫框後的畫面 | ⚠️ **2026-07-31 起已不使用**，見下方說明 |
| `phone_a` / `phone_b` / `phone_c` | 手機畫面 | 手機推流 App |

（傑雅版原本叫 `my_camera_tapo`，語意等同 `cam_in`。）

### ⚠️ `cam_out` 已經廢止（2026-07-31）

**舊做法**：AI 端把偵測框「燒」進畫面，重新編碼一次推回 `cam_out`，前端切頻道看。

**現在**：AI 端只送**座標**給後端，瀏覽器用 canvas 自己把骨架疊在影像上。

| | 舊（`cam_out`）| 新（canvas 疊圖）|
|---|---|---|
| 開關 | `DETECT_STREAM=1`（**已移除**）| `DETECT_BROADCAST=1` |
| AI 端成本 | 每路多一支 ffmpeg 即時編碼 | 一次幾 KB 的座標 POST |
| 切換即時／偵測 | 換一條串流網址，畫面會黑一下 | 只是多疊一層，影像不斷 |
| 用 VLC 等外部播放器 | 看得到框 | **看不到**（框不在影像裡）← 換過來的代價 |

所以**這份文件裡與 `cam_out` 有關的設定，現在都不需要了**。
細節記錄於專案內部的整合文件。

---

# Windows 的跑法

（Linux / WSL2 請直接跳到後面的「Linux / WSL2 的跑法」。）

## 一、準備

1. 下載 MediaMTX Windows 版（<https://github.com/bluenviron/mediamtx/releases>，
   選 `mediamtx_vX.X.X_windows_amd64.zip`），解壓到本資料夾。
   **`mediamtx.exe` 不進 git。**
2. 複製設定檔：

   ```powershell
   Copy-Item mediamtx.yml.example mediamtx.yml
   ```

3. 編輯 `mediamtx.yml` 的 `cam_in`，填入攝影機帳密與 IP。
   **這個檔案含帳密，不進 git。**
4. ffmpeg 只有在需要假畫面時才用得到：

   ```powershell
   winget install Gyan.FFmpeg
   ```

   裝完要**開一個新的終端機**才吃得到 PATH。

### Tapo C210 的 RTSP 帳密要另外設

**不是** TP-Link 的登入帳號，是另一組專門給 RTSP 用的：

```
Tapo App → 選這台攝影機 → 右上角齒輪 → 進階設定 → 攝影機帳號
```

> ⚠️ **沒設這一步，RTSP 會直接被拒絕連線**，而且錯誤訊息看起來像是網路問題，很容易查錯方向。

路徑有兩個：`stream1` = 1080p、`stream2` = 360p。**先用 `stream2`**，比較不吃頻寬。

## 二、啟動

```powershell
.\mediamtx.exe .\mediamtx.yml
```

**怎麼確認起來了** —— 看 log：

| log 出現這行 | 代表 |
|---|---|
| `[WebRTC] listener opened on :8889` | MediaMTX 起來了 ✅ |
| `[RTSP source] ready` | 攝影機也連上了 ✅ |
| 沒有 `[RTSP source] ready` | 攝影機連不上，多半是帳密或 IP 錯 ❌ |

查自己電腦的區網 IP：

```powershell
Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -like '192.168.*' } |
  Select-Object InterfaceAlias, IPAddress
```

### 找攝影機的 IP（換 Wi-Fi 就會變，不是固定的）

Tapo App 的裝置資訊裡看得到。查不到的話從電腦掃 —— RTSP 用 554 埠，開著的那台就是攝影機：

```powershell
$ips = 1..254 | ForEach-Object { "192.168.54.$_" }   # 換成你的網段
$tasks = @()
foreach ($ip in $ips) { $p = New-Object System.Net.NetworkInformation.Ping; $tasks += ,@($ip, $p.SendPingAsync($ip, 800)) }
Start-Sleep -Milliseconds 1500
foreach ($t in $tasks) {
  if ($t[1].IsCompleted -and $t[1].Result.Status -eq 'Success') {
    if (Test-NetConnection -ComputerName $t[0] -Port 554 -InformationLevel Quiet -WarningAction SilentlyContinue) { "$($t[0]) ← 攝影機" }
  }
}
```

找到 IP 後填進**後端**的 `.env`，然後重啟後端：

```
MEDIAMTX_BASE_URL=http://<你的IP>:8889
```

（前端不用重新 build —— 網址是後端在回應請求時才組出來的。）

### ⚠️ 「後端」是指前端實際連的那一台

觀看網址是由**回應請求的那台後端**組出來的，所以要設在哪，取決於前端連的是誰：

| 情境 | 要設 `MEDIAMTX_BASE_URL` 的地方 |
| --- | --- |
| 本機開發（前端連 localhost:8000） | 你自己的 `.env` |
| 用雲端網站看（`http://35.221.135.197`） | **雲端 VM 上的 `/var/project/.env`**，改完重啟後端容器 |

> ⚠️ **雲端那台沒設的話，前端只會顯示灰色占位框，畫面上不會有任何錯誤訊息** —— 很難看出
> 是設定沒填。**demo 前務必確認。**

值一律填**當天實際跑 MediaMTX 那台電腦的區網 IP**，不是雲端 VM 自己的 IP。

## 三、看畫面

**從前端網站看**（登入後首頁的四宮格）。前端會自動跟後端換權杖再連 MediaMTX。

> ⚠️ 直接開 `http://<你的IP>:8889/cam_in`（MediaMTX 內建的播放頁）**現在會回 401**。
> B 階段起開啟了身分驗證，沒有權杖就是看不到。**這是刻意的，不是壞掉。**

只想確認「MediaMTX 到底有沒有收到畫面」的話，看 log 有沒有 `stream is available and online`。

## 四、沒有攝影機時，用影片頂替

用 ffmpeg 推一支 mp4 進去當假攝影機。

**前提**：`mediamtx.yml` 裡該頻道要設成 `source: publisher`。
設成 `rtsp://`（主動去拉攝影機）的話，是推不進去的。

```powershell
ffmpeg -nostdin -re -stream_loop -1 -i ..\frontend\public\videos\fall-demo.mp4 `
    -an -c:v copy -rtsp_transport tcp -f rtsp rtsp://localhost:8554/cam_in
```

參數在做什麼：

| 參數 | 作用 |
|---|---|
| `-re` | 用**真實速度**播。不加的話會用最快速度衝完 |
| `-stream_loop -1` | 無限循環 |
| `-an` | 不要聲音（少一條軌就少一種相容性問題）|
| `-c:v copy` | 不轉碼。來源已經是 H.264 時 CPU 幾乎零負擔 |
| `-rtsp_transport tcp` | 走 TCP，避免 UDP 掉包造成畫面破格 |

來源不是 H.264 的話，把 `-c:v copy` 換成
`-c:v libx264 -preset ultrafast -tune zerolatency -g 30`。

> 原本這裡有兩支 `.ps1` 腳本做這件事，已於 2026-07-29 刪除，要用就照上面的指令重寫。

---

# Linux / WSL2 的跑法（2026-07-28 實測）

## ⚠️ WSL2 一定要把 MediaMTX 跑在 Docker 裡

**踩過的坑**：在 WSL2 裡直接跑 `./mediamtx`，**WSL2 內部測起來全部正常**
（`curl` 打得到、串流讀得到），但 **Windows 上的瀏覽器完全連不到 8889**，
前端只會一直轉圈。

原因是埠的轉發機制不同：

| 服務跑在哪 | Windows 的瀏覽器連得到嗎 |
|---|---|
| Docker 容器（前端 :80、後端 :8000）| ✅ Docker Desktop 直接發佈到 Windows |
| WSL2 原生行程 | ❌ 靠 WSL2 自己的 localhost 轉發，實測沒生效 |

> ⚠️ **所以驗證時不能只從 WSL2 內部 `curl`** —— 那會全部顯示正常，但瀏覽器還是打不開。

正確做法：

```bash
docker run -d --name nh-mediamtx --restart unless-stopped \
  -p 8554:8554 -p 8889:8889 -p 8189:8189/udp -p 9997:9997 \
  -v $PWD/streaming/mediamtx.yml:/mediamtx.yml:ro \
  bluenviron/mediamtx:latest
```

> ⚠️ **`8189/udp` 一定要發佈**。那是 WebRTC 傳影像用的，
> 沒發佈的話會「協商成功但收不到影像」—— 看起來像連上了，就是沒畫面。

## 查頻道狀態要用控制 API，不要用猜的

先在 `mediamtx.yml` 加上：

```yaml
api: yes
apiAddress: :9997
authInternalUsers:            # 預設的內建使用者沒有 api 權限，不加會回 authentication error
  - user: any
    permissions:
      - {action: publish}
      - {action: read}
      - {action: playback}
      - {action: api}
```

然後查：

```bash
curl -s http://127.0.0.1:9997/v3/paths/list | python3 -m json.tool
```

看每個頻道的 `ready` 欄位。

> ⚠️ **不要用 WHEP 端點的 HTTP 狀態碼來判斷有沒有畫面** —— 那只是 CORS preflight，
> 不管有沒有人在推流都回 204，**會把所有頻道都誤判成「有畫面」**。

## 沒有攝影機時用影片頂著（Linux／WSL2 版）

```bash
ffmpeg -re -stream_loop -1 -i frontend/public/videos/fall-demo.mp4 \
  -an -c:v libx264 -preset ultrafast -tune zerolatency -g 48 \
  -f rtsp -rtsp_transport tcp rtsp://127.0.0.1:8554/cam_in
```

## 找攝影機的 IP

```bash
python3 - <<'PY'
import socket, concurrent.futures as cf
def probe(ip):
    s=socket.socket(); s.settimeout(1.5)
    try: s.connect((ip,554)); return ip
    except Exception: return None
    finally: s.close()
ips=[f"192.168.0.{i}" for i in range(1,255)]          # 換成你的網段
with cf.ThreadPoolExecutor(max_workers=128) as ex:
    print([r for r in ex.map(probe, ips) if r])
PY
```

> ⚠️ **掃不到 554 埠不代表攝影機不在。** Tapo 要先在 App 裡建立攝影機帳號才會開 RTSP。
> 沒開帳號時它只有 `8800`（TP-Link 專有協定）與 `443` 開著。
> MAC 位址前綴 `60-a4-b7` 就是 TP-Link 的機器。

## 接 Tapo C210（2026-07-28 實測通過）

先照前面「Tapo C210 的 RTSP 帳密要另外設」建立攝影機帳號，
再把 `cam_in` 從「等別人推進來」改成「主動去拉」：

```yaml
cam_in:
  source: rtsp://<攝影機帳號>:<密碼>@<攝影機IP>:554/stream2
  rtspTransport: tcp        # 一定要加，UDP 會破格
  sourceOnDemand: no
```

`docker restart nh-mediamtx` 之後，**log 出現這兩行才算成功**：

```
[path cam_in] [RTSP source] started
[path cam_in] stream is available and online, 2 tracks (H264, G711)
```

**AI 端不用重啟** —— 它對 `cam_in` 是無限重連，攝影機一上線就會自己接上。

## ⚠️ 換攝影機、換位置、換解析度之後要重啟 AI

AI 端的 `normal_h_reference`（防線 B 用的參考身高）**只在程式啟動時校正一次**，之後不會更新。

換了來源卻不重啟的話，會拿舊的參考值去判斷，
**症狀是畫面永遠紅燈，而且看不出原因**。

細節與修法方向見 [`../docs/NEXT_STAGE.md`](../docs/NEXT_STAGE.md) 的 9-3。

## ⚠️ 攝影機不要陡角俯視

實測發現：架高、陡角往下拍時，**站著的人在影像上的軀幹會被壓縮成接近水平**
（髖部投影得比肩膀還高），跟臥倒的幾何特徵完全一樣，防線 A 會持續誤報。

**建議架法：牆面約 2 公尺高、微微下傾。**

詳細數據見 [`../docs/CHANGELOG-STAGES.md`](../docs/CHANGELOG-STAGES.md) 第 9 項缺陷四。

---

# 手機當鏡頭（2026-07-28 三支手機實測通過）

用 **Larix Broadcaster**（iOS / Android 都有，免費）。三支手機各設一條連線：

| 手機 | 推流位址 | 對應前端格子 |
| --- | --- | --- |
| 第一支 | `rtsp://<電腦IP>:8554/phone_a` | 第 2 格 |
| 第二支 | `rtsp://<電腦IP>:8554/phone_b` | 第 3 格 |
| 第三支 | `rtsp://<電腦IP>:8554/phone_c` | 第 4 格 |

設定步驟：

1. 齒輪 ⚙ → **Connections** → **New connection**
2. `Name` 隨意、`URL` 填上表的位址
3. 存檔後回連線清單，**確認該連線前面的勾勾是打開的**
4. 設定 → **Video** → Codec 選 **H.264**
5. 回主畫面按紅色圓鈕開始推流

**踩過的坑**：

| 症狀 | 原因 |
|---|---|
| 按了推流**毫無反應** | **連線沒打勾**。Larix 可以存很多組連線，沒勾的不會用。**這是最常卡住的地方** |
| 前端顯示「連線失敗」 | Codec 選成 **HEVC／H.265**。MediaMTX 收得到，但瀏覽器播不出來 |
| 完全連不上 | 手機連到行動網路了。必須連**同一個 Wi-Fi** |

**不適用的 App**：Iriun Webcam、DroidCam 這類「把手機變成電腦視訊鏡頭」的工具。
它們是把畫面送進電腦的虛擬鏡頭裝置，**沒有「推到指定伺服器」的功能**，餵不進 MediaMTX。

挑 App 的關鍵字是 **RTSP push** 或「推流」，設定裡要有讓你填伺服器網址的欄位。

> 不要用手機瀏覽器的 `/publish` 頁面 —— 那需要 HTTPS 與自簽憑證（每支手機都要安裝並信任），
> A 階段刻意不做。

---

# 防火牆

**多數情況下什麼都不用做。** Windows 在你第一次啟動 `mediamtx.exe` 時會跳出詢問視窗，
按了允許之後，它會自動建立「**這支程式的所有埠號、TCP＋UDP 全部放行**」的規則，
8889 / 8189 / 8554 一次涵蓋（2026-07-28 於本專案實測確認）。

檢查現況：

```powershell
Get-NetFirewallRule | Where-Object { $_.DisplayName -like "*mediamtx*" } |
  ForEach-Object { "$($_.DisplayName) [$($_.Profile)] $($_.Action) -> $(($_ | Get-NetFirewallApplicationFilter).Program)" }
```

看到指向**你這份** `mediamtx.exe` 的 `Allow` 規則就沒問題。

### ⚠️ 規則的 Profile 要對得上目前的網路類型

```powershell
Get-NetConnectionProfile | Select-Object Name, NetworkCategory
```

`NetworkCategory` 是 `Public` 的話，**只在 `Private` 生效的規則等於沒有**。
自動建立的規則會對應你當下所在的網路，所以通常會對；手動加規則時才要留意這點。

### 真的要手動開，三個埠都要

| 協定 | 埠 | 用途 |
| --- | ---: | --- |
| TCP | 8889 | WHEP 報到 |
| UDP | 8189 | WebRTC 影像流動 |
| TCP | 8554 | RTSP 推流（手機、ffmpeg 推進來用）|

```powershell
New-NetFirewallRule -DisplayName "MediaMTX WHEP 8889" -Direction Inbound -Protocol TCP -LocalPort 8889 -Action Allow
New-NetFirewallRule -DisplayName "MediaMTX ICE 8189" -Direction Inbound -Protocol UDP -LocalPort 8189 -Action Allow
New-NetFirewallRule -DisplayName "MediaMTX RTSP 8554" -Direction Inbound -Protocol TCP -LocalPort 8554 -Action Allow
```

### ⚠️ 加了 Allow 規則還是不通，而且 log 連一筆請求都沒有？

（來源：傑雅實測筆記）

**Windows Defender 會「自動」為 `mediamtx.exe` 建立兩條「封鎖」規則，
而封鎖規則的優先權高於允許規則。**

解法：到「具進階安全性的 Windows Defender 防火牆 → 輸入規則」，
找到名稱含 MediaMTX、動作為「封鎖」的那兩條，**停用它們**（建議停用，不要刪除）。

另外，手機第一次連線時 Chrome 會問「允許尋找區域網路上的裝置」，**必須按允許**。

### 電腦上裝了 VMware / VirtualBox / WSL 的話

那些虛擬網卡也有自己的 IP（`192.168.224.1`、`172.27.x.x` 之類）。
設定 `webrtcIPsFromInterfaces: yes` 會把**所有網卡的位址都報給瀏覽器**，
瀏覽器可能先去試虛擬網卡那條，繞一圈才連上真正的 Wi-Fi。

多半還是會通，只是比較慢。真的連不上時，在 `mediamtx.yml` 限定只用 Wi-Fi 那張網卡：

```yaml
webrtcIPsFromInterfacesList: [Wi-Fi]   # 名稱用 Get-NetIPAddress 查 InterfaceAlias
```

---

# 症狀 → 原因對照表

| 現象 | 原因 |
| --- | --- |
| `ERR listen udp :8000: bind: Only one usage of each socket address` | **已經有另一個 MediaMTX 在跑**，兩個搶同一組埠。工作管理員關掉 `mediamtx` 再啟動（`Get-Process mediamtx` 查得到是哪一個）|
| 腳本報 `The string is missing the terminator` | `.ps1` 存成 UTF-8 但**沒有 BOM**。Windows PowerShell 5.1 會用 Big5 讀，中文變亂碼導致語法錯誤。用 VS Code 右下角編碼選 **UTF-8 with BOM** 重存 |
| 腳本說「找不到 ffmpeg」但明明裝好了 | 終端機是**安裝前**開的，環境變數還是舊的。**開一個新的終端機** |
| `RTP packets are too big (1460 > 1440), remuxing them` | **警告而非錯誤**，MediaMTX 會自己處理，可以忽略 |
| log 沒有 `stream is available and online` | 攝影機帳密或 IP 錯；或攝影機沒開 RTSP 帳號 |
| 攝影機與電腦互相看不到 | 攝影機在 2.4G、電腦在 5G，路由器把兩個網段隔開了 |
| 畫面一直停在「連線中」 | 該頻道沒有來源（MediaMTX log 沒有 `is available`）|
| WHEP 回 **404** | 頻道名打錯，或該頻道目前沒有來源 |
| WHEP 回 **201 但沒畫面** | **UDP 8189 被擋** |
| Console 出現 mixed content | 前端是 https 而 MediaMTX 是 http，**必須兩邊一致** |
| 手機按了推流但 log 沒反應 | Larix 的連線沒打勾；或手機不在同一個 Wi-Fi |
| 前端某格「連線失敗」但其他格正常 | 該頻道沒有來源（手機沒推、ffmpeg 沒跑），**不是前端問題** |

---

# ⚠️ 改 `mediamtx.yml` 會中斷所有串流

MediaMTX 偵測到設定檔變動會自動重載（log 出現 `reloading configuration (file changed)`），
**重載時所有連線都會被砍掉重建**：

| 誰 | 會怎樣 |
|---|---|
| 攝影機 | 斷線後自行重連（幾秒）|
| ffmpeg 推的假畫面 | **直接結束，要手動重跑** |
| 手機 | 要重新按推流 |

**demo 進行中絕對不要改這個檔案。** 要加新頻道請在開場前一次改完。

另外：**沒有列在 `paths:` 底下的頻道，MediaMTX 會直接拒收。**
新增鏡頭時，`mediamtx.yml` 與資料庫的頻道名要一起加，只加資料庫會推不進來。

---

# 電腦重開機後要重跑的東西

```powershell
# 1. 後端（一定要先起，MediaMTX 要問它）
cd backend; uv run uvicorn main:app --reload

# 2. MediaMTX（cam_in 會自動去連攝影機）
cd streaming; .\mediamtx.exe .\mediamtx.yml

# 3. 手機三支重新按推流
```

兩個會變動的 IP，變了要改設定：

| 什麼變了 | 要改哪裡 |
|---|---|
| 攝影機的 IP（**換 Wi-Fi 就會變**）| `mediamtx.yml` |
| 電腦自己的 IP | 後端 `.env` 的 `MEDIAMTX_BASE_URL` |

---

# 安全性（B 階段起已有身分驗證）

2026-07-29 起 `mediamtx.yml` 開啟了 `authMethod: http`：
**每一個觀看請求，MediaMTX 都會回頭打後端的 `POST /streams/auth` 問「這個人能不能看」。**
光有網址是看不到畫面的。

| 誰 | 憑什麼進來 | 沒有的話 |
| --- | --- | --- |
| 瀏覽器 | 先跟後端換 60 秒的短命權杖，帶 `Authorization: Bearer` 打 WHEP | 401 |
| AI 端（RTSP 讀 `cam_in`）| **不需要憑證**，直接 `rtsp://<host>:8554/cam_in` | — |
| 推流端（手機 Larix）| **不需要憑證**（`authHTTPExclude` 放行）| — |

### 為什麼只鎖瀏覽器那條路

RTSP 讀取是**刻意放行**的：AI 端拿不到瀏覽器才有的短命權杖，
若另設一組固定帳密，代價是每個讀取端都要改網址、多一個協調與出錯的環節。

> ⚠️ **這個決定的前提是攝影機／MediaMTX／AI 主機同屬「受控內網」。**
> 在共用 Wi-Fi 上這個前提並不成立 —— 同網段的人用 VLC 開
> `rtsp://<host>:8554/cam_in` 就看得到畫面。
> 正式環境應該把它們切到獨立網段。

想鎖回去的話：`.env` 加一組帳密，`backend/streams/router.py` 的 RTSP 分支改成比對
`body.user` / `body.password`，並把所有讀取端的網址改成
`rtsp://<帳號>:<密碼>@<host>:8554/<頻道>`。

設計規格記錄於後端的內部設計文件。

### 啟動順序：後端一定要先起

MediaMTX 每次有人要看都得問後端。**後端沒起來，所有觀看都會失敗（畫面全黑）。**

```
1. 後端      cd backend; uv run uvicorn main:app --reload
2. MediaMTX  .\mediamtx.exe .\mediamtx.yml
3. 推流端    攝影機 / 手機 Larix（可有可無，跟驗證無關）
4. 前端      cd frontend; npm run dev
```

### RTSP 端不用改任何東西

讀 `cam_in` 不需要憑證，網址照舊：

```
rtsp://<host>:8554/cam_in
```

**AI 端不必因為開了驗證而修改任何東西。**

### 退路：demo 現場怎麼把驗證關掉

把 `mediamtx.yml` 的 `authMethod` / `authHTTPAddress` / `authHTTPExclude`
整段每行開頭加 `#` 註解掉，存檔即熱重載生效（約 30 秒，含所有連線重連）。
驗完把 `#` 拿掉就恢復。

> ⚠️ **這條退路只對「MediaMTX 問不到後端」有效**（位址打錯、防火牆擋住、雲端位址填錯字），
> **對「後端整個掛掉」無效** —— 前端連換票那一步都會失敗。
> 不過後端掛掉時整個系統（登入、事件、鏡頭清單）本來就全死，不只串流。

### 2026-07-29 真機實測結果

真 Tapo C210 + 本機後端，全部驗過：

| 驗收項目 | 結果 |
| --- | --- |
| 開啟驗證後 MediaMTX 仍拉得到攝影機 | ✅ `source: rtsp://…` 是 MediaMTX 主動外連，不受此機制管轄 |
| 瀏覽器登入後四宮格有畫面 | ✅ 後端記錄 4 筆 `token 200` + 4 筆 `auth 204` |
| 不帶權杖開內建播放頁 / WHEP | ✅ 401 |
| RTSP 讀取不帶任何憑證（等同 AI 端）| ✅ 放行（後端回 204；無來源的頻道回 404 而非 401，即證明驗證已通過）|
| 關掉驗證後恢復可看 | ✅ 401 → 200 |

### 還做不到的事

**權杖只在建立連線那一刻驗一次，之後 MediaMTX 不會再問。**

所以權杖過期、使用者登出、帳號被停用，**都不會中斷已經在播的畫面**。
擋的是「新連線」，不是「踢掉正在看的人」。
要真的中斷，只能關瀏覽器分頁或重啟 MediaMTX。

另外，換票與 WHEP 協商走的是 http 明文，**同網段抓封包可以撿到那 60 秒的權杖**。
（WebRTC 的影像本身是加密的，不受影響。）根治要整套上 HTTPS，屬後續階段。
