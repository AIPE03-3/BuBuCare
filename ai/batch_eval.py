"""批次評估：一次跑完 `test_demo/` 所有單一動作短片，比較各觸發策略。

## 為什麼要這支

`local_pipeline_eval.py` 一次只看一支影片，而且需要人工標註時間段。單一動作的短片
不需要標註——**檔名就是標籤**：`Fall*` 全片該觸發、其餘全片都不該觸發。這讓評估
變得極便宜，也避開了剪接素材的污染問題（見 docs/2026-07-28-fall-detection-local-eval.md）。

## 為什麼比 test4.mp4 那種長片可信

test4 把 20 種情境混在一支影片裡，算出來的誤報率是各種情境的混合平均，看不出
「系統在哪一種動作上會出錯」。單一動作短片可以直接指出：撿東西誤報幾次、
坐下誤報幾次——這是可行動的資訊。

## 效能設計

每支影片**只跑一次推論**，把逐幀狀態記下來，再對各策略離線套用 `decide_trigger()`。
比較 N 種策略不需要 N 倍時間（實測比重跑快 3~4 倍）。

## 用法

```bash
ai/.venv/bin/python ai/batch_eval.py                    # 跑全部策略
ai/.venv/bin/python ai/batch_eval.py --modes geo-first  # 只跑指定策略
ai/.venv/bin/python ai/batch_eval.py --dir 其他資料夾
```
"""
import argparse
import sys
from collections import deque
from pathlib import Path

import cv2
import numpy as np
import torch
from ultralytics import YOLO

from local_pipeline_eval import (
    DEFAULT_ACT_WEIGHTS, DEFAULT_POSE_WEIGHTS, POSE_CONF, TRIGGER_MODES, WINDOW_SIZE,
    decide_trigger, extract_pose_state, load_act_model, pick_device, run_act,
    select_main_person,
)

# 檔名前綴 → 這支影片全片該不該觸發。
# 大小寫不敏感；比對時取最長的相符前綴，避免 "Fall" 誤吃 "FallDown" 之類的新命名。
FALL_PREFIXES = ("fall",)
NORMAL_PREFIXES = ("walk", "sitdown", "sit", "pickupobject", "pickup",
                   "squat", "bend", "liedown", "stand")
# 舊的剪接長片語意不同（一支裡混了 20 段跌倒與正常），不能用「整片一個標籤」評估
SKIP_PREFIXES = ("test",)


def classify_video(path):
    """依檔名判斷這支影片全片該不該觸發。回傳 (動作標籤, 該觸發嗎) 或 None＝跳過。"""
    name = path.stem.lower()
    if name.startswith(SKIP_PREFIXES):
        return None
    for prefix in FALL_PREFIXES:
        if name.startswith(prefix):
            return prefix, True
    for prefix in sorted(NORMAL_PREFIXES, key=len, reverse=True):
        if name.startswith(prefix):
            return prefix, False
    return None


def run_inference(video_path, pose_model, act_model, device, conf, no_skip=False):
    """跑一支影片，回傳每個處理幀的狀態（不含觸發判斷——那是各策略離線做的）。"""
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        return []

    frame_window = deque(maxlen=WINDOW_SIZE)
    records = []
    frame_count = 0
    processed_count = 0
    has_seen_person = False
    height_reference = None

    while True:
        ok, frame = capture.read()
        if not ok:
            break
        frame_count += 1
        if not no_skip and frame_count % 2 != 0:
            continue

        result = pose_model(frame, verbose=False, conf=conf)[0]
        pose_state = extract_pose_state(result, height_reference, frame.shape[0])

        if height_reference is None and 5 <= processed_count <= 20 and pose_state["valid"]:
            if result.boxes is not None and len(result.boxes) > 0:
                best_idx = select_main_person(result.boxes.conf.cpu().numpy(),
                                              result.boxes.xywh.cpu().numpy())
                if best_idx >= 0:
                    height_reference = float(result.boxes.xywh.cpu().numpy()[best_idx][3])

        if pose_state["valid"]:
            has_seen_person = True
        frame_window.append(pose_state["feature"])

        pred_class, act_confidence = 1, 0.0
        if len(frame_window) == WINDOW_SIZE:
            pred_class, act_confidence = run_act(act_model, frame_window, device)

        records.append({
            "pose_state": pose_state,
            "window_len": len(frame_window),
            "pred_class": pred_class,
            "act_conf": act_confidence,
            "has_seen_person": has_seen_person,
        })
        processed_count += 1

    capture.release()
    return records


def apply_mode(records, mode):
    """對已跑好的逐幀狀態套用某個觸發策略，回傳 (觸發幀數, 總幀數, 首次觸發幀序)。"""
    triggered = 0
    first_trigger = None
    for index, record in enumerate(records):
        should_trigger, _ = decide_trigger(
            record["pose_state"], record["window_len"], record["pred_class"],
            record["act_conf"], record["has_seen_person"], mode=mode,
        )
        if should_trigger:
            triggered += 1
            if first_trigger is None:
                first_trigger = index
    return triggered, len(records), first_trigger


def main():
    parser = argparse.ArgumentParser(description="批次評估單一動作短片")
    parser.add_argument("--dir", default=str(Path(__file__).resolve().parent / "test_demo"))
    parser.add_argument("--modes", nargs="+", default=sorted(TRIGGER_MODES))
    parser.add_argument("--conf", type=float, default=POSE_CONF)
    parser.add_argument("--no-skip", action="store_true", help="不跳幀")
    args = parser.parse_args()

    video_dir = Path(args.dir)
    targets = []
    for path in sorted(video_dir.glob("*.mp4")):
        classified = classify_video(path)
        if classified is None:
            continue
        targets.append((path, *classified))

    if not targets:
        print(f"❌ {video_dir} 裡沒有可辨識的短片"
              f"（檔名要以 {FALL_PREFIXES + NORMAL_PREFIXES} 之一開頭）")
        return 1

    device = pick_device()
    print(f"🚀 裝置：{device}｜{len(targets)} 支影片 × {len(args.modes)} 種策略")
    print("   （每支只推論一次，策略比較離線套用）\n")
    pose_model = YOLO(str(DEFAULT_POSE_WEIGHTS))
    pose_model.to(device)
    act_model = load_act_model(DEFAULT_ACT_WEIGHTS, device)

    results = {}
    for path, label, should_fire in targets:
        records = run_inference(path, pose_model, act_model, device, args.conf, args.no_skip)
        if not records:
            print(f"⚠️ 讀不到內容，略過：{path.name}")
            continue
        results[path.name] = {
            "label": label, "should_fire": should_fire, "records": len(records),
            "modes": {mode: apply_mode(records, mode) for mode in args.modes},
        }
        print(f"  ✓ {path.name}")

    # ── 逐片明細 ──
    header = f"\n{'影片':<26}{'動作':<14}{'該報':<6}"
    for mode in args.modes:
        header += f"{mode:>13}"
    print(header)
    print("-" * (46 + 13 * len(args.modes)))
    for name, data in results.items():
        row = f"{name:<26}{data['label']:<14}{'✓' if data['should_fire'] else '✗':<6}"
        for mode in args.modes:
            fired, total, _ = data["modes"][mode]
            row += f"{fired / total:>12.1%}"
        print(row)

    # ── 摘要：事件級與幀級分開看 ──
    # 事件級才是護理師的體感：她收到的是「一則通知」，不是「一幀」。
    # 一支正常動作的影片只要報過一次，對值班的人來說就是被吵了一次。
    print(f"\n{'=' * 70}")
    print("摘要")
    print(f"{'=' * 70}")
    fall_videos = [d for d in results.values() if d["should_fire"]]
    normal_videos = [d for d in results.values() if not d["should_fire"]]

    print(f"\n{'策略':<14}{'跌倒片抓到':<14}{'正常片誤報':<14}{'正常片幀誤報率':<16}{'跌倒片幀召回'}")
    print("-" * 70)
    for mode in args.modes:
        caught = sum(1 for d in fall_videos if d["modes"][mode][0] > 0)
        false_fired = sum(1 for d in normal_videos if d["modes"][mode][0] > 0)
        normal_frames = sum(d["modes"][mode][1] for d in normal_videos)
        normal_fired = sum(d["modes"][mode][0] for d in normal_videos)
        fall_frames = sum(d["modes"][mode][1] for d in fall_videos)
        fall_fired = sum(d["modes"][mode][0] for d in fall_videos)
        print(f"{mode:<14}"
              f"{f'{caught}/{len(fall_videos)}':<14}"
              f"{f'{false_fired}/{len(normal_videos)}':<14}"
              f"{normal_fired / normal_frames if normal_frames else 0:<16.1%}"
              f"{fall_fired / fall_frames if fall_frames else 0:.1%}")

    print("\n判讀：『跌倒片抓到』要接近滿分（漏一次可能出人命）；"
          "\n      『正常片誤報』是有幾支影片被誤報過——這個數字直接對應護理師被吵幾次。")

    # 哪些正常動作最容易誤報，指出下一個該修的地方
    print(f"\n{'─' * 70}")
    print("正常動作的誤報分佈（哪種動作最容易被誤判）")
    print(f"{'─' * 70}")
    by_label = {}
    for data in normal_videos:
        by_label.setdefault(data["label"], []).append(data)
    for mode in args.modes:
        parts = []
        for label, group in sorted(by_label.items()):
            fired = sum(1 for d in group if d["modes"][mode][0] > 0)
            parts.append(f"{label} {fired}/{len(group)}")
        print(f"  {mode:<12} " + "｜".join(parts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
