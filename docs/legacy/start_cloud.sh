#!/bin/bash

# =========================================================================
# ☁️ 後勤雲端 MLOps 啟動腳本 (Cloud MLOps Startup Script)
# 職責：開啟 Docker 容器、接收標註資料、自動觸發模型重訓
# 提示：需要幫 AI 補習重訓時才需要開啟此腳本。
# =========================================================================

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$BASE_DIR"

echo "======================================================="
echo "☁️ [Cloud 後勤] 正在啟動 MLOps 煉丹爐與標註伺服器..."
echo "======================================================="

# 1. 啟動基礎設施 Docker (ClearML, Label Studio, Kafka)
echo "🐳 [1/2] 啟動 Docker 容器 (ClearML, Label Studio, Kafka)..."
docker-compose up -d
sleep 5

# 2. 啟動 Python MLOps 腳本
echo "🔄 [2/2] 啟動 Watchdog 標註巡邏員、Webhook 監聽器與 ClearML Agent..."

PROJECT_PATH="$BASE_DIR/Fall"
TOOLS_PATH="$PROJECT_PATH/tools"

# 確保環境變數對齊
if [ -f "$TOOLS_PATH/.env" ]; then
    export $(grep -v '^#' "$TOOLS_PATH/.env" | xargs)
fi

pkill -f watchdog.py
pkill -f webhook_receiver.py
pkill -f "clearml-agent"
kill -9 $(lsof -t -i:9001) 2>/dev/null

nohup "$PROJECT_PATH/.venv/bin/python" "$TOOLS_PATH/webhook_receiver.py" > "$PROJECT_PATH/webhook.log" 2>&1 &
nohup "$PROJECT_PATH/.venv/bin/python" "$TOOLS_PATH/watchdog.py" > "$PROJECT_PATH/watchdog.log" 2>&1 &
nohup bash -c "PATH=\"$PROJECT_PATH/.venv/bin:\$PATH\" clearml-agent daemon --queue default --foreground" > "$PROJECT_PATH/agent.log" 2>&1 &

echo "======================================================="
echo "✅ [Cloud 後勤] MLOps 伺服器已全面啟動！"
echo "🌐 Label Studio 標註網頁: http://localhost:8080"
echo "🌐 ClearML 模型戰情室: http://localhost:8080 (ClearML 預設埠)"
echo "💡 提示：按 [Ctrl + C] 隨時關閉並清理後端資源。"
echo "======================================================="

# 攔截 Ctrl+C 自動清理
cleanup() {
    echo -e "\n🛑 偵測到中斷訊號 (Ctrl+C)，正在關閉後勤 MLOps 伺服器..."
    docker-compose down
    pkill -f watchdog.py
    pkill -f webhook_receiver.py
    pkill -f "clearml-agent"
    echo "✅ 後勤系統已安全關閉！"
    exit 0
}
trap cleanup SIGINT SIGTERM

# 保持腳本運行，直到使用者按下 Ctrl+C
while true; do
    sleep 3600
done
