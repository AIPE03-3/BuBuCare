from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker

from core.config import DATABASE_URL, SSL_ROOT_CERT

# engine 實際負責跟資料庫溝通的引擎
# psycopg2 是 Python 連 PostgreSQL 的驅動程式（連線字串在 config.py 組好）
engine = create_engine(
    DATABASE_URL,
    # ── 連線池的保鮮機制 ───────────────────────────────────────────
    # 沒有這兩行會怎樣（2026-07-30 實測）：RDS 會單方面收掉閒置太久的連線，但連線池
    # 不知道，還是把那條「已經死掉」的連線借給下一個請求 → psycopg2 在真的送出查詢時
    # 才發現對面沒了，噴 `OperationalError: SSL SYSCALL error: EOF detected` → HTTP 500。
    # 症狀很賊：**重試一次就好了**（第二次借到的是新連線），所以容易被當成偶發網路問題
    # 放過。實測是後端閒置一段時間後的第一個 POST /login 直接 500，9 秒後重試就 200。
    pool_pre_ping=True,   # 借出前先送一個輕量探測，發現是死的就丟掉重開（代價是每次借用多一次 round-trip）
    pool_recycle=1800,    # 連線活超過 30 分鐘主動汰換，不等它被對面收掉
    connect_args={
        "sslmode": "verify-full",     # 要求驗證伺服器的 SSL 憑證，防止連到假的資料庫
        "sslrootcert": SSL_ROOT_CERT  # AWS RDS 的根憑證檔案，用來確認對方是真的 AWS
    }
)

# 每次要跟資料庫做事（查詢、新增），就會開一個 session
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base() # 之後 models.py 裡定義的表格，都要繼承這個 Base，這樣 SQLAlchemy 才知道哪些是資料庫的表

# 一個工具函式，負責「開一個 session 給你用，用完自動關掉」，避免你忘記關閉連線造成資源浪費
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def run_column_migrations():
    """補齊「舊表」缺的欄位——create_all 只建不存在的表，不會回頭改既有表的欄位。

    正式 RDS 上的 detect_events 表在加這三欄前就已經在用、有資料，所以 models.py
    的新欄位需要這裡手動 ALTER TABLE 補上。全新資料庫則是空轉（create_all 建表時就含這些欄位）。
    """
    with engine.begin() as conn:
        conn.execute(text(
            "DO $$ BEGIN "
            "CREATE TYPE ai_event_verdict AS ENUM ('true_alarm', 'false_alarm'); "
            "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
        ))
        conn.execute(text(
            "ALTER TABLE detect_events ADD COLUMN IF NOT EXISTS ai_verdict ai_event_verdict"
        ))
        conn.execute(text(
            "ALTER TABLE detect_events ADD COLUMN IF NOT EXISTS ai_confidence FLOAT"
        ))
        conn.execute(text(
            "ALTER TABLE detect_events ADD COLUMN IF NOT EXISTS ai_reasoning TEXT"
        ))