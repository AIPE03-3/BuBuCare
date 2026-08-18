#!/usr/bin/env bash
set -euo pipefail

# 2026-08-10 早於中午的案件是修正時區前以 UTC 寫入、被前端誤認為
# 台北時間的測試資料；正確案件從當日下午 16:xx 起算。
CUTOFF="${1:-2026-08-10 12:00:00}"

echo "清理來源：PostgreSQL 容器 nh-postgres / database aipe03"
echo "事件主表：detect_events"
echo "相依通報表：detect_event_reports"
echo "截止時間：$CUTOFF"

echo "--- 清理前符合條件的案件 ---"
docker exec nh-postgres psql -v ON_ERROR_STOP=1 -U aipe -d aipe03 \
  -c "SELECT event_id, device_id, detected_at, status FROM detect_events WHERE detected_at < TIMESTAMP '$CUTOFF' ORDER BY detected_at;"

echo "--- 執行交易 ---"
docker exec nh-postgres psql -v ON_ERROR_STOP=1 -U aipe -d aipe03 \
  -c "BEGIN; DELETE FROM detect_event_reports WHERE event_id IN (SELECT event_id FROM detect_events WHERE detected_at < TIMESTAMP '$CUTOFF'); DELETE FROM detect_events WHERE detected_at < TIMESTAMP '$CUTOFF'; COMMIT;"

echo "--- 清理後保留案件 ---"
docker exec nh-postgres psql -v ON_ERROR_STOP=1 -U aipe -d aipe03 \
  -c "SELECT event_id, device_id, detected_at, status FROM detect_events ORDER BY detected_at;"
