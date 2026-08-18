# agent/image_store.py
"""圖檔存取抽象（見 agent/docs/01-architecture.md §8）。

背景：圖檔有兩份——S3 一份、邊緣端本機硬碟一份。Agent 不綁定特定機器，
所以 ingest 節點只認識 resolve() 這個介面，不知道也不在乎圖從哪來；
換部署位置只改 AGENT_IMAGE_SOURCE 環境變數，零程式碼改動。

兩種後端對下游完全同型：都回傳「本機可讀的絕對路徑」。
S3 後端因此一律先下載到暫存目錄——VLM（Ollama）只吃本機路徑。
"""
import time
from pathlib import Path
from typing import Protocol

from agent.config import Settings


class ImageNotFound(Exception):
    # 取不到圖。由 ingest 節點接住 → 記 DLQ 後跳過該筆，不讓 consumer 掛掉
    pass


class ImageStore(Protocol):
    def resolve(self, image_filename: str) -> str:
        """回傳本機可讀的絕對路徑；取不到丟 ImageNotFound。"""
        ...


class LocalImageStore:
    """AGENT_IMAGE_SOURCE=local：在 base_dir 底下找檔案。

    邊緣端「先發 Kafka、後寫檔」是有可能的，所以檔案還沒出現時會等一小段時間再看一次
    （沿用 vlm_worker.py 的既有行為，只是把寫死的 1 秒改成可設定）。
    """

    def __init__(self, base_dir: str, wait_seconds: float = 2.0):
        self.base_dir = Path(base_dir)
        self.wait_seconds = wait_seconds

    def resolve(self, image_filename: str) -> str:
        if not image_filename:
            raise ImageNotFound("訊息未帶 image_filename")

        path = self.base_dir / image_filename
        if path.exists():
            return str(path.resolve())

        # 沒等到就是真的沒有：不再自己編一個 snapshot_{cam_id}.jpg 去猜
        # （vlm_worker 舊行為會猜檔名，猜錯時 VLM 讀到別張圖，判讀結果會是錯的）
        time.sleep(self.wait_seconds)
        if path.exists():
            return str(path.resolve())

        raise ImageNotFound(f"找不到圖檔：{path}")


class S3ImageStore:
    """AGENT_IMAGE_SOURCE=s3：從 bucket 下載到本機暫存目錄後回傳路徑。

    憑證走標準 AWS 環境變數 / credentials 檔，程式碼不碰金鑰。
    同一個檔案已在暫存目錄就直接用，不重複下載。
    """

    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        region: str = "ap-northeast-1",
        cache_dir: str = "/tmp/agent-image-cache",
        client=None,
    ):
        self.bucket = bucket
        self.prefix = prefix
        self.region = region
        self.cache_dir = Path(cache_dir)
        self._client = client  # 測試注入 fake client；正式留 None 走 lazy 建立

    @property
    def client(self):
        # lazy import + lazy 建立：沒用到 S3 後端時不需要 boto3 連線，單測也不必裝憑證
        if self._client is None:
            import boto3

            self._client = boto3.client("s3", region_name=self.region)
        return self._client

    def _key_for(self, image_filename: str) -> str:
        # 待確認（不擋工）：S3 key 命名是否等於 image_filename，見 04-open-questions.md Q2
        if not self.prefix:
            return image_filename
        return f"{self.prefix.rstrip('/')}/{image_filename}"

    def resolve(self, image_filename: str) -> str:
        if not image_filename:
            raise ImageNotFound("訊息未帶 image_filename")

        local_path = self.cache_dir / image_filename
        if local_path.exists():
            return str(local_path.resolve())

        local_path.parent.mkdir(parents=True, exist_ok=True)
        key = self._key_for(image_filename)
        try:
            self.client.download_file(self.bucket, key, str(local_path))
        except Exception as e:
            # 下載失敗的原因（缺檔、沒權限、斷線）對下游沒有差別，一律當成取不到圖
            raise ImageNotFound(f"S3 下載失敗 s3://{self.bucket}/{key}：{e}") from e

        return str(local_path.resolve())


def build_image_store(settings: Settings) -> ImageStore:
    # 唯一決定「用哪個後端」的地方，其餘程式碼一律只認 ImageStore 介面
    if settings.image_source == "local":
        return LocalImageStore(settings.image_base_dir, settings.image_wait_seconds)
    if settings.image_source == "s3":
        return S3ImageStore(
            bucket=settings.s3_bucket,
            prefix=settings.s3_prefix,
            region=settings.s3_region,
            cache_dir=settings.s3_cache_dir,
        )
    # config.load_settings() 已擋掉其他值，走到這裡代表有人繞過 config 自己組 Settings
    raise ValueError(f"未知的 image_source：{settings.image_source!r}")


__all__ = [
    "ImageNotFound",
    "ImageStore",
    "LocalImageStore",
    "S3ImageStore",
    "build_image_store",
]
