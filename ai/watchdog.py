import time
import subprocess
import logging
import signal
import sys
from pathlib import Path

# 移植自 Albert Fall/tools/watchdog.py：清掉 Mac 硬編路徑，一律以本檔為基準（ai/）。
BASE_DIR = Path(__file__).resolve().parent

# 設定詳細日誌格式（log 落在 ai/watchdog.log）
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(str(BASE_DIR / "watchdog.log"))
    ]
)
logger = logging.getLogger("AdvancedWatchdog")

# 設定與路徑（同層的標註 SDK）
INFERENCE_SCRIPT = str(BASE_DIR / "inference_to_labelstudio_sdk.py")
INTERVAL = 300  # 掃描間隔 5 分鐘

def graceful_exit(signum, frame):
    logger.info("收到終止訊號，正在安全關閉監控服務...")
    sys.exit(0)

# 註冊訊號處理，確保系統關閉時不會產生殘留錯誤
signal.signal(signal.SIGINT, graceful_exit)
signal.signal(signal.SIGTERM, graceful_exit)

def run_sync():
    """執行同步標註腳本並處理異常"""
    logger.info(">>> 開始執行 S3 影像同步與自動標註流程...")
    try:
        # 用 sys.executable 確保吃到 venv 的 Python（含 ultralytics / requests / boto3）
        result = subprocess.run(
            [sys.executable, INFERENCE_SCRIPT],
            capture_output=True,
            text=True,
            check=True
        )
        # 顯示同步輸出的關鍵摘要
        if result.stdout:
            logger.info(f"執行結果: {result.stdout.strip()}")

    except subprocess.CalledProcessError as e:
        logger.error(f"同步腳本執行失敗 (Exit Code: {e.returncode})")
        logger.error(f"錯誤訊息: {e.stderr.strip()}")
    except Exception as e:
        logger.error(f"系統異常: {str(e)}")

if __name__ == "__main__":
    logger.info("🚀 監控服務已就緒，進入全自動模式...")

    while True:
        run_sync()
        logger.info(f"[*] 任務完成，進入休眠 {INTERVAL} 秒，系統維持待命狀態...")
        time.sleep(INTERVAL)
