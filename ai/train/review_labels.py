#!/usr/bin/env python3
"""把標註初稿畫成一張對照圖，讓校正用看的而不是逐支播影片。

校正 50 支影片是整條重訓路徑上唯一的人工瓶頸。逐支開播放器要 2 小時，
看縮圖對照只要 30 分鐘——絕大多數影片初稿是對的，掃一眼就能過。

產出：dataset/labels_review/<影片名>.jpg
    每張圖是連續取樣的畫面，**紅框 = 初稿判定的跌落區間**，左上角是原始幀號。
    看圖判斷：紅框有沒有正確涵蓋「開始失衡 → 完全著地」？

    - 對 → 什麼都不用做，初稿直接沿用
    - 錯 → 把正確幀號寫進 dataset/labels/<影片名>.txt

⚠ CAUCAFall 的受試者多數跌倒後會起身，影片後段是站立。
   標註只能涵蓋跌落過程，**不要延伸到起身**，否則模型會學成「躺著＝跌倒」。

用法：
    ai/.venv/bin/python ai/train/review_labels.py
    ai/.venv/bin/python ai/train/review_labels.py --only FallForwardS1 FallLeftS3
"""

import argparse
import re
import sys
from pathlib import Path

import cv2
import numpy as np

_AI_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_AI_DIR))

import dataset_utils as du  # noqa: E402

DEFAULT_DATASET = _AI_DIR / "train" / "dataset"

COLUMNS = 5
ROWS = 4
THUMB_WIDTH = 288
PADDING_FRAMES = 20     # 初稿區間前後各多看這麼多原始幀
COLOR_IN_SPAN = (0, 0, 255)     # BGR 紅：初稿判定的跌落區間
COLOR_OUT_SPAN = (90, 90, 90)   # 灰：區間外
_FRAME_PATTERN = re.compile(r"frame\s+(\d+)\s*[-~]\s*(\d+)", re.IGNORECASE)


def read_draft_span(draft_path):
    """讀初稿的 frame 區間。讀不到（含 `frame ?-?`）回 None。"""
    if not draft_path.is_file():
        return None
    match = _FRAME_PATTERN.search(draft_path.read_text(encoding="utf-8"))
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def pick_sample_frames(span, total_frames, count):
    """挑要顯示哪些原始幀。初稿存在就聚焦其前後，否則平均取樣整支。"""
    if span is None:
        return np.linspace(0, max(total_frames - 1, 0), count, dtype=int).tolist()
    start = max(0, span[0] - PADDING_FRAMES)
    end = min(total_frames - 1, span[1] + PADDING_FRAMES)
    if end <= start:
        return np.linspace(0, max(total_frames - 1, 0), count, dtype=int).tolist()
    return np.linspace(start, end, count, dtype=int).tolist()


def build_sheet(video_path, span):
    """讀影片，拼出對照圖。回傳 BGR 影像或 None。"""
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        return None
    total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    wanted = pick_sample_frames(span, total_frames, COLUMNS * ROWS)

    thumbnails = []
    for frame_index in wanted:
        capture.set(cv2.CAP_PROP_POS_FRAMES, int(frame_index))
        ok, frame = capture.read()
        if not ok:
            continue
        height = int(frame.shape[0] * THUMB_WIDTH / frame.shape[1])
        thumbnail = cv2.resize(frame, (THUMB_WIDTH, height))

        in_span = span is not None and span[0] <= frame_index <= span[1]
        color = COLOR_IN_SPAN if in_span else COLOR_OUT_SPAN
        cv2.rectangle(thumbnail, (0, 0), (THUMB_WIDTH - 1, height - 1), color, 4)
        label = f"{frame_index}"
        cv2.rectangle(thumbnail, (0, 0), (78, 26), (0, 0, 0), -1)
        cv2.putText(thumbnail, label, (5, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (255, 255, 255), 2)
        thumbnails.append(thumbnail)
    capture.release()

    if not thumbnails:
        return None
    thumb_height = thumbnails[0].shape[0]
    blank = np.zeros((thumb_height, THUMB_WIDTH, 3), dtype=np.uint8)
    while len(thumbnails) < COLUMNS * ROWS:
        thumbnails.append(blank)
    rows = [np.hstack(thumbnails[row * COLUMNS:(row + 1) * COLUMNS]) for row in range(ROWS)]
    return np.vstack(rows)


def annotate_header(sheet, stem, span):
    """在圖上方加一條說明列。"""
    header_height = 44
    header = np.zeros((header_height, sheet.shape[1], 3), dtype=np.uint8)
    if span is None:
        text = f"{stem}  |  NO DRAFT - label this one manually"
    else:
        text = f"{stem}  |  draft frame {span[0]}-{span[1]}  (red = fall span)"
    cv2.putText(header, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    return np.vstack([header, sheet])


def parse_args():
    parser = argparse.ArgumentParser(description="產生標註校正用的對照圖")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--only", nargs="*", default=None, help="只處理這些影片（不含副檔名）")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    dataset_dir = Path(args.dataset).resolve()
    videos_dir = dataset_dir / "videos"
    drafts_dir = dataset_dir / "labels_draft"
    review_dir = dataset_dir / "labels_review"

    splits = du.load_splits(dataset_dir)
    # 只有「原始」跌倒影片需要校正——鏡像檔共用來源標註
    names = [
        name for name in du.all_assigned_files(splits)
        if du.is_fall_video(Path(name).stem) and not du.is_flipped(Path(name).stem)
    ]
    if args.only:
        wanted = set(args.only)
        names = [name for name in names if Path(name).stem in wanted]
    if not names:
        print("❌ 沒有符合條件的影片", file=sys.stderr)
        return 1

    review_dir.mkdir(parents=True, exist_ok=True)
    done, skipped, no_draft = 0, 0, []

    for index, name in enumerate(sorted(names), 1):
        stem = Path(name).stem
        out_path = review_dir / f"{stem}.jpg"
        if out_path.exists() and not args.overwrite:
            skipped += 1
            continue

        span = read_draft_span(drafts_dir / f"{stem}.txt")
        if span is None:
            no_draft.append(stem)
        sheet = build_sheet(videos_dir / name, span)
        if sheet is None:
            print(f"❌ [{index}/{len(names)}] {stem}｜讀不到影片")
            continue
        cv2.imwrite(str(out_path), annotate_header(sheet, stem, span))
        done += 1
        span_text = f"frame {span[0]}-{span[1]}" if span else "無初稿"
        print(f"✅ [{index}/{len(names)}] {stem}｜{span_text}")

    print("-" * 68)
    print(f"產生 {done} 張｜跳過 {skipped}")
    if no_draft:
        print(f"⚠ 無初稿、需整支人工看（{len(no_draft)}）：" + ", ".join(no_draft))
    print(f"📁 {review_dir}")
    print("\n校正方式：看圖確認紅框是否正確涵蓋『開始失衡 → 完全著地』。")
    print("  正確 → 不用動；錯誤 → 把正確幀號寫進 dataset/labels/<影片名>.txt")
    print("  ⚠ 不要把區間延伸到『跌倒後起身』的部分。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
