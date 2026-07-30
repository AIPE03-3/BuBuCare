# agent/sample_store.py
"""主動學習樣本落地：複製圖檔 + 寫 sidecar JSON。

目錄結構（images/ 沿用 ai/vlm_worker.py 現況，meta/ 是新增的）：

    active_learning_dataset/
    ├── README.md                       ← 首次寫入時自動產生，說明這個資料夾是什麼
    ├── images/
    │   └── snapshot_101_20260719.jpg
    └── meta/
        └── snapshot_101_20260719.json  ← sidecar：為什麼收這張、多重要

**刻意不寫 labels/**：現況 vlm_worker.py:52 會產生一組寫死的假座標當作 YOLO-Pose 標註
（每張圖都是同一組數字，與畫面內容無關）。主動學習的唯一用途是回訓，
拿假標註去訓練比不收這張圖更糟，所以這裡只收圖與收錄理由，標註留給日後真正的標註步驟。

sidecar 採「一圖一檔」而非單一大索引檔：追加不必讀寫整份、並行寫不互相覆蓋、
寫到一半當機只毀一筆、搬移樣本時說明跟著圖走。
"""
import json
import logging
import shutil
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("agent.sample_store")

DATASET_README = """# active_learning_dataset

Agent 在複判過程中挑出的「值得回訓」樣本，由 `agent/nodes/al_curator.py` 判斷收錄。

## 結構

- `images/` —— 原始快照，檔名沿用邊緣端的 image_filename
- `meta/` —— 每張圖一份同名 sidecar JSON，記錄收錄理由、優先級、當時的判定結果

## 為什麼沒有 labels/

舊版 `ai/vlm_worker.py` 會產生 `labels/*.txt`，但內容是一組**寫死的假座標**
（每張圖都相同，與畫面內容無關）。拿假標註回訓會讓模型學到錯的東西，
比不收這張圖更糟，因此本目錄不產生標註檔。

回訓前請先做真正的標註步驟：人工標註，或對這批圖跑一次 YOLO-Pose 推論產生標註。

## 怎麼挑樣本

```bash
# 撈出高優先樣本
grep -l '"priority": "high"' meta/*.json
```
"""


class ActiveLearningStore:
    """把樣本寫到磁碟。碰檔案系統的部分全部在這裡，節點只呼叫 save()。"""

    def __init__(self, dataset_dir: str):
        self.dataset_dir = Path(dataset_dir)

    @property
    def images_dir(self) -> Path:
        return self.dataset_dir / "images"

    @property
    def meta_dir(self) -> Path:
        return self.dataset_dir / "meta"

    def _ensure_dirs(self) -> None:
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        # README 只在不存在時寫：日後有人翻到這個資料夾，不用問人就知道它是什麼
        readme = self.dataset_dir / "README.md"
        if not readme.exists():
            readme.write_text(DATASET_README, encoding="utf-8")

    def save(self, image_path: str, metadata: dict) -> str | None:
        """複製圖檔並寫 sidecar，回傳存放的圖檔路徑；失敗回 None。

        收樣本失敗不該影響主流程（事件還是要送出去），所以這裡吞掉例外只記 log。
        """
        try:
            self._ensure_dirs()
            source = Path(image_path)
            target = self.images_dir / source.name
            shutil.copy(source, target)

            sidecar = self.meta_dir / f"{source.stem}.json"
            payload = {
                "image": source.name,
                "collected_at": datetime.now().isoformat(timespec="seconds"),
                **metadata,
            }
            _write_json(sidecar, payload)

            logger.info("收錄主動學習樣本：%s（%s）", source.name, metadata.get("priority"))
            return str(target)
        except OSError as e:
            logger.error("樣本收錄失敗 %s：%s", image_path, e)
            return None


def _write_json(path: Path, payload: dict) -> None:
    # ensure_ascii=False：收錄理由是繁中，要讓人直接讀得懂
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
