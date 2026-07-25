#!/bin/sh
# 一個容器內同時跑兩支程式（合併方案 B）

# 0) 先確認 .env 真的掛進來了
# compose 是用 volume 把根目錄的 ./.env 掛進來的。Docker 遇到「來源檔案不存在」不會報錯，
# 而是自動在 host 建一個同名的「資料夾」掛進來，程式因此讀不到任何設定，
# 只會噴一個看不懂的 KeyError: 'SECRET_KEY'。這裡先擋下來，講人話。
if [ ! -f /app/.env ]; then
  echo "[start.sh] 錯誤：找不到 /app/.env" >&2
  echo "[start.sh] 請在專案根目錄放一份 .env（範本見 .env.example），再重跑 docker compose up -d" >&2
  echo "[start.sh] 若根目錄已被 Docker 建出一個名為 .env 的「資料夾」，要先把它刪掉才能放檔案" >&2
  exit 1
fi

# 1) 背景啟動 Kafka 收件人（結尾的 & 代表丟到背景去跑）
# 包一層 while 迴圈的原因：冷啟動時 Kafka 要 10 秒以上才聽得到，但 KafkaConsumer 只等約 2 秒
# 就丟 NoBrokersAvailable 收工。少了這層迴圈，consumer 從此死掉、容器卻因為 uvicorn 還活著而
# 一直顯示 Up——事件收不到但四個容器全綠，是最難查的那種故障。
while true; do
  uv run --no-sync python -m kafka_consumer
  echo "[start.sh] consumer 結束（多半是 Kafka 還沒開機好），5 秒後重啟" >&2
  sleep 5
done &

# 2) 前景啟動網站（前景這支活著，容器就活著）
# --no-sync：套件在 build 階段就裝好了，開機時不要再連 PyPI 同步一次
#            （預設的 uv run 會順手把 pytest 等 dev 套件裝回來，等於每次啟動都要有網路）
# exec：讓 uvicorn 取代 sh 成為 1 號行程，docker compose down 的停止訊號才收得到
#       （否則訊號停在 sh、uvicorn 沒收到，每次關閉都要空等滿 10 秒才被強制砍掉）
exec uv run --no-sync python -m uvicorn main:app --host 0.0.0.0 --port 8000
