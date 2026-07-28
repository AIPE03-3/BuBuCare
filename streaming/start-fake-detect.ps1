# 假的「AI 偵測畫面」：從 cam_in 拉畫面 → 畫一個固定紅框 → 推到 cam_out。
#
# 為什麼需要這支：
#   cam_out 的正式來源是 albert 的推論程式（讀 cam_in → 畫框 → 推回 cam_out），
#   但該推流功能尚未實作（目前畫完框只有 cv2.imshow 本機顯示）。
#   前端的「即時／偵測」切換鈕需要兩邊都有畫面才驗證得了，所以先用固定框頂著。
#   紅框位置固定、與畫面內容無關 —— 它只證明「切換鈕有生效」，不證明任何 AI 能力。
#
# albert 的推流做好之後，把這支關掉、換他推上來即可，
# 前端、後端、資料庫都不用改（換的是 MediaMTX 上游）。
#
# 用法（MediaMTX 要先啟動，且 cam_in 要已經有畫面）：
#   .\start-fake-detect.ps1
param(
    [string]$MediaMtxHost = "localhost",
    [string]$SourceChannel = "cam_in",
    [string]$TargetChannel = "cam_out"
)

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Error "找不到 ffmpeg，請先安裝：winget install Gyan.FFmpeg"
    exit 1
}

$source = "rtsp://${MediaMtxHost}:8554/${SourceChannel}"
$target = "rtsp://${MediaMtxHost}:8554/${TargetChannel}"

# drawbox：在畫面正中間畫一個佔一半大小的紅框，t=6 是線寬
# 畫框一定要重新編碼（不能 -c:v copy），所以帶上低延遲參數壓住延遲
$filter = "drawbox=x=iw/4:y=ih/4:w=iw/2:h=ih/2:color=red@0.9:t=6"

Write-Host "假偵測畫面：$source --[紅框]--> $target（Ctrl+C 停止）"
ffmpeg -nostdin -rtsp_transport tcp -i $source `
    -vf $filter -an `
    -c:v libx264 -preset ultrafast -tune zerolatency -g 30 `
    -rtsp_transport tcp -f rtsp $target
