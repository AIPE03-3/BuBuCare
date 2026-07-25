# backend/core/config.py
"""集中管理環境設定：整個 backend 只有這一支會讀 .env 和環境變數。

原本 database.py / auth.py / kafka_consumer.py 各自 load_dotenv() 一次，
「這個服務到底吃哪些環境變數」要翻三個檔案才知道，預設值也散落各處。
收攏到這裡後：想加/改設定只看這支；其他檔案一律 from backend.core.config import XXX。
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # 讀 repo 根目錄的 .env，讓底下的 os.getenv() 抓得到值

# backend/ 資料夾在磁碟上的絕對位置（用這支檔案自己的位置往上推兩層）。
# 憑證之類的檔案路徑都以它為基準，這樣不管從哪個資料夾下指令啟動都找得到。
BACKEND_DIR = Path(__file__).resolve().parent.parent


# ── 資料庫（PostgreSQL / AWS RDS）────────────────────────
# 格式是 SQLAlchemy 規定的：驅動程式://帳號:密碼@主機:埠號/資料庫名稱
# DATABASE_URL = (
#     f"postgresql+psycopg2://"
#     f"{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
#     f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
# )
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    (
        f"postgresql://"
        f"{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
        f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    ),
)


# AWS RDS 的根憑證，用來確認連到的是真的 AWS 而不是假冒的資料庫
SSL_ROOT_CERT = str(BACKEND_DIR / "global-bundle.pem")

# CI／測試環境設 1：跳過 import 當下的建表動作（雲端測試機連不到 AWS RDS）
SKIP_DB_INIT = os.getenv("SKIP_DB_INIT") == "1"


# ── JWT（登入後發給前端的通行證）──────────────────────────
SECRET_KEY = os.environ["SECRET_KEY"]  # 故意用 [] 不用 get()：沒設就啟動失敗，不要跑到一半才爆
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 1
STREAM_TOKEN_EXPIRE_SECONDS = int(os.getenv("STREAM_TOKEN_EXPIRE_SECONDS", "60"))
MEDIAMTX_PUBLISH_USER = os.getenv("MEDIAMTX_PUBLISH_USER", "")
MEDIAMTX_PUBLISH_PASS = os.getenv("MEDIAMTX_PUBLISH_PASS", "")


# ── 機器對機器驗證（判斷層打 POST /events 要帶這把 key）──
EVENT_API_KEY = os.getenv("EVENT_API_KEY", "")


# ── Kafka consumer（獨立行程用）─────────────────────────
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC = "processed-reports"
KAFKA_GROUP_ID = "fulilian-backend"
EVENTS_URL = os.getenv("EVENTS_URL", "http://localhost:8000/events")
RETRY_SLEEP_SECONDS = 5


# ── S3（事件影片/截圖，換發限時網址用）──
# albert 傳來的是 s3://aipe03-3/... 的物件位置；後端拿它換發限時可播放網址給前端。
# bucket 名稱藏在 s3:// 字串裡，這裡只需要 region 與存取金鑰。
S3_REGION = os.getenv("S3_REGION", "us-east-1")
S3_ACCESS_KEY_ID = os.getenv("ACCESS_KEY_ID", "")
S3_SECRET_ACCESS_KEY = os.getenv("SECRET_ACCESS_KEY", "")
S3_URL_TTL = int(os.getenv("S3_URL_TTL", "3600"))  # 限時網址存活秒數，預設 1 小時
