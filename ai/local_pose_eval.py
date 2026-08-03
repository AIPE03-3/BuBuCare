"""本地 pose 辨識效果評估：不經 Triton，直接載 `yolo11s-pose.pt` 跑自己的圖片／影片。

## 為什麼需要這支

正式管線 `inference_test.py` 三顆模型**全部打 Triton**，而 `rt_detr` 那顆是 Blackwell
專屬的 TensorRT `.plan`（見 `triton_repo/README.md`），開發機（macOS）根本起不來。
要在自己電腦上先確認「骨架抓得準不準」，需要一條不依賴 Triton 的路。

## 這支看的是什麼

**不是**「有沒有畫出骨架」——那看起來永遠很漂亮。看的是**跌倒判斷真正吃進去的那幾個輸入**，
判斷邏輯逐項對齊 `inference_test.py:663-702`：

| 指標 | 對應正式管線 | 為什麼重要 |
|---|---|---|
| 選中的人 | `:672-678` `conf × (w×h)` 取最大 | 系統只看一個人，選錯人後面全錯 |
| 34 維特徵是否全零 | `:683` `np.all(temp_feat == 0)` | 全零＝這幀餵給 AcT 也是廢的，等於沒偵測到 |
| `body_angle` / `w_box/h_box` | `:697` 躺平判斷的兩個輸入 | 直接決定 `is_physically_lying` |
| 關鍵點缺失 | `xyn` 為 0 即該點沒抓到 | 肩(5,6)/臀(11,12) 缺一個，body_angle 就算不出來 |

所以輸出會告訴你「這一幀對跌倒判斷**有沒有用**」，而不只是「有沒有看到人」。

## 用法

```bash
# 單張圖 / 影片 / 整個資料夾
.venv/bin/python ai/local_pose_eval.py 路徑

# 即時看畫面（按 q 離開）
.venv/bin/python ai/local_pose_eval.py 路徑 --show

# 調門檻（預設 0.45，對齊正式管線的 conf）
.venv/bin/python ai/local_pose_eval.py 路徑 --conf 0.3
```

輸出的標註圖／影片預設寫到 `ai/pose_eval_out/`。
"""
import argparse
import os
import sys
from pathlib import Path

import cv2
import numpy as np
import torch
from ultralytics import YOLO

# 這支量的是「關鍵點抓得好不好」，跟 AcT 用哪種正規化無關，故固定用 image-norm
# （bbox-norm 只是同一組點的線性變換，抓不到就是抓不到，換基準不會變出點來）
from pose_features import is_feature_valid, pose_feature_image_norm
from fall_chain import person_geometry

# 對齊 inference_test.py:564 的 conf=0.45。門檻不同，選中的人可能就不同，
# 拿別的值測出來的結論套不回正式管線。
DEFAULT_CONF = 0.45

# 權重與這支腳本同目錄（ai/）。不寫死絕對路徑，換機器照樣跑。
_AI_DIR = Path(__file__).resolve().parent
DEFAULT_WEIGHTS = _AI_DIR / "yolo11s-pose.pt"
DEFAULT_OUT_DIR = _AI_DIR / "pose_eval_out"

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv"}

# COCO 17 點。索引是硬編在正式管線裡的（肩 5/6、臀 11/12），這裡列全是為了讓
# 缺點報告看得懂是哪個部位沒抓到。
KEYPOINT_NAMES = [
    "鼻", "左眼", "右眼", "左耳", "右耳",
    "左肩", "右肩", "左肘", "右肘", "左腕", "右腕",
    "左髖", "右髖", "左膝", "右膝", "左踝", "右踝",
]
# 肩 5/6、臀 11/12 的索引在 fall_chain.py，這支不再自己宣告一份


def pick_device():
    """Mac 用 MPS、有 CUDA 用 CUDA、都沒有退 CPU（同 inference_test.py:48 的選法）。"""
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def select_main_person(boxes_conf, boxes_xywh, conf_threshold):
    """複製正式管線的選人規則：conf 過門檻者中，`conf × 框面積`最大的那一個。

    回傳索引；沒有任何人過門檻回 -1。

    為什麼要照抄而不是「取信心最高」：正式管線就是這樣選的
    （inference_test.py:672-678），選人規則不同，測出來的結論套不回去。
    面積納入考量是為了偏好「近的人」——遠處路過的訪客不該蓋掉床邊的住民。
    """
    best_idx, max_score = -1, -1.0
    for idx in range(len(boxes_xywh)):
        if idx >= len(boxes_conf) or boxes_conf[idx] < conf_threshold:
            continue
        _, _, width, height = boxes_xywh[idx]
        score = boxes_conf[idx] * (width * height)
        if score > max_score:
            max_score, best_idx = score, idx
    return best_idx


def analyze(result, conf_threshold):
    """把一幀的推論結果抽成評估指標 dict。沒有人時回 person_count=0。"""
    empty = {"person_count": 0, "best_idx": -1}
    if result.keypoints is None or len(result.keypoints) == 0:
        return empty
    if result.boxes is None or len(result.boxes) == 0:
        return empty

    keypoints_norm = result.keypoints.xyn.cpu().numpy()
    boxes_conf = result.boxes.conf.cpu().numpy()
    boxes_xywh = result.boxes.xywh.cpu().numpy()
    if keypoints_norm.ndim != 3 or keypoints_norm.shape[0] == 0:
        return empty

    best_idx = select_main_person(boxes_conf, boxes_xywh, conf_threshold)
    if best_idx < 0:
        # 有偵測到人，但沒有人過 conf 門檻——這是「有畫面但對判斷無用」的典型情況
        return {"person_count": len(boxes_conf), "best_idx": -1}

    keypoints = keypoints_norm[best_idx]
    feature_34 = pose_feature_image_norm(keypoints)
    _, _, width, height = boxes_xywh[best_idx]
    # 幾何判斷走 fall_chain 那一份，不在這裡重算。這支只看輸入品質，
    # 只要防線 A（躺平）——防線 B 需要跨幀的身高基準，這支沒有那個狀態
    geometry = person_geometry(keypoints, boxes_xywh[best_idx])
    angle = geometry["body_angle"]
    aspect_ratio = geometry["aspect_ratio"]
    is_lying = geometry["is_lying"]

    return {
        "person_count": len(boxes_conf),
        "best_idx": int(best_idx),
        "best_conf": float(boxes_conf[best_idx]),
        "feature_valid": is_feature_valid(feature_34),
        "missing_keypoints": [
            KEYPOINT_NAMES[i] for i in range(17)
            if keypoints[i][0] == 0 and keypoints[i][1] == 0
        ],
        "body_angle": angle,
        "aspect_ratio": aspect_ratio,
        "is_physically_lying": is_lying,
    }


def format_line(stats):
    """把指標壓成一行終端輸出。"""
    if stats["person_count"] == 0:
        return "沒偵測到人"
    if stats["best_idx"] < 0:
        return f"偵測到 {stats['person_count']} 人，但沒有人過 conf 門檻 → 這幀對判斷無用"

    parts = [
        f"{stats['person_count']} 人",
        f"主體 conf={stats['best_conf']:.2f}",
        f"特徵{'有效' if stats['feature_valid'] else '全零(無效)'}",
    ]
    angle = stats["body_angle"]
    parts.append(f"軀幹角={angle:.1f}°" if angle is not None else "軀幹角=無法計算(肩/臀缺點)")
    parts.append(f"w/h={stats['aspect_ratio']:.2f}")
    if stats["is_physically_lying"]:
        parts.append("⚠躺平")
    missing = stats["missing_keypoints"]
    if missing:
        shown = "、".join(missing[:5]) + ("…" if len(missing) > 5 else "")
        parts.append(f"缺{len(missing)}點({shown})")
    return " | ".join(parts)


def summarize(all_stats, label):
    """多幀（影片／資料夾）的統計摘要——單幀看不出的問題要靠比例才看得出來。"""
    total = len(all_stats)
    if total == 0:
        print(f"\n{label}：沒有可分析的畫面")
        return

    detected = [s for s in all_stats if s["person_count"] > 0]
    usable = [s for s in all_stats if s.get("feature_valid")]
    lying = [s for s in all_stats if s.get("is_physically_lying")]
    angles = [s["body_angle"] for s in all_stats if s.get("body_angle") is not None]

    print(f"\n{'=' * 60}")
    print(f"{label} 統計（共 {total} 幀）")
    print(f"{'=' * 60}")
    print(f"  有偵測到人      ：{len(detected):>5} 幀（{len(detected) / total:.1%}）")
    # 這行是重點：真正能餵給 AcT 的比例。跟上一行的差距就是「看得到人但用不上」的損耗
    print(f"  特徵有效可用    ：{len(usable):>5} 幀（{len(usable) / total:.1%}）← 真正能餵給 AcT 的")
    print(f"  判定躺平        ：{len(lying):>5} 幀（{len(lying) / total:.1%}）")
    if angles:
        print(f"  軀幹角可計算    ：{len(angles):>5} 幀（{len(angles) / total:.1%}）"
              f"，範圍 {min(angles):.0f}°~{max(angles):.0f}°")
    else:
        print("  軀幹角可計算    ：    0 幀 ← 肩/臀關鍵點從沒同時抓到，躺平判斷全程失效")

    # 缺點排行：哪個部位最常抓不到，直接指出模型在這個場景的弱點
    missing_counter = {}
    for stats in all_stats:
        for name in stats.get("missing_keypoints", []):
            missing_counter[name] = missing_counter.get(name, 0) + 1
    if missing_counter:
        top = sorted(missing_counter.items(), key=lambda kv: -kv[1])[:5]
        print("  最常缺的關鍵點  ：" + "、".join(f"{n}({c}次)" for n, c in top))


def run_image(model, path, conf_threshold, out_dir, show):
    """單張圖片：印一行指標，存一張標註圖。"""
    result = model(str(path), verbose=False, conf=conf_threshold)[0]
    stats = analyze(result, conf_threshold)
    print(f"[{path.name}] {format_line(stats)}")

    annotated = result.plot(boxes=True, labels=True, conf=conf_threshold)
    if out_dir:
        out_path = out_dir / f"pose_{path.name}"
        cv2.imwrite(str(out_path), annotated)
        print(f"         → {out_path}")
    if show:
        cv2.imshow("pose", annotated)
        cv2.waitKey(0)
    return stats


def run_video(model, path, conf_threshold, out_dir, show, print_every):
    """影片：逐幀分析，存標註影片，最後印統計摘要。"""
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        print(f"⚠️ 開不了影片：{path}")
        return []

    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))

    writer = None
    if out_dir:
        out_path = out_dir / f"pose_{path.stem}.mp4"
        writer = cv2.VideoWriter(
            str(out_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
        )

    all_stats = []
    frame_index = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            result = model(frame, verbose=False, conf=conf_threshold)[0]
            stats = analyze(result, conf_threshold)
            all_stats.append(stats)

            if frame_index % print_every == 0:
                print(f"  第 {frame_index:>4} 幀｜{format_line(stats)}")

            annotated = result.plot(boxes=True, labels=True, conf=conf_threshold)
            if writer:
                writer.write(annotated)
            if show:
                cv2.imshow("pose", annotated)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    print("  （使用者按 q 中斷）")
                    break
            frame_index += 1
    finally:
        capture.release()
        if writer:
            writer.release()

    if out_dir and writer:
        print(f"  → {out_dir / f'pose_{path.stem}.mp4'}")
    return all_stats


def collect_targets(path):
    """把輸入路徑展開成待處理檔案清單（檔案直接用，資料夾掃第一層）。"""
    if path.is_file():
        return [path]
    if not path.is_dir():
        return []
    suffixes = IMAGE_SUFFIXES | VIDEO_SUFFIXES
    return sorted(p for p in path.iterdir() if p.suffix.lower() in suffixes)


def main():
    parser = argparse.ArgumentParser(
        description="本地 pose 辨識效果評估（不經 Triton）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("path", help="圖片／影片檔，或裝著它們的資料夾")
    parser.add_argument("--conf", type=float, default=DEFAULT_CONF,
                        help=f"偵測門檻，預設 {DEFAULT_CONF}（對齊正式管線）")
    parser.add_argument("--weights", default=str(DEFAULT_WEIGHTS), help="pose 權重路徑")
    parser.add_argument("--out", default=str(DEFAULT_OUT_DIR), help="標註結果輸出目錄")
    parser.add_argument("--no-save", action="store_true", help="不存標註檔，只看終端數據")
    parser.add_argument("--show", action="store_true", help="即時顯示視窗（影片按 q 離開）")
    parser.add_argument("--print-every", type=int, default=10,
                        help="影片每幾幀印一行，預設 10")
    args = parser.parse_args()

    target_path = Path(args.path).expanduser()
    if not target_path.exists():
        print(f"❌ 路徑不存在：{target_path}")
        return 1

    weights_path = Path(args.weights)
    if not weights_path.exists():
        print(f"❌ 找不到權重：{weights_path}")
        return 1

    targets = collect_targets(target_path)
    if not targets:
        print(f"❌ 沒有可處理的檔案（支援 {sorted(IMAGE_SUFFIXES | VIDEO_SUFFIXES)}）")
        return 1

    out_dir = None
    if not args.no_save:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)

    device = pick_device()
    print(f"🚀 裝置：{device}｜權重：{weights_path.name}｜conf：{args.conf}")
    print(f"📂 待處理 {len(targets)} 個檔案\n")
    model = YOLO(str(weights_path))
    model.to(device)

    for target in targets:
        suffix = target.suffix.lower()
        if suffix in IMAGE_SUFFIXES:
            run_image(model, target, args.conf, out_dir, args.show)
            continue
        if suffix in VIDEO_SUFFIXES:
            print(f"[{target.name}] 影片分析中…")
            stats = run_video(model, target, args.conf, out_dir, args.show, args.print_every)
            summarize(stats, target.name)
            continue
        print(f"（略過不支援的檔案：{target.name}）")

    if args.show:
        cv2.destroyAllWindows()

    # 資料夾裡全是圖片時，逐張印過了但沒有整體概念，補一份總計
    image_targets = [t for t in targets if t.suffix.lower() in IMAGE_SUFFIXES]
    if len(image_targets) > 1:
        all_stats = [
            analyze(model(str(p), verbose=False, conf=args.conf)[0], args.conf)
            for p in image_targets
        ]
        summarize(all_stats, f"{len(image_targets)} 張圖片整體")

    return 0


if __name__ == "__main__":
    sys.exit(main())
