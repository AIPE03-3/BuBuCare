# backend/observability/router.py
# 監控用的兩個端點：健康檢查與指標輸出。
# 這兩條都不屬於任何業務功能（事件、帳號、裝置），而是「服務本身」的對外窗口。

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter()


# ── 健康檢查（雲端探針用）────────────────────────────────────
# 打 GET /health 有回 {"status":"ok"} 就代表後端活著、能正常收請求。
# 雲端的監控／nginx 會定期戳這條確認服務沒掛，不查資料庫、不需登入，回得越快越好。
@router.get("/health")
def health_check():
    return {"status": "ok"}


# ── 指標輸出（Prometheus 抓取用）────────────────────────────
# 1. Prometheus 每隔固定秒數打這條，把當下所有指標的數字抄回去，存成歷史曲線。
# 2. generate_latest() 印出「整個行程裡所有 Counter」，不管它們定義在哪個檔案
#    （例如 events/router.py 的 EVENT_VERDICT_TOTAL）——prometheus_client 有一本
#    全域登記簿，Counter 一建立就自動登記，這裡不需要 import 它。
# 3. 包 Response 的原因：FastAPI 預設會把回傳值轉成 JSON，Prometheus 只吃純文字格式。
# 4. 目前不驗證身分（同 /health）。
@router.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
