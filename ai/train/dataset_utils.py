"""資料集共用邏輯：讀切分、判標籤、處理鏡像檔的標註對應。

`extract_features.py` 與 `train_act.py` 都從這裡取規則，不要各自重寫一份——
切分規則寫兩份，遲早會不一致，而不一致的症狀是「數字很好但上線不對」，很難查。
"""

import json
import re
from pathlib import Path

_SUBJECT_PATTERN = re.compile(r"S(\d+)$", re.IGNORECASE)
_LEFT_RIGHT_PATTERN = re.compile(r"left|right", re.IGNORECASE)

# 與 build_dataset.py 的 FLIP_OFFSET 一致。鏡像檔的受試者編號 = 來源 + 10
FLIP_OFFSET = 10
# 檔名前綴 → 這支影片是不是跌倒。與 batch_eval.py 的 classify_video() 同語意
FALL_PREFIXES = ("fall",)


def load_splits(dataset_dir):
    """讀 splits.json。回傳整份 dict。

    訓練腳本一律從這裡拿檔案清單，**不要自己 glob videos/**——
    那樣會把測試集與被排除的鏡像檔一起吃進訓練，而且數字上看不出異常。
    """
    splits_path = Path(dataset_dir) / "splits.json"
    if not splits_path.is_file():
        raise FileNotFoundError(
            f"找不到 {splits_path}，請先執行 ai/train/build_dataset.py"
        )
    return json.loads(splits_path.read_text(encoding="utf-8"))


def split_files(splits, split_name):
    """取某個 split 的檔名清單（不含被排除的鏡像檔）。"""
    files = splits["splits"].get(split_name)
    if files is None:
        available = ", ".join(sorted(splits["splits"]))
        raise KeyError(f"沒有這個 split：{split_name}（可用：{available}）")
    return list(files)


def all_assigned_files(splits):
    """所有有被分配到 split 的檔名（train + val + test），排除 excluded。"""
    names = []
    for files in splits["splits"].values():
        names.extend(files)
    return sorted(names)


def parse_subject(stem):
    """從檔名取受試者編號。取不到回 None。"""
    match = _SUBJECT_PATTERN.search(stem)
    return int(match.group(1)) if match else None


def is_flipped(stem):
    """這支是不是鏡像檔（受試者編號 > FLIP_OFFSET）。"""
    subject = parse_subject(stem)
    return subject is not None and subject > FLIP_OFFSET


def is_fall_video(stem):
    """檔名前綴判斷是不是跌倒影片。"""
    return stem.lower().startswith(FALL_PREFIXES)


def _swap_left_right(text):
    """left/right 對調，保留大小寫風格。"""

    def replace(match):
        word = match.group(0)
        target = "right" if word.lower() == "left" else "left"
        if word.isupper():
            return target.upper()
        if word[0].isupper():
            return target.capitalize()
        return target

    return _LEFT_RIGHT_PATTERN.sub(replace, text)


def label_source_stem(stem):
    """回傳這支影片該用哪一份標註（的檔名 stem）。

    鏡像檔不另存標註——水平翻轉不改變時間軸，跌落起訖與來源完全相同。
    只存一份的好處是不會發生「校正了原始、忘了同步鏡像」這種不對稱錯誤。

        FallRightS11 → FallLeftS1
        FallForwardS3 → FallForwardS3（原始檔，回傳自己）
    """
    subject = parse_subject(stem)
    if subject is None or subject <= FLIP_OFFSET:
        return stem
    source = _SUBJECT_PATTERN.sub(lambda m: f"S{int(m.group(1)) - FLIP_OFFSET}", stem)
    # 鏡像時檔名的 Left/Right 被對調過，要換回來才對得上來源標註
    return _swap_left_right(source)


def label_path_for(dataset_dir, stem):
    """這支影片對應的標註檔路徑（鏡像檔會指向來源的標註）。"""
    return Path(dataset_dir) / "labels" / f"{label_source_stem(stem)}.txt"


def is_draft_label(label_path):
    """這份標註還是未校正的初稿嗎（第一行帶 `# STATUS: DRAFT`）。

    初稿是啟發式猜的，直接拿去訓練等於用雜訊當真值。
    校正完把該行改成 `# STATUS: REVIEWED`。
    """
    path = Path(label_path)
    if not path.is_file():
        return False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip().upper()
        if stripped.startswith("# STATUS:"):
            return "DRAFT" in stripped
    return False
