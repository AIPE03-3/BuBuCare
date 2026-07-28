# 串流環境（MediaMTX）

影像走 `攝影機/手機 → MediaMTX → 瀏覽器`，**完全不經過後端**。
後端只負責告訴前端「MediaMTX 在哪、要看哪個頻道」。

## 頻道

| 頻道 | 內容 | 誰推進來 |
| --- | --- | --- |
| `cam_in` | 原始畫面 | Tapo 攝影機（MediaMTX 主動拉），或 `start-fake-camera.ps1` 推 mp4 |
| `cam_out` | 畫框後 | 正式來源是 albert 的推論程式（**尚未實作**）；A 階段用 `start-fake-detect.ps1` 頂著 |
| `phone_a` / `phone_b` / `phone_c` | 手機畫面 | 手機推流 App |

（傑雅版原本叫 `my_camera_tapo`，語意等同 `cam_in`。）

## 準備

1. 下載 MediaMTX Windows 版（<https://github.com/bluenviron/mediamtx/releases>，
   選 `mediamtx_vX.X.X_windows_amd64.zip`），解壓到本資料夾。
   **`mediamtx.exe` 不進 git。**
2. `Copy-Item mediamtx.yml.example mediamtx.yml`
3. 編輯 `mediamtx.yml` 的 `cam_in`，填入攝影機帳密與 IP。**這個檔案含帳密，不進 git。**
4. ffmpeg 只有在需要假畫面時才用得到（`cam_out` 或沒有攝影機時）：
   `winget install Gyan.FFmpeg`，裝完要**開新的終端機**才吃得到 PATH。

### Tapo C210 的 RTSP 帳密

**不是** TP-Link 的登入帳號。要另外設：

```
Tapo App → 選這台攝影機 → 右上角齒輪 → 進階設定 → 攝影機帳號
```

沒設這一步，RTSP 會直接被拒絕連線，而且錯誤訊息看起來像網路問題。

路徑：`stream1` = 1080p、`stream2` = 360p。先用 `stream2`，比較不吃頻寬。

## 啟動

```powershell
.\mediamtx.exe .\mediamtx.yml
```

log 出現 `[WebRTC] listener opened on :8889` 就是起來了。
接真攝影機時還會看到 `[RTSP source] ready`，沒有這行代表攝影機連不上（多半是帳密或 IP 錯）。

查自己的區網 IP：

```powershell
Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -like '192.168.*' } |
  Select-Object InterfaceAlias, IPAddress
```

### 找攝影機的 IP（換 Wi-Fi 就會變，不是固定的）

Tapo App 的裝置資訊裡看得到。查不到的話從電腦掃——RTSP 用 554 埠，開著的那台就是攝影機：

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

把 IP 填進**後端** `.env`：`MEDIAMTX_BASE_URL=http://<你的IP>:8889`，重啟後端。
（前端不用重新 build——網址是後端在回應時才組出來的。）

### ⚠ 「後端」是指前端實際連的那一台

WHEP 網址由**回應請求的那台後端**組出來，所以要設在哪，看前端連誰：

| 情境 | 要設 `MEDIAMTX_BASE_URL` 的地方 |
| --- | --- |
| 本機開發（前端連 localhost:8000） | 你自己的 `.env` |
| 用雲端網站看（`http://35.221.135.197`） | **雲端 VM 上 `/var/project/.env`**，改完重啟後端容器 |

雲端那台沒設的話，`stream_url` 會回 `null`，前端只會顯示灰色占位框——
**畫面不會有錯誤訊息，很難看出是設定沒填**。demo 前務必確認。

值一律填**當天實際跑 MediaMTX 那台電腦的區網 IP**，不是雲端 VM 自己的 IP。

## 看畫面

瀏覽器開 `http://<你的IP>:8889/cam_in`，MediaMTX 內建的播放頁會直接放。

## 假的偵測畫面（cam_out）

```powershell
.\start-fake-detect.ps1
```

從 `cam_in` 拉畫面、畫一個固定紅框、推到 `cam_out`。
**紅框位置固定，與畫面內容無關**——它只證明前端切換鈕有生效，不證明任何 AI 能力。

albert 的推流做好之後把這支關掉即可，前後端與資料庫都不用改。

## 沒有攝影機時

`mediamtx.yml` 的 `cam_in` 改成 `source: publisher`，然後：

```powershell
.\start-fake-camera.ps1 -Video ..\frontend\public\videos\fall-demo.mp4 -Channel cam_in
```

影片不是 H.264 的話加 `-Transcode`（會吃 CPU）。

## 手機當鏡頭（2026-07-28 三支手機實測通過）

用 **Larix Broadcaster**（iOS / Android 皆有，免費）。三支手機各自設定一條連線：

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

踩過的坑：

- **連線沒打勾** → 按了推流毫無反應。Larix 可存多組連線，沒勾的不會用。這是最常卡住的地方
- **Codec 選成 HEVC／H.265** → MediaMTX 收得到、瀏覽器播不出來，症狀是前端「連線失敗」
- 手機必須連**同一個 Wi-Fi**，不是行動網路

**不適用的 App**：Iriun Webcam、DroidCam 這類「把手機變成電腦的視訊鏡頭」的工具。
它們把畫面送進電腦的虛擬鏡頭裝置，沒有「推到指定伺服器」的功能，餵不進 MediaMTX。
挑 App 的關鍵字是 **RTSP push** 或「推流」，設定裡要有讓你填伺服器網址的欄位。

> 不要用手機瀏覽器的 `/publish` 頁面——那需要 HTTPS 與自簽憑證（每支手機都要安裝並信任），
> A 階段刻意不做。

## 防火牆

**多數情況下什麼都不用做。** Windows 在你第一次啟動 `mediamtx.exe` 時會跳出詢問視窗，
按了允許之後它會自動建立「**這支程式的所有埠號、TCP＋UDP 全部放行**」的規則，
8889 / 8189 / 8554 一次涵蓋（2026-07-28 於本專案實測確認）。

檢查現況：

```powershell
Get-NetFirewallRule | Where-Object { $_.DisplayName -like "*mediamtx*" } |
  ForEach-Object { "$($_.DisplayName) [$($_.Profile)] $($_.Action) -> $(($_ | Get-NetFirewallApplicationFilter).Program)" }
```

看到指向**你這份** `mediamtx.exe` 的 `Allow` 規則就沒問題。

**⚠ 規則的 Profile 要對得上目前的網路類型。** 查目前網路：

```powershell
Get-NetConnectionProfile | Select-Object Name, NetworkCategory
```

`NetworkCategory` 是 `Public` 的話，只在 `Private` 生效的規則等於沒有。
自動建立的規則會對應你當下所在的網路，所以通常會對；手動加規則時才要留意這點。

真的要手動開，三個埠都要：

| Protocol | Port | 用途 |
| --- | ---: | --- |
| TCP | 8889 | WHEP 報到 |
| UDP | 8189 | WebRTC 影像流動 |
| TCP | 8554 | RTSP 推流（手機、ffmpeg 推進來用） |

```powershell
New-NetFirewallRule -DisplayName "MediaMTX WHEP 8889" -Direction Inbound -Protocol TCP -LocalPort 8889 -Action Allow
New-NetFirewallRule -DisplayName "MediaMTX ICE 8189" -Direction Inbound -Protocol UDP -LocalPort 8189 -Action Allow
New-NetFirewallRule -DisplayName "MediaMTX RTSP 8554" -Direction Inbound -Protocol TCP -LocalPort 8554 -Action Allow
```

**⚠ 加了 Allow 規則還是不通，而且 MediaMTX 的 log 連一筆請求都沒有？**（來源：傑雅實測筆記）

Windows Defender 會**自動**為 `mediamtx.exe` 建立兩條 **Block** 規則，
而**封鎖規則優先於允許規則**。到「具進階安全性的 Windows Defender 防火牆 → 輸入規則」，
找到名稱含 MediaMTX、動作為「封鎖」的兩條，**停用它們**（建議停用不要刪除）。

另外手機第一次連線時，Chrome 會問「允許尋找區域網路上的裝置」，必須按允許。

### 電腦上裝了 VMware / VirtualBox / WSL 的話

那些虛擬網卡也有 IP（`192.168.224.1`、`172.27.x.x` 之類）。`webrtcIPsFromInterfaces: yes`
會把**所有網卡的位址都報給瀏覽器**，瀏覽器可能先去試虛擬網卡那條，繞一圈才連上真正的 Wi-Fi。

多半還是會通，只是慢。真的連不上時，在 `mediamtx.yml` 限定只用 Wi-Fi 那張網卡：

```yaml
webrtcIPsFromInterfacesList: [Wi-Fi]   # 名稱用 Get-NetIPAddress 查 InterfaceAlias
```

## 常見狀況

| 現象 | 原因 |
| --- | --- |
| `ERR listen udp :8000: bind: Only one usage of each socket address` | **已經有另一個 MediaMTX 在跑**，兩個會搶同一組埠號。工作管理員關掉 `mediamtx` 再啟動（`Get-Process mediamtx` 查得到是哪一個） |
| 腳本報 `The string is missing the terminator` | `.ps1` 存成 UTF-8 但**沒有 BOM**。Windows PowerShell 5.1 會用 Big5 讀，中文變亂碼導致語法錯誤。用 VS Code 右下角編碼選 **UTF-8 with BOM** 重存 |
| 腳本說「找不到 ffmpeg」但明明裝好了 | 終端機是**安裝前**開的，環境變數還是舊的。開一個新的終端機 |
| `RTP packets are too big (1460 > 1440), remuxing them` | 警告而非錯誤，MediaMTX 會自己處理，可忽略 |
| log 沒有 `stream is available and online` | 攝影機帳密或 IP 錯；或攝影機沒開 RTSP 帳號 |
| 攝影機與電腦互相看不到 | 攝影機在 2.4G、電腦在 5G，路由器把兩個網段隔開了 |
| 畫面一直停在「連線中」 | 該頻道沒有來源（MediaMTX log 沒有 `is available`） |
| WHEP 回 404 | 頻道名打錯，或該頻道目前沒有來源 |
| WHEP 回 201 但沒畫面 | UDP 8189 被擋 |
| Console 出現 mixed content | 前端是 https 而 MediaMTX 是 http，必須兩邊一致 |
| 手機按了推流但 log 沒反應 | Larix 的連線沒打勾；或手機不在同一個 Wi-Fi |
| 前端某格「連線失敗」但其他格正常 | 該頻道沒有來源（手機沒推、ffmpeg 沒跑），不是前端問題 |

## ⚠ 改 mediamtx.yml 會中斷所有串流

MediaMTX 偵測到設定檔變動會自動重載（log 出現 `reloading configuration (file changed)`），
**重載時所有連線都會被砍掉重建**：

- 攝影機斷線後自行重連（幾秒）
- `start-fake-detect.ps1` 的 ffmpeg **直接結束**，要手動重跑
- 手機端要重新按推流

**demo 進行中絕對不要改這個檔案。** 要加新頻道請在開場前一次改完。

另外：**沒有列在 `paths:` 底下的頻道，MediaMTX 會直接拒收**。新增鏡頭時
`mediamtx.yml` 與資料庫的頻道名要一起加，只加資料庫會推不進來。

## 電腦重開機後要重跑的東西

```powershell
# 1. MediaMTX（cam_in 會自動去連攝影機）
cd streaming; .\mediamtx.exe .\mediamtx.yml

# 2. 假偵測畫面（另開一個視窗）
.\start-fake-detect.ps1

# 3. 手機三支重新按推流
```

攝影機的 IP **換 Wi-Fi 就會變**，變了要改 `mediamtx.yml`；
電腦自己的 IP 變了要改後端 `.env` 的 `MEDIAMTX_BASE_URL`。

## 安全性

**A 階段沒有任何驗證**：同一個 Wi-Fi 上任何人只要知道網址就看得到住民畫面。
僅適用於開發與受控的 demo 場地，上正式環境前必須補上串流驗證（排在 A 階段之後緊接著做）。
