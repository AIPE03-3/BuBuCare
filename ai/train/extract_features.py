#!/usr/bin/env python3
"""影片 → AcT 訓練特徵（.npz），並順便產生跌落區間的標註初稿。

⚠ 本腳本刻意 import `local_pipeline_eval` 的 `extract_pose_state()`，
   **不自己重寫一份特徵抽取**。訓練用的特徵與線上推論用的特徵只要有一點不一致，
   離線數字會漂亮、上線會變差，而且極難 debug。要改特徵請改那一份，兩邊一起變。

輸出：
    dataset/features/<影片名>.npz   逐處理幀的 34 維特徵與幾何旗標
    dataset/labels_draft/<影片名>.txt   跌落區間初稿（**只有跌倒影片、且必須人工校正**）

用法：
    # 先抽跌倒影片（標註要用），再抽其餘
    ai/.venv/bin/python ai/train/extract_features.py --only-fall
    ai/.venv/bin/python ai/train/extract_features.py

    # 只抽某個 split
    ai/.venv/bin/python ai/train/extract_features.py --splits train val
"""

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

_AI_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_AI_DIR))

from local_pipeline_eval import (  # noqa: E402  （要先插 sys.path 才 import 得到）
    DEFAULT_POSE_WEIGHTS, OCCLUDED_HEIGHT_RATIO, POSE_CONF,
    extract_pose_state, select_main_person,
)
from pose_features import DEFAULT_FEATURE_NORM, FEATURE_NORMS  # noqa: E402
import dataset_utils as du  # noqa: E402

DEFAULT_DATASET = _AI_DIR / "train" / "dataset"
# 跳幀。與正式管線 inference_test.py:536 一致：每 2 幀處理 1 幀
FRAME_SKIP = 2
# 身高基準的取樣區間（處理幀計數），對齊 local_pipeline_eval.py 的做法
HEIGHT_REF_RANGE = (5, 20)

# ── 標註初稿的啟發式參數 ────────────────────────────────────────────────
# 這些只影響「初稿」，不影響訓練。校正過的標註才是真實來源。
#
# 參數是看實際曲線調出來的，不是猜的。實測（CAUCAFall，跳幀 2 後）：
#   - 下墜過程約 5~16 個處理幀（0.5~1.6 秒）
#   - `is_lying` 靠軀幹角度判斷，在**下墜中途**就會成立，比高度變化早好幾幀，
#     所以它只拿來當「跌落已發生」的訊號，不當結束點
#   - 多數受試者跌倒後會起身，影片後段是站立——初稿絕不能延伸到那裡
LYING_HEIGHT_RATIO = 0.55    # 低於此視為已躺平/被遮擋
STANDING_HEIGHT_RATIO = 0.9  # 高於此視為還站著（下墜起點）
SETTLE_FRAMES = 3            # 觸發後再往後延幾幀，涵蓋「躺穩」
MIN_FALL_FRAMES = 5          # 跌落至少這麼多處理幀（0.5 秒）
# 超過這個長度視為可疑：跌落不會拖到 2 秒。
# 典型成因是 Fall sitting——人本來就坐著，往前回推永遠找不到「站著」的幀。
SUSPICIOUS_FALL_FRAMES = 20
MAX_FALL_FRAMES = 30         # 往前回推的上限（3 秒）
SEARCH_START_AFTER = 5       # 前幾個處理幀不找跌落起點（身高基準還沒建立）
# ────────────────────────────────────────────────────────────────────────


def extract_one_video(video_path, pose_model, conf, occluded_height_ratio, feature_norm):
    """跑一支影片，回傳逐處理幀的特徵與幾何旗標（各為等長 array）。"""
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        return None

    features, is_lying, is_occluded, height_ratios, valids = [], [], [], [], []
    normal_height_reference = None
    frame_count = 0
    processed_count = 0

    while True:
        ok, frame = capture.read()
        if not ok:
            break
        frame_count += 1
        if frame_count % FRAME_SKIP != 0:
            continue

        image_height = frame.shape[0]
        result = pose_model(frame, verbose=False, conf=conf)[0]
        state = extract_pose_state(result, normal_height_reference, image_height,
                                   occluded_height_ratio, feature_norm)

        # 身高基準：取前期幾幀的人框高度，之後拿來判斷「突然變矮」
        if normal_height_reference is None and state["valid"] \
                and HEIGHT_REF_RANGE[0] <= processed_count <= HEIGHT_REF_RANGE[1]:
            if result.boxes is not None and len(result.boxes) > 0:
                boxes_xywh = result.boxes.xywh.cpu().numpy()
                best_idx = select_main_person(result.boxes.conf.cpu().numpy(), boxes_xywh)
                if best_idx >= 0:
                    normal_height_reference = float(boxes_xywh[best_idx][3])

        features.append(state["feature"])
        is_lying.append(state["is_lying"])
        is_occluded.append(state["is_occluded"])
        height_ratios.append(np.nan if state["height_ratio"] is None else state["height_ratio"])
        valids.append(state["valid"])
        processed_count += 1

    capture.release()
    if not features:
        return None

    return {
        "features": np.asarray(features, dtype=np.float32),
        "is_lying": np.asarray(is_lying, dtype=bool),
        "is_occluded": np.asarray(is_occluded, dtype=bool),
        "height_ratio": np.asarray(height_ratios, dtype=np.float32),
        "valid": np.asarray(valids, dtype=bool),
        "frame_skip": np.int32(FRAME_SKIP),
        # 特徵是哪種正規化算出來的，跟著特徵一起走。train_act.py 靠它擋混用，
        # 光看 .npz 的數值分不出 image 還是 bbox（都是 34 維 float32）
        "feature_norm": np.str_(feature_norm),
    }


def guess_fall_span(data):
    """從幾何旗標猜跌落區間。回傳 (起始處理幀, 結束處理幀) 或 None。

    ⚠ 這是啟發式初稿，**不是標註**。
    邏輯：先找「第一次躺平/大幅變矮」當結束點，再往前回推到「還站著」當起點。
    前跌在某些視角下幾何看不出來，這種影片會回 None，必須整支人工標。
    """
    is_lying = data["is_lying"]
    height_ratio = data["height_ratio"]
    total = len(is_lying)

    lying_like = is_lying | (np.nan_to_num(height_ratio, nan=1.0) < LYING_HEIGHT_RATIO)
    candidates = np.flatnonzero(lying_like)
    candidates = candidates[candidates >= SEARCH_START_AFTER]
    if candidates.size == 0:
        return None

    # 觸發點是「跌落中」而非「跌落完」，往後延幾幀涵蓋躺穩的過程
    trigger_idx = int(candidates[0])
    end_idx = min(total - 1, trigger_idx + SETTLE_FRAMES)

    # 起點：往前找最後一個「還站著」的幀。用高度比而非 is_lying，
    # 因為軀幹角度在下墜中途就變了，用它會把起點抓得太晚、區間退化成兜底值。
    lower_bound = max(0, trigger_idx - MAX_FALL_FRAMES)
    start_idx = lower_bound
    for idx in range(trigger_idx - 1, lower_bound - 1, -1):
        ratio = height_ratio[idx]
        if np.isnan(ratio):
            continue  # 基準還沒建立，這幀給不出資訊，不能當作「站著」
        if not is_lying[idx] and ratio >= STANDING_HEIGHT_RATIO:
            start_idx = idx
            break

    if end_idx - start_idx < MIN_FALL_FRAMES:
        start_idx = max(0, end_idx - MIN_FALL_FRAMES)
    if start_idx >= end_idx:
        return None
    return start_idx, end_idx


def write_label_draft(path, stem, span, frame_skip):
    """把初稿寫成 parse_label_file() 讀得懂的格式（原始幀號）。"""
    lines = [
        # 這行讓 train_act.py 能算出「還有幾支沒校正」。校正完請把 DRAFT 改成 REVIEWED。
        "# STATUS: DRAFT",
        f"# {stem} 跌落區間 —— 自動產生的初稿，**必須人工校正後才能使用**",
        "# 校正完把上面那行改成 `# STATUS: REVIEWED`",
        "# 幀號為原始幀號（未跳幀）。格式也接受 0:03-0:05 這種時間寫法。",
    ]
    if span is None:
        lines.append("# ⚠ 幾何判斷找不到跌落點，這支要整支人工看過再填")
        lines.append("# 直接把下面那行的 ?-? 換成幀號即可（那行沒有 #，填了就生效）")
        # 佔位符刻意不加 `#`：加了的話填完數字仍是註解、永遠不生效，
        # 而且不會報錯只會靜默少樣本——這個坑實際踩過一次。
        # `?-?` 不匹配 parse_label_file 的數字 regex，所以未填寫時同樣不會被解析。
        lines.append("frame ?-?")
    else:
        start, end = span
        lines.append(f"frame {start * frame_skip}-{end * frame_skip}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args():
    parser = argparse.ArgumentParser(description="抽 AcT 訓練特徵並產生標註初稿")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET), help="資料集目錄")
    parser.add_argument("--splits", nargs="*", default=None,
                        help="只處理這些 split（預設全部 train/val/test）")
    parser.add_argument("--only-fall", action="store_true",
                        help="只處理跌倒影片（標註要先做，先抽這批）")
    parser.add_argument("--pose-weights", default=str(DEFAULT_POSE_WEIGHTS))
    parser.add_argument("--conf", type=float, default=POSE_CONF)
    parser.add_argument("--occ-height", type=float, default=OCCLUDED_HEIGHT_RATIO)
    parser.add_argument("--overwrite", action="store_true", help="重算已存在的特徵")
    parser.add_argument("--drafts-only", action="store_true",
                        help="不跑 pose，直接讀現成的 .npz 重算標註初稿（調參數用）")
    parser.add_argument("--feature-norm", default=DEFAULT_FEATURE_NORM, choices=FEATURE_NORMS,
                        help="特徵正規化基準：image=整張畫面（預設）／bbox=人物框。"
                             "各自存到不同目錄，不會覆蓋對方")
    return parser.parse_args()


def main():
    args = parse_args()
    dataset_dir = Path(args.dataset).resolve()
    videos_dir = dataset_dir / "videos"
    features_dir = du.features_dir(dataset_dir, args.feature_norm)
    drafts_dir = dataset_dir / "labels_draft"

    splits = du.load_splits(dataset_dir)
    if args.splits:
        names = []
        for split_name in args.splits:
            names.extend(du.split_files(splits, split_name))
    else:
        names = du.all_assigned_files(splits)
    if args.only_fall:
        names = [name for name in names if du.is_fall_video(Path(name).stem)]
    names = sorted(set(names))

    if not names:
        print("❌ 沒有符合條件的影片", file=sys.stderr)
        return 1

    pose_model = None
    if not args.drafts_only:
        from ultralytics import YOLO  # 放這裡：載入很慢，參數錯誤時不必等它
        print(f"📦 載入 pose 權重：{args.pose_weights}")
        pose_model = YOLO(str(args.pose_weights))

    features_dir.mkdir(parents=True, exist_ok=True)
    drafts_dir.mkdir(parents=True, exist_ok=True)
    if args.drafts_only:
        print(f"📝 只重算標註初稿（讀現成特徵，不跑 pose）")
    print(f"🎬 待處理 {len(names)} 支｜跳幀 {FRAME_SKIP}｜conf {args.conf}")
    print("-" * 68)

    done, skipped, failed = 0, 0, []
    drafts_written, drafts_missing, drafts_suspicious = 0, [], []

    for index, name in enumerate(names, 1):
        stem = Path(name).stem
        video_path = videos_dir / name
        feature_path = features_dir / f"{stem}.npz"

        if args.drafts_only:
            if not feature_path.exists():
                skipped += 1
                continue
            data = np.load(feature_path)
        else:
            if feature_path.exists() and not args.overwrite:
                skipped += 1
                continue
            if not video_path.is_file():
                print(f"❌ [{index}/{len(names)}] {name}｜影片不存在")
                failed.append(name)
                continue

            data = extract_one_video(video_path, pose_model, args.conf, args.occ_height,
                                     args.feature_norm)
            if data is None:
                print(f"❌ [{index}/{len(names)}] {name}｜讀不到任何幀")
                failed.append(name)
                continue
            np.savez_compressed(feature_path, **data)
        done += 1
        valid_rate = float(data["valid"].mean())
        note = ""

        # 標註初稿只對「原始」跌倒影片產生——鏡像檔共用來源的標註，不另存一份
        if du.is_fall_video(stem) and not du.is_flipped(stem):
            span = guess_fall_span(data)
            draft_path = drafts_dir / f"{stem}.txt"
            if not draft_path.exists() or args.overwrite:
                write_label_draft(draft_path, stem, span, FRAME_SKIP)
            if span is None:
                drafts_missing.append(stem)
                note = "｜⚠ 猜不出跌落點，需整支人工標"
            else:
                drafts_written += 1
                note = f"｜初稿 frame {span[0] * FRAME_SKIP}-{span[1] * FRAME_SKIP}"
                if span[1] - span[0] > SUSPICIOUS_FALL_FRAMES:
                    drafts_suspicious.append(stem)
                    note += " ⚠ 過長，優先校正"

        print(f"✅ [{index}/{len(names)}] {stem}｜{len(data['features'])} 幀"
              f"｜偵測率 {valid_rate:.0%}{note}")

    print("-" * 68)
    print(f"完成 {done}｜跳過（已存在）{skipped}｜失敗 {len(failed)}")
    if drafts_written or drafts_missing:
        print(f"標註初稿：產生 {drafts_written} 份，猜不出的 {len(drafts_missing)} 份")
        if drafts_missing:
            print(f"  ⚠ 需整支人工標（{len(drafts_missing)}）：" + ", ".join(drafts_missing))
        if drafts_suspicious:
            print(f"  ⚠ 區間過長、優先校正（{len(drafts_suspicious)}）："
                  + ", ".join(drafts_suspicious))
        print(f"  📁 {drafts_dir}")
        print("  ⚠ 初稿是啟發式猜的，校正後請存到 dataset/labels/（不要直接用初稿訓練）")
    if failed:
        print("失敗：" + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
