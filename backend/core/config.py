# backend/core/config.py
"""集中管理環境設定：整個 backend 只有這一支會讀 .env 和環境變數。

原本 database.py / auth.py / kafka_consumer.py 各自 load_dotenv() 一次，
「這個服務到底吃哪些環境變數」要翻三個檔案才知道，預設值也散落各處。
收攏到這裡後：想加/改設定只看這支；其他檔案一律 from core.config import XXX。
"""
import os
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv

load_dotenv()  # 讀 repo 根目錄的 .env，讓底下的 os.getenv() 抓得到值

# backend/ 資料夾在磁碟上的絕對位置（用這支檔案自己的位置往上推兩層）。
# 憑證之類的檔案路徑都以它為基準，這樣不管從哪個資料夾下指令啟動都找得到。
BACKEND_DIR = Path(__file__).resolve().parent.parent


# ── 資料庫（PostgreSQL / AWS RDS）────────────────────────
# 格式是 SQLAlchemy 規定的：驅動程式://帳號:密碼@主機:埠號/資料庫名稱
# 帳號/密碼先做網址編碼（quote_plus）：密碼含 @ # : / 等特殊字元時，直接塞進網址會破壞結構
# （@ 會被當成主機分隔、# 會被當成錨點截斷），編碼後 SQLAlchemy 連線時自動還原。
DATABASE_URL = (
    f"postgresql+psycopg2://"
    f"{quote_plus(os.getenv('DB_USER', ''))}:{quote_plus(os.getenv('DB_PASSWORD', ''))}"
    f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
)

# AWS RDS 的根憑證，用來確認連到的是真的 AWS 而不是假冒的資料庫
SSL_ROOT_CERT = str(BACKEND_DIR / "global-bundle.pem")

# CI／測試環境設 1：跳過 import 當下的建表動作（雲端測試機連不到 AWS RDS）
SKIP_DB_INIT = os.getenv("SKIP_DB_INIT") == "1"


# ── JWT（登入後發給前端的通行證）──────────────────────────
SECRET_KEY = os.environ["SECRET_KEY"]  # 故意用 [] 不用 get()：沒設就啟動失敗，不要跑到一半才爆
ALGORITHM = "HS256"
# 登入 token 的壽命。原本是 1 天，2026-07-29 縮到 8 小時（約一個班次）。
# 縮短的理由：JWT 無法撤銷——按登出只是前端把 token 丟掉，後端仍然認得它，
# 所以「有效期」就是 token 外流後唯一的止血點，1 天的冒用窗口太長。
# 8 小時是安全與便利的折衷：值班人員一個班次內不會被登出。
# 徹底的解法是 refresh token（短效 access + 長效換票券），見 backend/docs/future-work.md 第 1 項。
ACCESS_TOKEN_EXPIRE_HOURS = 8


# ── 機器對機器驗證（判斷層打 POST /events 要帶這把 key）──
EVENT_API_KEY = os.getenv("EVENT_API_KEY", "")


# ── Kafka consumer（獨立行程用）─────────────────────────
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC = "processed-reports"
KAFKA_GROUP_ID = "fulilian-backend"
EVENTS_URL = os.getenv("EVENTS_URL", "http://localhost:8000/events")
RETRY_SLEEP_SECONDS = 5


# ── S3（事件影片/截圖，換發限時網址用）──
# AI 端傳來的是 s3://aipe03-3/... 的物件位置；後端拿它換發限時可播放網址給前端。
# bucket 名稱藏在 s3:// 字串裡，這裡只需要 region 與存取金鑰。
S3_REGION = os.getenv("S3_REGION", "us-east-1")
S3_ACCESS_KEY_ID = os.getenv("ACCESS_KEY_ID", "")
S3_SECRET_ACCESS_KEY = os.getenv("SECRET_ACCESS_KEY", "")
S3_URL_TTL = int(os.getenv("S3_URL_TTL", "3600"))  # 限時網址存活秒數，預設 1 小時


# ── 攝影機即時串流（MediaMTX）──
# 值要含協定與埠號，例如 http://192.168.1.108:8889；留空代表這個環境沒有串流。
# 換場地或換電腦只要改這一個值、重啟後端即可，前端不用重新 build、資料庫不用改。
# ⚠ 前端若跑在 https，這裡必須一併改成 https://——瀏覽器不允許 https 頁面載入 http 串流。
MEDIAMTX_BASE_URL = os.getenv("MEDIAMTX_BASE_URL", "")

# 串流權杖有效秒數。刻意設很短：權杖會出現在 MediaMTX 與 nginx 的存取紀錄裡，
# 過期越快、萬一外流可用的時間越短。60 秒足夠瀏覽器完成一次 WHEP 協商。
STREAM_TOKEN_EXPIRE_SECONDS = int(os.getenv("STREAM_TOKEN_EXPIRE_SECONDS", "60"))

# AI 端讀取串流用的帳密。他們的推論程式走 RTSP 讀 cam_in，拿不到瀏覽器才有的
# 短命權杖，所以另外給一組固定憑證（推流不受影響，MediaMTX 那邊直接放行）。
# 預設空字串，且空字串一律拒絕（fail-closed）：
# 寧可「忘了設 → 讀不到」，也不要「忘了設 → 整條 RTSP 對外全開」。
STREAM_RTSP_USER = os.getenv("STREAM_RTSP_USER", "")
STREAM_RTSP_PASS = os.getenv("STREAM_RTSP_PASS", "")
