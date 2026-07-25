#!/bin/sh
# 一個容器內同時跑兩支程式（合併方案 B）
# 1) 背景啟動 Kafka 收件人（結尾的 & 代表丟到背景去跑）
uv run python -m kafka_consumer &
# 2) 前景啟動網站（前景這支活著，容器就活著）
uv run python -m uvicorn main:app --host 0.0.0.0 --port 8000
