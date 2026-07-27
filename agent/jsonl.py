# agent/jsonl.py
"""JSON lines 落地：DLQ（壞訊息）與 shadow 判定記錄共用這一支。

選 JSON lines 而非資料庫的理由：這兩種記錄都是「追加、少讀、給人和腳本事後撈」的性質，
一行一筆、grep 得動、不必開 schema，也不會因為 Agent 寫記錄失敗就拖垮消費迴圈。
"""
import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("agent.jsonl")


def append_jsonl(path: str, record: dict) -> None:
    """追加一筆記錄，自動補上 logged_at 時間戳。

    寫檔失敗只記 log 不丟例外：記錄掉一筆，遠比整個 consumer 掛掉輕。
    """
    payload = {"logged_at": datetime.now().isoformat(), **record}
    try:
        file_path = Path(path)
        if file_path.parent != Path("."):
            file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "a", encoding="utf-8") as f:
            # ensure_ascii=False：繁中理由要人看得懂，不要變成 \uXXXX
            f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    except OSError as e:
        logger.error("寫入 %s 失敗：%s", path, e)
