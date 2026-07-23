# MediaMTX 區域網路串流設定與問題排查筆記

## 環境

-   Windows
-   MediaMTX v1.19.2
-   Tapo RTSP
-   WebRTC: 8889
-   HTTP測試伺服器: 8000

## 1. MediaMTX 設定

確認 mediamtx.yml：

``` yaml
paths:
  my_camera_tapo:
    source: rtsp://<帳號>:<密碼>@192.168.1.115:554/stream2
    rtspTransport: tcp

webrtc: true
webrtcAddress: :8889
webrtcAllowOrigins: ["*"]
webrtcIPsFromInterfaces: true
```

啟動後應看到：

    [WebRTC] started with listeners on :8889 (TCP/HTTP), :8189 (UDP/ICE)

## 2. 啟動 HTTP 測試伺服器

``` powershell
cd C:\AIPE_PROJECT\RTSP
py -m http.server 8000 --bind 0.0.0.0
```

也可：

``` powershell
py -m http.server 8000 --bind 0.0.0.0 --directory C:\AIPE_PROJECT\RTSP
```

測試： - http://127.0.0.1:8000/ - http://192.168.1.108:8000/

## 3. 防火牆規則

TCP 8889： - Inbound - TCP - Port 8889 - Allow - Domain/Private/Public

UDP 8189： - Inbound - UDP - Port 8189 - Allow - Domain/Private/Public

## 4. 遇到的問題

-   電腦可開：
    -   http://192.168.1.108:8889/my_camera_tapo/
-   手機無法開。
-   手機可開：
    -   http://192.168.1.108:8000/

MediaMTX 日誌沒有新增任何 HTTP/WebRTC 紀錄。

### 測試

暫時關閉 Windows 防火牆後：

手機立即可觀看 WebRTC。

=\> 問題確定是 Windows 防火牆。

### 真正原因

Windows Defender 自動建立兩條：

-   MediaMTX
-   Action：Block
-   Program：mediamtx.exe

即使 Port Rule 為 Allow，也會被 Block Rule 擋住。

## 解決方式

停用 MediaMTX 的 Block 規則（建議停用，不必刪除）。

保留： - TCP 8889 Allow - UDP 8189 Allow

## 5. Chrome 區域網路權限

手機第一次會詢問：

「允許 Chrome 尋找區域網路上的裝置」

必須按「允許」。

## 6. 手機 IP

iPhone：

設定 → Wi-Fi → 目前 Wi-Fi → ⓘ → IP 位址

可用於限制只有指定手機可連線。

## 7. 最佳做法

-   防火牆保持開啟。
-   停用 MediaMTX Block Rule。
-   保留 TCP 8889、UDP 8189 Allow Rule。
-   若需要，可將 Allow Rule 限制為指定手機 IP。

## Checklist

-   [ ] MediaMTX 啟動
-   [ ] WebRTC 8889 啟動
-   [ ] TCP 8889 Allow
-   [ ] UDP 8189 Allow
-   [ ] MediaMTX Block Rule 停用
-   [ ] Chrome 已允許區域網路
-   [ ] 手機與電腦同 Wi-Fi
-   [ ] 8000 可開
-   [ ] 8889 可觀看
