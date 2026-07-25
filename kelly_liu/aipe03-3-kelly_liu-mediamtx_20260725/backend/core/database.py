from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from backend.core.config import DATABASE_URL, SSL_ROOT_CERT


# 根據資料庫種類準備不同的連線參數
if DATABASE_URL.startswith("sqlite"):
    # SQLite 在 FastAPI 多執行緒環境需要這個設定
    connect_args = {
        "check_same_thread": False,
    }
else:
    # PostgreSQL / AWS RDS 使用 SSL 憑證驗證
    connect_args = {
        "sslmode": "verify-full",
        "sslrootcert": SSL_ROOT_CERT,
    }


# 只能建立一次 engine
engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
)


# SessionLocal 必須綁定上面建立完成的 engine
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()