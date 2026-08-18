#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  echo "[錯誤] 找不到 $ROOT_DIR/.env" >&2
  exit 1
fi

env_value() {
  local key="$1"
  sed -n "s/^${key}=//p" .env | tail -n 1 | tr -d '\r'
}

DB_USER_VALUE="$(env_value DB_USER)"
DB_PASSWORD_VALUE="$(env_value DB_PASSWORD)"
DB_HOST_VALUE="$(env_value DB_HOST)"
DB_PORT_VALUE="$(env_value DB_PORT)"
DB_NAME_VALUE="$(env_value DB_NAME)"
DB_SSLMODE_VALUE="$(env_value DB_SSLMODE)"

for key in DB_USER_VALUE DB_PASSWORD_VALUE DB_HOST_VALUE DB_PORT_VALUE DB_NAME_VALUE; do
  if [[ -z "${!key}" ]]; then
    echo "[錯誤] .env 的 ${key%_VALUE} 未設定" >&2
    exit 1
  fi
done

if [[ "$DB_SSLMODE_VALUE" != "disable" ]]; then
  echo "[錯誤] 本地 PostgreSQL 的 DB_SSLMODE 必須是 disable" >&2
  exit 1
fi

if ! docker inspect nh-postgres >/dev/null 2>&1; then
  echo "[錯誤] 找不到 nh-postgres 容器" >&2
  exit 1
fi

docker start nh-postgres >/dev/null

echo "[1/5] 等待 PostgreSQL..."
for _ in $(seq 1 30); do
  if docker exec nh-postgres pg_isready -U "$DB_USER_VALUE" -d "$DB_NAME_VALUE" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! docker exec nh-postgres pg_isready -U "$DB_USER_VALUE" -d "$DB_NAME_VALUE" >/dev/null 2>&1; then
  echo "[錯誤] PostgreSQL 未就緒" >&2
  exit 1
fi

echo "[2/5] 驗證資料庫帳號與密碼..."
if ! docker exec -e PGPASSWORD="$DB_PASSWORD_VALUE" nh-postgres \
  psql -h 127.0.0.1 -U "$DB_USER_VALUE" -d "$DB_NAME_VALUE" \
  -tAc 'SELECT 1' | grep -qx '1'; then
  echo "[錯誤] DB_USER、DB_PASSWORD 或 DB_NAME 與 nh-postgres 不一致" >&2
  exit 1
fi

echo "[3/5] 重建並啟動完整 Compose（含 frontend/backend）..."
docker compose up -d --build

echo "[4/5] 建立資料表與初始帳號..."
# backend 的 restart policy 不影響一次性 run；即使常駐 backend 尚未 ready，
# 初始化錯誤也會直接顯示在目前終端。
docker compose run --rm backend uv run --no-sync python -m init_db

echo "[5/5] 等待 API 並測試 A001 登入..."
for _ in $(seq 1 30); do
  status="$(curl -sS -o /tmp/nh-login-response.json -w '%{http_code}' \
    -X POST http://127.0.0.1:8000/login \
    -H 'Content-Type: application/x-www-form-urlencoded' \
    --data 'username=A001&password=123456' 2>/dev/null || true)"
  if [[ "$status" == "200" ]]; then
    echo "[完成] 資料庫初始化成功，A001 / 123456 登入測試通過"
    exit 0
  fi
  sleep 1
done

echo "[錯誤] 初始化完成，但登入 API 未回傳 200" >&2
docker compose ps backend >&2 || true
docker compose logs --tail 100 backend >&2 || true
exit 1
