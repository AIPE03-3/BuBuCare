FROM python:3.12-slim

# 借用 uv 官方現成執行檔，裝進這包
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# 先複製套件清單，把依賴裝好（分兩段是快取技巧：沒改清單就不重裝套件）
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# 再複製後端原始碼（core/、events/… 與 global-bundle.pem 憑證）
COPY . .

EXPOSE 8000

# 啟動腳本：背景跑 consumer + 前景跑 uvicorn（見 start.sh）
CMD ["sh", "start.sh"]
