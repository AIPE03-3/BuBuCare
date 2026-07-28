"""本地跑完整跌倒判斷鏈：yolo11s-pose → 34 維特徵 → 30 幀視窗 → AcT，即時看畫面。

## 跟 local_pose_eval.py 的差別

`local_pose_eval.py` 只到 pose 為止，看的是「輸入品質」。
這支接上 **AcT 時序模型**，跑完整條判斷鏈，看的是「**最後判不判得出跌倒**」。

## 為什麼本地跑得起來

正式管線把 AcT 搬上 Triton（`triton_act_client.py`），但 `ai/action_transformer.pth`
是純 PyTorch state_dict，模型架構就寫在 `inference_test.py:299-311`——本地直接建同一個
架構載進去即可，不需要 Triton。pose 則用 `yolo11s-pose.pt`。

（rt_detr 那顆才是真的本地跑不動：Triton 上是 Blackwell 專屬 `.plan`。故本支**不含**
依賴 detr 的那幾條防線：離床、座椅滑落、環境巡檢。只跑 pose + AcT 主鏈。）

## 判斷邏輯逐項對齊正式管線

| 這裡 | 正式管線 |
|---|---|
| `conf=0.45` | `inference_test.py:564` |
| 跳幀 `frame_count % 2` | `:536` |
| 選人 `conf × 框面積` | `:672-678` |
| 34 維特徵 `kp[:17,:2].flatten()` | `:682` |
| 躺平 `角度<40°` 或 `w/h>1.25` | `:697` |
| 遮擋 `h/normal_h<0.70` 且 `y2>img_h/2` | `:702` |
| 視窗 30 幀、`softmax`/`argmax` | `:718-733` |
| 觸發條件三選一 | `:744-749` |

所以這裡看到的判斷結果，跟正式管線在同一支影片上會是一樣的。

## 用法

```bash
# 影片檔
ai/.venv/bin/python ai/local_pipeline_eval.py ai/test_demo/test1.mp4

# 電腦攝影機（自己站起來坐下、假裝跌倒試試）
ai/.venv/bin/python ai/local_pipeline_eval.py 0

# 觸發後不要永久鎖在 FALL（反覆測比較方便）
ai/.venv/bin/python ai/local_pipeline_eval.py 0 --no-latch

# 存一份標註影片
ai/.venv/bin/python ai/local_pipeline_eval.py 影片路徑 --save
```

播放中按 **q** 離開、**空白鍵** 暫停／繼續。
"""
import argparse
import sys
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn as nn
from ultralytics import YOLO

_AI_DIR = Path(__file__).resolve().parent
DEFAULT_POSE_WEIGHTS = _AI_DIR / "yolo11s-pose.pt"
DEFAULT_ACT_WEIGHTS = _AI_DIR / "action_transformer.pth"
DEFAULT_OUT_DIR = _AI_DIR / "pose_eval_out"

# 以下常數全部對齊 inference_test.py，改任何一個都會讓結果套不回正式管線
POSE_CONF = 0.45          # :564
WINDOW_SIZE = 30          # :403 deque(maxlen=30)
LYING_ANGLE_DEG = 40.0    # :697
LYING_ASPECT_RATIO = 1.25 # :697
OCCLUDED_HEIGHT_RATIO = 0.70  # :702
AI_THINKING_CONF = 0.35   # :744
DIRECT_TRIGGER_CONF = 0.55  # :749

LEFT_SHOULDER, RIGHT_SHOULDER = 5, 6
LEFT_HIP, RIGHT_HIP = 11, 12

# BGR。與 inference_test.py:767-788 的配色一致，方便跟正式畫面對照
COLOR_FALL = (0, 0, 255)      # 紅
COLOR_NORMAL = (0, 255, 0)    # 綠
COLOR_BUFFER = (0, 255, 255)  # 黃


class ActionTransformer(nn.Module):
    """時序跌倒分類器。

    ⚠ 架構必須與 `inference_test.py:299-311` **完全一致**，否則 state_dict 載不進來
    （也代表跟 Triton 上 serving 的那顆不是同一個東西，測出來的結論沒有意義）。
    改架構要兩邊一起改。
    """

    def __init__(self, input_dim=34, seq_len=30, num_classes=2):
        super().__init__()
        self.embedding = nn.Linear(input_dim, 64)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=64, nhead=4, dim_feedforward=128, batch_first=True
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=2)
        self.fc = nn.Sequential(nn.Linear(64, 32), nn.ReLU(), nn.Linear(32, num_classes))

    def forward(self, x):
        x = self.embedding(x)
        x = self.transformer(x)
        return self.fc(x.mean(dim=1))


def pick_device():
    """Mac 用 MPS、有 CUDA 用 CUDA、都沒有退 CPU（同 inference_test.py:48）。"""
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def load_act_model(weights_path, device):
    """載入 AcT。權重是 state_dict，故要先建架構再灌權重。"""
    model = ActionTransformer(input_dim=34, seq_len=WINDOW_SIZE, num_classes=2)
    state = torch.load(str(weights_path), map_location="cpu", weights_only=False)
    model.load_state_dict(state)
    model.to(device).eval()
    return model


def select_main_person(boxes_conf, boxes_xywh):
    """正式管線的選人規則：過 conf 門檻者中，`conf × 框面積`最大的那個（:672-678）。

    不是「取信心最高」——面積納入考量是為了偏好近處的人，遠方路過的訪客不該蓋掉住民。
    """
    best_idx, max_score = -1, -1.0
    for idx in range(len(boxes_xywh)):
        if idx >= len(boxes_conf) or boxes_conf[idx] < POSE_CONF:
            continue
        _, _, width, height = boxes_xywh[idx]
        score = boxes_conf[idx] * (width * height)
        if score > max_score:
            max_score, best_idx = score, idx
    return best_idx


def extract_pose_state(result, normal_height_reference, image_height):
    """從一幀 pose 結果抽出：34 維特徵、躺平旗標、遮擋旗標、身高參考值。

    回傳 dict。沒有可用的人時 `feature` 為全零向量（等同正式管線的無效幀）。
    """
    state = {
        "feature": np.zeros(34, dtype=np.float32),
        "valid": False,
        "is_lying": False,
        "is_occluded": False,
        "body_angle": None,
        "aspect_ratio": 0.0,
        "person_count": 0,
        "best_conf": 0.0,
        "height_reference": normal_height_reference,
    }
    if result.keypoints is None or result.boxes is None or len(result.boxes) == 0:
        return state

    keypoints_all = result.keypoints.xyn.cpu().numpy()
    boxes_conf = result.boxes.conf.cpu().numpy()
    boxes_xywh = result.boxes.xywh.cpu().numpy()
    boxes_xyxy = result.boxes.xyxy.cpu().numpy()
    state["person_count"] = len(boxes_conf)
    if keypoints_all.ndim != 3 or keypoints_all.shape[0] == 0:
        return state

    best_idx = select_main_person(boxes_conf, boxes_xywh)
    if best_idx < 0:
        return state

    keypoints = keypoints_all[best_idx]
    feature = keypoints[:17, :2].flatten().astype(np.float32)
    state["best_conf"] = float(boxes_conf[best_idx])
    # 全零＝關鍵點全沒抓到，餵給 AcT 也是廢的（對齊 :683 的 np.all(...==0) 檢查）
    if not np.all(feature == 0):
        state["feature"] = feature
        state["valid"] = True

    _, _, box_width, box_height = boxes_xywh[best_idx]
    _, _, _, y2 = boxes_xyxy[best_idx]
    aspect_ratio = float(box_width / box_height) if box_height else 0.0
    state["aspect_ratio"] = aspect_ratio

    # 躺平判斷（防線 A，:693-697）
    shoulder_x = (keypoints[LEFT_SHOULDER][0] + keypoints[RIGHT_SHOULDER][0]) / 2.0
    shoulder_y = (keypoints[LEFT_SHOULDER][1] + keypoints[RIGHT_SHOULDER][1]) / 2.0
    hip_x = (keypoints[LEFT_HIP][0] + keypoints[RIGHT_HIP][0]) / 2.0
    hip_y = (keypoints[LEFT_HIP][1] + keypoints[RIGHT_HIP][1]) / 2.0
    if shoulder_x != 0 and hip_x != 0:  # xyn 為 0 代表該點沒抓到
        angle = float(np.abs(np.degrees(np.arctan2(hip_y - shoulder_y, hip_x - shoulder_x))))
        state["body_angle"] = angle
        if angle < LYING_ANGLE_DEG:
            state["is_lying"] = True
    if aspect_ratio > LYING_ASPECT_RATIO:
        state["is_lying"] = True

    # 遮擋判斷（防線 B，:701-702）：人突然「變矮」且位置偏下 → 可能倒在遮蔽物後面
    if normal_height_reference is not None:
        if (box_height / normal_height_reference) < OCCLUDED_HEIGHT_RATIO and y2 > (image_height * 0.5):
            state["is_occluded"] = True

    return state


def run_act(act_model, window, device):
    """30 幀視窗 → AcT → (pred_class, confidence)。index 0=跌倒、1=正常。"""
    window_array = np.array(window, dtype=np.float32).reshape(1, WINDOW_SIZE, 34)
    with torch.no_grad():
        logits = act_model(torch.from_numpy(window_array).to(device))
        prob = torch.softmax(logits, dim=1)
        pred_class = int(torch.argmax(prob, dim=1).item())
        confidence = float(prob[0][pred_class].item())
    return pred_class, confidence


def decide_trigger(pose_state, window_len, pred_class, act_confidence, has_seen_person):
    """觸發條件，對齊 :744-749。回傳 (should_trigger, is_ai_thinking_fall)。"""
    window_full = window_len == WINDOW_SIZE
    is_ai_thinking_fall = window_full and pred_class == 0 and act_confidence > AI_THINKING_CONF
    if not has_seen_person:
        return False, is_ai_thinking_fall

    # 幾何先行：躺平或疑似遮擋時，視窗還沒滿也先報（急救場景不等 30 幀）
    if pose_state["is_lying"] or pose_state["is_occluded"]:
        if not window_full or is_ai_thinking_fall or pose_state["is_occluded"]:
            return True, is_ai_thinking_fall
        return False, is_ai_thinking_fall

    # 幾何沒事，但 AcT 高信心認為跌倒 → 也報
    if window_full and pred_class == 0 and act_confidence > DIRECT_TRIGGER_CONF:
        return True, is_ai_thinking_fall
    return False, is_ai_thinking_fall


def draw_overlay(frame, info):
    """把判斷過程畫到畫面上——這支的重點就是「看得到偵測框怎麼變」。"""
    height, width = frame.shape[:2]
    color = info["color"]

    if info["draw_border"]:
        cv2.rectangle(frame, (0, 0), (width, height), color, 12)

    cv2.putText(frame, info["status_text"], (40, 60),
                cv2.FONT_HERSHEY_SIMPLEX, 1.2, color, 3, cv2.LINE_AA)

    # 左下角逐行列出判斷依據，一眼看出「為什麼是這個結論」
    lines = [
        f"AcT: {info['act_label']}  conf={info['act_confidence']:.2f}",
        f"window {info['window_len']}/{WINDOW_SIZE}   person={info['person_count']}"
        f"   pose_conf={info['best_conf']:.2f}",
        f"angle={info['angle_text']}  w/h={info['aspect_ratio']:.2f}"
        f"{'  [LYING]' if info['is_lying'] else ''}"
        f"{'  [OCCLUDED]' if info['is_occluded'] else ''}",
        f"feature={'ok' if info['feature_valid'] else 'ZERO(useless)'}"
        f"   fps={info['fps']:.1f}",
    ]
    for i, text in enumerate(reversed(lines)):
        cv2.putText(frame, text, (40, height - 30 - i * 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
    return frame


def open_source(source):
    """影片檔或攝影機索引。回傳 (capture, 是否為攝影機)。"""
    if str(source).isdigit():
        return cv2.VideoCapture(int(source)), True
    return cv2.VideoCapture(str(source)), False


def main():
    parser = argparse.ArgumentParser(description="本地跑 pose + AcT 完整跌倒判斷鏈（即時畫面）")
    parser.add_argument("source", help="影片檔路徑，或攝影機索引（例如 0）")
    parser.add_argument("--conf", type=float, default=POSE_CONF,
                        help=f"pose 偵測門檻，預設 {POSE_CONF}（對齊正式管線）")
    parser.add_argument("--pose-weights", default=str(DEFAULT_POSE_WEIGHTS))
    parser.add_argument("--act-weights", default=str(DEFAULT_ACT_WEIGHTS))
    parser.add_argument("--save", action="store_true", help="另存一份標註影片")
    parser.add_argument("--out", default=str(DEFAULT_OUT_DIR), help="存檔目錄")
    parser.add_argument("--no-skip", action="store_true",
                        help="不跳幀（正式管線是每 2 幀處理 1 幀）")
    parser.add_argument("--no-latch", action="store_true",
                        help="觸發後不永久鎖在 FALL（正式管線會鎖，反覆測時建議開）")
    parser.add_argument("--speed", type=float, default=1.0,
                        help="播放速度倍率，預設 1.0（貼齊原始 fps）")
    parser.add_argument("--no-show", action="store_true",
                        help="不開視窗，只印判斷結果（無 GUI 的環境或只想存檔時用）")
    parser.add_argument("--print-every", type=int, default=10,
                        help="--no-show 時每幾個處理幀印一行，預設 10")
    args = parser.parse_args()

    pose_path, act_path = Path(args.pose_weights), Path(args.act_weights)
    for path, name in ((pose_path, "pose 權重"), (act_path, "AcT 權重")):
        if not path.exists():
            print(f"❌ 找不到{name}：{path}")
            return 1

    capture, is_camera = open_source(args.source)
    if not capture.isOpened():
        print(f"❌ 開不了來源：{args.source}")
        return 1

    device = pick_device()
    print(f"🚀 裝置：{device}")
    print(f"📦 載入 pose：{pose_path.name}｜AcT：{act_path.name}")
    pose_model = YOLO(str(pose_path))
    pose_model.to(device)
    act_model = load_act_model(act_path, device)
    print("🔥 兩顆模型就緒（rt_detr 那條防線本地不跑，見檔頭說明）")
    print("▶️  播放中：q 離開、空白鍵暫停／繼續\n")

    source_fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    frame_delay = 1.0 / (source_fps * max(args.speed, 0.01))

    writer = None
    if args.save:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = "camera" if is_camera else Path(args.source).stem
        out_path = out_dir / f"pipeline_{stem}.mp4"
        writer = cv2.VideoWriter(
            str(out_path), cv2.VideoWriter_fourcc(*"mp4v"), source_fps,
            (int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
             int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))),
        )

    frame_window = deque(maxlen=WINDOW_SIZE)
    frame_count = 0
    processed_count = 0
    has_seen_person = False
    ever_detected_fall = False
    normal_height_reference = None
    trigger_count = 0
    fps_value = 0.0
    paused = False

    try:
        while True:
            if paused:
                key = cv2.waitKey(50) & 0xFF
                if key == ord("q"):
                    break
                if key == ord(" "):
                    paused = False
                continue

            loop_start = time.time()
            ok, frame = capture.read()
            if not ok:
                break
            frame_count += 1
            # 跳幀（:536）。省一半算力，AcT 的 30 幀視窗因此涵蓋約 2 秒實際時間
            if not args.no_skip and frame_count % 2 != 0:
                continue

            image_height = frame.shape[0]
            result = pose_model(frame, verbose=False, conf=args.conf)[0]
            pose_state = extract_pose_state(result, normal_height_reference, image_height)

            # 身高基準取前期幾幀（:689 用 10<frame_count<40），之後拿來判斷「突然變矮」
            if normal_height_reference is None and 10 < frame_count < 40 and pose_state["valid"]:
                if result.boxes is not None and len(result.boxes) > 0:
                    best_idx = select_main_person(
                        result.boxes.conf.cpu().numpy(), result.boxes.xywh.cpu().numpy()
                    )
                    if best_idx >= 0:
                        normal_height_reference = float(result.boxes.xywh.cpu().numpy()[best_idx][3])

            if pose_state["valid"]:
                has_seen_person = True
            frame_window.append(pose_state["feature"])

            pred_class, act_confidence = 1, 0.0
            if len(frame_window) == WINDOW_SIZE:
                pred_class, act_confidence = run_act(act_model, frame_window, device)

            should_trigger, _ = decide_trigger(
                pose_state, len(frame_window), pred_class, act_confidence, has_seen_person
            )
            if should_trigger:
                trigger_count += 1
                if not ever_detected_fall:
                    print(f"🚨 第 {frame_count} 幀觸發跌倒｜AcT conf={act_confidence:.2f}"
                          f"｜lying={pose_state['is_lying']}｜occluded={pose_state['is_occluded']}")
                ever_detected_fall = True

            # 顯示用的鎖存：正式管線觸發後永久停在 FALL（ever_detected_fall），
            # --no-latch 讓它只在當幀觸發時才紅，反覆測比較方便
            latched_fall = ever_detected_fall and not args.no_latch
            if should_trigger or latched_fall:
                status_text, color, draw_border = "FALL DETECTED!", COLOR_FALL, True
            elif len(frame_window) < WINDOW_SIZE:
                status_text, color, draw_border = "Buffering...", COLOR_BUFFER, False
            else:
                status_text, color, draw_border = "Normal", COLOR_NORMAL, True

            processed_count += 1
            elapsed = time.time() - loop_start
            if elapsed > 0:
                fps_value = 1.0 / elapsed

            annotated = result.plot(boxes=True, labels=True, conf=args.conf)
            angle = pose_state["body_angle"]
            annotated = draw_overlay(annotated, {
                "status_text": status_text,
                "color": color,
                "draw_border": draw_border,
                "act_label": "FALL" if pred_class == 0 else "normal",
                "act_confidence": act_confidence,
                "window_len": len(frame_window),
                "person_count": pose_state["person_count"],
                "best_conf": pose_state["best_conf"],
                "angle_text": f"{angle:.0f}deg" if angle is not None else "n/a",
                "aspect_ratio": pose_state["aspect_ratio"],
                "is_lying": pose_state["is_lying"],
                "is_occluded": pose_state["is_occluded"],
                "feature_valid": pose_state["valid"],
                "fps": fps_value,
            })

            if writer:
                writer.write(annotated)

            if args.no_show:
                # 無視窗模式：定期印一行，讓終端也看得出判斷在怎麼變
                if processed_count % args.print_every == 0:
                    print(f"  第 {frame_count:>4} 幀｜{status_text:<16}"
                          f"｜AcT {'FALL' if pred_class == 0 else 'normal'} {act_confidence:.2f}"
                          f"｜window {len(frame_window)}/{WINDOW_SIZE}"
                          f"｜angle {f'{angle:.0f}' if angle is not None else 'n/a'}"
                          f"｜w/h {pose_state['aspect_ratio']:.2f}"
                          f"{' [LYING]' if pose_state['is_lying'] else ''}")
                continue

            cv2.imshow("pose + AcT", annotated)

            # 節流貼齊原始 fps，讓畫面是正常速度而不是「跑多快播多快」
            wait_ms = 1
            if not is_camera:
                remain = frame_delay * (1 if args.no_skip else 2) - (time.time() - loop_start)
                wait_ms = max(1, int(remain * 1000))
            key = cv2.waitKey(wait_ms) & 0xFF
            if key == ord("q"):
                break
            if key == ord(" "):
                paused = True
    finally:
        capture.release()
        if writer:
            writer.release()
        cv2.destroyAllWindows()

    print(f"\n{'=' * 56}")
    print(f"讀取 {frame_count} 幀，實際處理 {processed_count} 幀")
    print(f"觸發跌倒 {trigger_count} 次｜曾偵測到人：{'是' if has_seen_person else '否'}")
    if normal_height_reference:
        print(f"身高基準（遮擋判斷用）：{normal_height_reference:.0f} px")
    if writer:
        print(f"→ 已存標註影片到 {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
