# backend/main.py
# 整個 web 服務的組裝點：建 app、設 CORS、把各功能的 router 掛上去。
# 這裡刻意不放任何路由本體——路由住在自己的功能資料夾（users/、events/），
# 想看某個功能怎麼運作，就只要打開那一個資料夾。
#
# 啟動（先 cd backend）：uvicorn main:app --reload

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
# CORS：允許瀏覽器從其他網址呼叫這個 API（開發測試用）

from core.config import SKIP_DB_INIT
from core.database import Base, engine, run_column_migrations
from devices.router import router as device_router
from events.router import router as event_router
from reports.router import router as report_router
from streams.router import router as stream_router
from users.router import router as user_router

# 程式啟動時建立所有還不存在的資料表（表名見 core/models.py，例如 user_account）
# CI／測試環境設 SKIP_DB_INIT=1 時跳過：避免 import 當下就去連正式資料庫
# （雲端測試機連不到 AWS RDS，這行會卡住或報錯）
if not SKIP_DB_INIT:
    Base.metadata.create_all(bind=engine)
    run_column_migrations()  # 補既有表缺的欄位；全新表則空轉

# ── 建立 FastAPI app 本體 ─────────────────────────────────
# 這個 app 物件就是整個服務的核心，所有路由都掛在它身上
app = FastAPI()

# 告訴瀏覽器：「哪些網站可以存取我的 API。」
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 掛上各功能的路由 ──────────────────────────────────────
app.include_router(user_router)   # 帳號：register / login / me / delete
app.include_router(event_router)  # 事件：POST /events、SSE、判定 / 結案
app.include_router(device_router)  # 裝置：鏡頭清單 / 改名
app.include_router(report_router)  # 通報單：存 / 查
app.include_router(stream_router)  # 串流：換權杖 / 供 MediaMTX 驗證



# ── 健康檢查（雲端探針用）────────────────────────────────────
# 打 GET /health 有回 {"status":"ok"} 就代表後端活著、能正常收請求。
# 雲端的監控／nginx 會定期戳這條確認服務沒掛，不查資料庫、不需登入，回得越快越好。
@app.get("/health")
def health_check():
    return {"status": "ok"}