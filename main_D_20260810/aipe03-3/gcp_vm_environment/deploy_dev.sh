#!/usr/bin/env bash
set -Eeuo pipefail

log(){ echo "[$(date '+%F %T')] $*"; }
err(){ echo "[ERROR] $*" >&2; exit 1; }

# ":- 如果前面空,給預設值"
#GIT_NAME="${GIT_NAME:-aipe03-3}"
GIT_NAME=${1:-aipe03-3}

# REPO_DIR="/home/ubuntu/$(basename "${PROJECT_DIR:-project}")"
REPO_DIR="/home/ubuntu/$GIT_NAME" #"/home/ubuntu/apie03-3
DEPLOY_DIR="${PROJECT_DIR:-/var/project}"


FRONTEND_SRC="$REPO_DIR/frontend"
FRONTEND_DST="$DEPLOY_DIR/nginx/html"

BACKEND_SRC="$REPO_DIR/backend"
# /var/project/python/api/backend
BACKEND_DST="$DEPLOY_DIR/python/api/backend"
# /var/project/python/api
BACKEND_ROOT_DST="$(dirname "$BACKEND_DST")" 
#會捨掉最後一個路徑, 如果/xxx/yyy/zzz/ 或/xxx/yyy/zzz 都是/xxx/yyy, 但就是多叫一個sub process

# /project/api
BACKEND_IN_CONTAINER="/project/$(basename "$BACKEND_ROOT_DST")"
#${變數/#舊字串/新字串}

echo "$REPO_DIR"
echo "$BACKEND_ROOT_DST"
echo "$BACKEND_IN_CONTAINER"

PY_CONTAINER="python-app"

log "Updating repository..."
cd "$REPO_DIR"
git fetch origin
git reset --hard origin/main

log "Building frontend..."
cd "$FRONTEND_SRC"
npm ci
npm run build

log "Sync frontend..."
mkdir -p "$FRONTEND_DST"
rsync -rlDc --no-p --chmod=ugo=rwX --delete dist/ "$FRONTEND_DST/"

log "Sync backend..."
mkdir -p "$BACKEND_DST"
rsync -rlDc --no-p --chmod=ugo=rwX --delete \
  --exclude='__pycache__/' \
  --exclude='*.py[cod]' \
  --exclude='.venv/' \
  "$BACKEND_SRC/" "$BACKEND_DST/"

# 260725 in backend/ 
# rsync -rlDc --no-p --chmod=ugo=rwX "$REPO_DIR/pyproject.toml" "$BACKEND_ROOT_DST"
# rsync -rlDc --no-p --chmod=ugo=rwX "$REPO_DIR/uv.lock" "$BACKEND_ROOT_DST"

# -rlDc：只保留遞迴、軟連結、裝置檔案與校驗碼比對。
# --no-p：關鍵！徹底命令 rsync 不要去更動目標目錄與檔案的權限屬性。
# --chmod=ugo=rwX：這是一個安全網。雖然不跟隨來源檔案的權限，但它會自動賦予新搬過去的檔案「所有人皆可讀取（rw）」、
# 資料夾「所有人皆可進入（X）」的預設權限，保證 Nginx 一定讀得到網頁。

log "cd python project..."
cd "$BACKEND_ROOT_DST"
# uv sync

log "Checking container..."
if ! docker ps -a --format '{{.Names}}' | grep -qx "$PY_CONTAINER"; then
    docker compose -f "$DEPLOY_DIR/docker-compose.yml" up -d
fi

STATE=$(docker inspect -f '{{.State.Status}}' "$PY_CONTAINER")
if [ "$STATE" != "running" ]; then
    docker start "$PY_CONTAINER"
fi


CONSUMER="$(docker top "$PY_CONTAINER" 2>/dev/null | grep '[k]afka_consumer' || true)"

if [ -n "$CONSUMER" ]; then
    log "kafka_consumer is already running."
else
    log "kafka_consumer is not running; starting it..."

    docker exec -d -w "$BACKEND_IN_CONTAINER/backend" "$PY_CONTAINER" \
    sh -c '
    while true; do
    #for i in $(seq 1 10); do
        PYTHONDONTWRITEBYTECODE=1 uv run python -m kafka_consumer \
            > /proc/1/fd/1 2> /proc/1/fd/2
        echo "[kafka_consumer] stopped, restart in 5s" >&2
       # echo "[kafka_consumer] stopped (attempt $i/10), restart in 5s" >&2
        sleep 5
    done
    '
fi

CMD="$(docker top "$PY_CONTAINER" 2>/dev/null | grep '[u]vicorn' || true)"

if echo "$CMD" | grep -q "main:app"; then
    log "uvicorn is already running."
else
    if [ -n "$CMD" ]; then
        log "Found an unexpected uvicorn process; restarting container..."
        docker restart "$PY_CONTAINER"
    else
        log "uvicorn is not running; starting it..."
    fi

	# docker exec -d python-app sh -c 'cd /project/api && exec uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload'
	#docker exec -d "$PY_CONTAINER" sh -c \
	#'cd /project/backend && exec uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload'
	# 改寫如下:
    docker exec -d -w "$BACKEND_IN_CONTAINER/backend" "$PY_CONTAINER" \
    sh -c 'PYTHONDONTWRITEBYTECODE=1 exec uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload --reload-exclude ".venv/*"  > /proc/1/fd/1 2> /proc/1/fd/2'
fi
# PYTHONDONTWRITEBYTECODE=1 是 Python 的環境設定，意思是：不要在磁碟上寫入 Python 編譯快取檔(__pycache__/ 這些)
# 單引 的 exec uv run ...（建議保留）：這是 Linux Shell 的內建指令。 
# 它的功能是：讓 uvicorn 進程直接取代（Overwrite）掉前面啟動的 sh 殼層進程。
# 好處：這樣做可以讓 uvicorn 成為該執行緒的 PID 1（主進程）。 
# 未來如果您想停止這個指令，Linux 的系統訊號（如 SIGTERM）才能直接送到 uvicorn，
# 讓網頁伺服器安全、優雅地關閉（Graceful Shutdown），而不會卡死在背景。


# 利用here document 做暫時的註解, : 是一個甚麼都不做的內建指令
: << 'COMMENT'
log "Waiting for health..."
for i in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
        log "Health OK"
        exit 0
    fi
    sleep 1
done

err "Health check failed"
COMMENT
