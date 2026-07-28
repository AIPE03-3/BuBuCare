# 用一支 mp4 假裝成攝影機，推進 MediaMTX 的指定頻道。
# 給沒有實體攝影機的組員用，也是攝影機不在身邊時的備案。
#
# 用法：
#   .\start-fake-camera.ps1 -Video ..\frontend\public\videos\fall-demo.mp4 -Channel cam_in
#
# 前提：mediamtx.yml 裡該頻道要是 source: publisher（等人推），
#       如果設成 rtsp://（主動拉攝影機），推進去會被拒絕。
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
    [string]$MediaMtxHost = "localhost",
    # 來源不是 H.264 時加這個開關：改成邊播邊轉碼（吃 CPU，但什麼格式都吞得下）
    [switch]$Transcode
)

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Error "找不到 ffmpeg，請先安裝：winget install Gyan.FFmpeg"
    exit 1
}

if (-not (Test-Path $Video)) {
    Write-Error "找不到影片檔：$Video"
    exit 1
}

$target = "rtsp://${MediaMtxHost}:8554/${Channel}"

if ($Transcode) {
    # -tune zerolatency：編碼器不囤積影格
    # -g 30：每秒一張完整影格，決定觀眾接上後多久看得到畫面
    $codecArgs = @("-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-g", "30", "-r", "30")
} else {
    $codecArgs = @("-c:v", "copy")
}

Write-Host "推流中：$Video -> $target（Ctrl+C 停止）"
ffmpeg -nostdin -re -stream_loop -1 -i $Video -an @codecArgs -rtsp_transport tcp -f rtsp $target
