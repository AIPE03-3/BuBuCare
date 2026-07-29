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
| 34 維特徵 `pose_features.pose_feature()` | 同一個函式 |
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

## 量化評估（需要標註檔）

```bash
# 用人工標註的「真跌倒時間段」算召回率／誤報率／反應延遲
ai/.venv/bin/python ai/local_pipeline_eval.py 影片 --labels 標註檔 --no-show

# 從第 2400 幀（或 --start 2:00）開始播，不用每次從頭看
ai/.venv/bin/python ai/local_pipeline_eval.py 影片 --start 2:00

# 逐幀原始數據存 CSV，可以自己用 Excel 交叉分析
ai/.venv/bin/python ai/local_pipeline_eval.py 影片 --csv out.csv --no-show
```

標註檔格式寬鬆，一行一段或全部黏在一起都可以，解析器用 regex 掃：

```
0:03-0:09  0:13-0:20  0:35-0:42
frame 6380-6450          ← 也接受直接寫幀號
# 井號開頭的行會被忽略
```
"""
import argparse
import csv
import re
import sys
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn as nn
from ultralytics import YOLO

from pose_features import empty_feature, is_feature_valid, pose_feature

_AI_DIR = Path(__file__).resolve().parent
DEFAULT_POSE_WEIGHTS = _AI_DIR / "yolo11s-pose.pt"
DEFAULT_ACT_WEIGHTS = _AI_DIR / "action_transformer.pth"
DEFAULT_OUT_DIR = _AI_DIR / "pose_eval_out"

# 以下常數全部對齊 inference_test.py，改任何一個都會讓結果套不回正式管線
POSE_CONF = 0.45          # :564
WINDOW_SIZE = 30          # :403 deque(maxlen=30)
LYING_ANGLE_DEG = 40.0    # :697
LYING_ASPECT_RATIO = 1.25 # :697
OCCLUDED_HEIGHT_RATIO = 0.50  # :702（2026-07-29 從 0.70 調降，見 docs/2026-07-29-pipeline-false-alarm-fix.md）
AI_THINKING_CONF = 0.35   # :744
DIRECT_TRIGGER_CONF = 0.55  # :749

LEFT_SHOULDER, RIGHT_SHOULDER = 5, 6
LEFT_HIP, RIGHT_HIP = 11, 12

# BGR。與 inference_test.py:767-788 的配色一致，方便跟正式畫面對照
COLOR_FALL = (0, 0, 255)      # 紅
COLOR_NORMAL = (0, 255, 0)    # 綠
COLOR_BUFFER = (0, 255, 255)  # 黃

# 觸發策略。用兩個布林旗標描述差異，而不是寫三份 if/else——三種模式的差別本來就只有
# 這兩個問題的答案，攤成資料表之後 decide_trigger 只需要一份邏輯。
#
#   act_alone          ：幾何完全正常時，AcT 能不能自己決定要報？
#   occluded_needs_act ：OCCLUDED 要不要 AcT 附議才算數？
#                        （現況它是無條件放行，誤判一次就報一次）
# test4.mp4（20 段人工標註真跌倒）實測，三者用同一支影片同一份標註：
#
#   模式         段級召回      幀級誤報   平均延遲
#   current      95.0% (19/20)  56.5%    0.26s
#   geo-first    90.0% (18/20)  12.1%    0.64s   ← 誤報降 4.7 倍，只多漏 1 段
#   geo-strict   65.0% (13/20)   7.1%    0.91s   ← 不要用，理由見下
TRIGGER_MODES = {
    # 2026-07-29 之前的正式管線行為。留著是為了做 A/B 對照，不是預設。
    "current": {"act_alone": True, "occluded_needs_act": False},
    # AcT 不能單獨觸發。誤報主因就是「幾何正常但 AcT 說跌倒」（佔誤報 78.7%），砍掉這條。
    # ✅ 已於 2026-07-29 帶進正式管線（ACT_ALONE_CAN_TRIGGER=false）
    "geo-first": {"act_alone": False, "occluded_needs_act": False},
    # ⚠ 實測失敗的方案，保留是為了記錄「試過、不行」，不要再走一次。
    # 動機是 OCCLUDED 涉及 geo-first 殘餘誤報的 87%（人蹲下/坐下/彎腰/走到家具後面
    # 都會「變矮且偏下」）。但真跌倒時 OCCLUDED 本來就常成立（人倒下被家具擋住），
    # 要求 AcT 附議等於連真跌倒一起砍——換來 5 個百分點的誤報改善，代價是 5 次漏報。
    "geo-strict": {"act_alone": False, "occluded_needs_act": True},
}
DEFAULT_TRIGGER_MODE = "geo-first"  # 對齊正式管線；要重現舊行為請加 --trigger-mode current --occ-height 0.70


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


def parse_time_to_seconds(text):
    """接受 `M:SS`、`MM:SS`、純秒數 `95`。解析不了回 None。"""
    text = str(text).strip()
    match = re.fullmatch(r"(\d+):(\d{1,2})(?:\.(\d+))?", text)
    if match:
        fraction = float(f"0.{match.group(3)}") if match.group(3) else 0.0
        return int(match.group(1)) * 60 + int(match.group(2)) + fraction
    try:
        return float(text)
    except ValueError:
        return None


def parse_label_file(path, fps):
    """讀人工標註的真跌倒時間段，回傳 [(起幀, 迄幀), …]（已排序、已合併重疊）。

    刻意用 regex 掃描整份內容而不是逐行解析：手寫標註常常是「全部黏成一行」或
    分隔符不一致，寬鬆解析省得為了格式來回。支援兩種寫法：
      - `0:03-0:09`     時間（分:秒）
      - `frame 120-360` 直接寫幀號
    `#` 開頭的行視為註解。
    """
    lines = []
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped.startswith("#"):
            lines.append(stripped)
    text = "\n".join(lines)

    segments = []
    for match in re.finditer(r"frame\s+(\d+)\s*[-~]\s*(\d+)", text, re.IGNORECASE):
        segments.append((int(match.group(1)), int(match.group(2))))
    # 時間格式。先把 frame 那種挖掉，免得數字被重複吃進來
    text_without_frames = re.sub(r"frame\s+\d+\s*[-~]\s*\d+", " ", text, flags=re.IGNORECASE)
    for match in re.finditer(r"(\d+:\d{1,2})\s*[-~]\s*(\d+:\d{1,2})", text_without_frames):
        start_sec = parse_time_to_seconds(match.group(1))
        end_sec = parse_time_to_seconds(match.group(2))
        if start_sec is None or end_sec is None:
            continue
        segments.append((int(round(start_sec * fps)), int(round(end_sec * fps))))

    if not segments:
        return []
    # 合併重疊或相鄰的段，避免同一次跌倒被拆成兩段害召回率失真
    segments.sort()
    merged = [list(segments[0])]
    for start, end in segments[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [tuple(seg) for seg in merged]


def in_any_segment(frame_index, segments):
    """該幀是否落在任一標註段內。"""
    return any(start <= frame_index <= end for start, end in segments)


def report_metrics(records, segments, fps, mode=DEFAULT_TRIGGER_MODE):
    """用人工標註算出指標。

    ⚠ **段級召回率單獨看會騙人**，這是本專案實際踩過的坑：
    當系統 63% 的幀都在觸發時，每段跌倒約 30 個處理幀，隨機亂報也幾乎必然命中至少
    一幀——實測「每幀 35% 機率隨機報」的段召回率是 **100%**。所以看到「段召回 95%」
    就下「抓得很準」的結論是錯的（本專案第一版報告就是這樣寫錯的）。

    真正有鑑別力的是**幀級的精確率與 F1，而且要跟 baseline 比**：
      - 精確率：報出來的有多少是真的（決定護理師會不會被吵到關掉系統）
      - 幀召回率：真跌倒的幀有多少被報到
      - F1 對照「永遠報跌倒」的 baseline——贏不了它就代表系統沒有提供資訊
      - 反應延遲：急救場景延遲就是傷害
    """
    print(f"\n{'=' * 60}")
    print(f"量化評估（依標註 {len(segments)} 段真跌倒｜策略 {mode}）")
    print(f"{'=' * 60}")

    triggered_frames = {r["frame"] for r in records if r["triggered"]}

    hit_count = 0
    latencies = []
    print("\n── 每段是否抓到 ──")
    for index, (start, end) in enumerate(segments, 1):
        hits = sorted(f for f in triggered_frames if start <= f <= end)
        time_label = f"{start / fps:>6.1f}s~{end / fps:<6.1f}s"
        if not hits:
            print(f"  {index:>2}. {time_label} ❌ 完全沒報（漏報）")
            continue
        hit_count += 1
        latency = (hits[0] - start) / fps
        latencies.append(latency)
        print(f"  {index:>2}. {time_label} ✅ 首次觸發延遲 {latency:>5.2f} 秒")

    # 只算「有效幀」：視窗沒滿或根本沒看到人的幀，系統本來就不該報，
    # 拿它們當分母會把誤報率洗淡，看起來比實際好。
    evaluable = [r for r in records if r["evaluable"]]
    positives = [r for r in evaluable if in_any_segment(r["frame"], segments)]
    negatives = [r for r in evaluable if not in_any_segment(r["frame"], segments)]
    if not evaluable or not positives:
        print("\n⚠ 沒有可評估的幀（視窗未滿或全程沒看到人），指標略過")
        return

    true_positives = sum(1 for r in positives if r["triggered"])
    false_positives = sum(1 for r in negatives if r["triggered"])
    frame_recall = true_positives / len(positives)
    precision = true_positives / (true_positives + false_positives) if true_positives + false_positives else 0.0
    f1 = 2 * precision * frame_recall / (precision + frame_recall) if precision + frame_recall else 0.0

    # baseline：一個什麼都不判斷、每幀都報跌倒的假系統。它的召回率必然 100%、
    # 精確率等於正樣本比例。真實系統的 F1 若贏不了它，代表它沒有提供任何資訊。
    positive_rate = len(positives) / len(evaluable)
    baseline_f1 = 2 * positive_rate / (positive_rate + 1)

    print("\n── 幀級指標（有鑑別力的看這裡）──")
    print(f"  精確率  ：{precision:6.1%}  ← 報出來的有多少是真跌倒")
    print(f"  幀召回率：{frame_recall:6.1%}  ← 真跌倒的幀有多少被報到")
    print(f"  F1      ：{f1:6.3f}")
    print(f"  ── 對照 baseline（永遠報跌倒的假系統）──")
    print(f"     精確率 {positive_rate:.1%}（＝全片跌倒幀比例）、F1 {baseline_f1:.3f}")
    verdict = "✅ 高於 baseline，系統有判斷力" if f1 > baseline_f1 + 0.05 else \
              "⚠️ 幾乎等於 baseline，系統近乎沒有判斷力"
    print(f"     {verdict}（差距 {f1 - baseline_f1:+.3f}）")
    print(f"  幀級誤報率：{false_positives}/{len(negatives)} "
          f"({false_positives / len(negatives):.1%})" if negatives else "  幀級誤報率：無正常時段")

    print("\n── 段級指標（參考用，不能單獨解讀）──")
    print(f"  段級召回率：{hit_count}/{len(segments)} ({hit_count / len(segments):.1%})"
          f"  ← 漏掉 {len(segments) - hit_count} 次")
    print(f"  ⚠ 觸發率高時這個數字會虛高：實測「每幀 35% 機率隨機亂報」的段召回率是 100%，"
          f"\n     所以它單獨看不能證明系統準，要搭配上面的精確率／F1 一起看")
    if latencies:
        print(f"  平均反應延遲：{sum(latencies) / len(latencies):.2f} 秒"
              f"（最慢 {max(latencies):.2f} 秒）")


def scene_histogram(frame):
    """算一幀的正規化 RGB 直方圖，用來比較相鄰幀的畫面差異。"""
    small = cv2.resize(frame, (64, 48))
    hist = cv2.calcHist([small], [0, 1, 2], None, [8, 8, 8], [0, 256] * 3).flatten()
    total = hist.sum()
    return hist / total if total else hist


def is_scene_cut(current_hist, previous_hist, threshold):
    """直方圖交集低於門檻 → 判定畫面已切換。

    ⚠️ **這是評估用的補償手段，不要搬進 inference_test.py。**

    用途：test4.mp4 這類剪接素材，AcT 的 30 幀視窗會跨越剪接點，讓「上一段的姿態」
    污染「下一段的判斷」（實測剪接後 3 秒內誤報率 68.6%，區外 54.1%）。

    ⚠️ **`--cut-handling reset`（清空視窗）實測是壞主意**，用 exclude 不要用 reset：
    清空後要 30 個處理幀（3 秒）才能重新填滿，這期間 AcT 完全不作用；而剪接點就在
    每段跌倒之前，等於把「跌倒剛發生」的那 3 秒判斷能力砍掉。實測 F1 反而變差：
    current 0.542→0.465、geo-first 0.625→0.460。誤報是降了，真跌倒也一起漏了。
    正確做法是 `exclude`——把污染幀排除在指標之外，不去干預判斷本身。

    為什麼不能上正式管線：真實 RTSP 沒有剪接點，但有一堆會造成直方圖劇變的正常事件
    ——攝影機切換夜視/日視（IR filter）、關燈、有人走近遮住鏡頭、掉包後畫面跳躍。
    每誤判一次就清空視窗，代價是「AcT 有 3 秒完全不作用」的防護空窗；若剛好在切夜視
    的瞬間有人跌倒就是漏報。test4 自己就同時有夜視與彩色兩種成像，可見這不是假設。

    正式管線 :480 的 frame_window.clear() 是由**斷線重連**這個明確事件觸發的，
    不是靠猜畫面內容——有訊號可依據，才不會誤判。兩者性質完全不同。
    """
    return float(1.0 - np.minimum(current_hist, previous_hist).sum()) > threshold


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


def extract_pose_state(result, normal_height_reference, image_height,
                       occluded_height_ratio=OCCLUDED_HEIGHT_RATIO):
    """從一幀 pose 結果抽出：34 維特徵、躺平旗標、遮擋旗標、身高參考值。

    回傳 dict。沒有可用的人時 `feature` 為全零向量（等同正式管線的無效幀）。
    """
    state = {
        "feature": empty_feature(),
        "valid": False,
        "is_lying": False,
        "is_occluded": False,
        "body_angle": None,
        "aspect_ratio": 0.0,
        "person_count": 0,
        "best_conf": 0.0,
        "height_reference": normal_height_reference,
        # 遮擋判斷的兩個原始輸入，留著讓離線掃描重算門檻用
        "height_ratio": None,
        "y2_ratio": 0.0,
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
    feature = pose_feature(keypoints)
    state["best_conf"] = float(boxes_conf[best_idx])
    if is_feature_valid(feature):
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
        # 原始數值一併留下，讓離線掃描能重算不同門檻，不必為了試一個參數就重跑推論
        state["height_ratio"] = float(box_height / normal_height_reference)
        state["y2_ratio"] = float(y2 / image_height) if image_height else 0.0
        if state["height_ratio"] < occluded_height_ratio and state["y2_ratio"] > 0.5:
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


def decide_trigger(pose_state, window_len, pred_class, act_confidence, has_seen_person,
                   mode=DEFAULT_TRIGGER_MODE):
    """觸發條件。`mode="current"` 與正式管線 :744-749 完全等價。

    回傳 (should_trigger, is_ai_thinking_fall)。
    """
    rules = TRIGGER_MODES[mode]
    window_full = window_len == WINDOW_SIZE
    is_ai_thinking_fall = window_full and pred_class == 0 and act_confidence > AI_THINKING_CONF
    if not has_seen_person:
        return False, is_ai_thinking_fall

    if pose_state["is_lying"] or pose_state["is_occluded"]:
        # 視窗還沒滿就先報：跌倒是急救場景，不能等湊滿 30 幀。三種模式都保留這條安全網
        if not window_full:
            return True, is_ai_thinking_fall
        if is_ai_thinking_fall:
            return True, is_ai_thinking_fall
        # OCCLUDED 的無條件放行：geo-strict 把它收掉，其餘模式維持現況
        if pose_state["is_occluded"] and not rules["occluded_needs_act"]:
            return True, is_ai_thinking_fall
        return False, is_ai_thinking_fall

    # 幾何沒事，只有 AcT 說跌倒
    if rules["act_alone"] and window_full and pred_class == 0 and act_confidence > DIRECT_TRIGGER_CONF:
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

    # 右上角時間戳＋幀號：標註真跌倒時段時，暫停後直接抄這裡的數字
    stamp = f"frame {info['frame']} | {info['timestamp']}"
    (stamp_w, _), _ = cv2.getTextSize(stamp, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
    cv2.putText(frame, stamp, (width - stamp_w - 20, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    # 有標註檔時，落在真跌倒時段的幀在時間戳下方標 GT，肉眼即可比對系統判斷對不對
    if info.get("in_truth_segment"):
        cv2.putText(frame, "GT: FALL", (width - stamp_w - 20, 68),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 215, 255), 2, cv2.LINE_AA)

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
    parser.add_argument("--start", default=None,
                        help="從指定位置開始播，接受 2:00（時間）或 2400（幀號）")
    parser.add_argument("--labels", default=None,
                        help="人工標註的真跌倒時間段檔案，給了才算召回率／誤報率")
    parser.add_argument("--csv", default=None,
                        help="逐幀原始數據輸出成 CSV，方便自己交叉分析")
    parser.add_argument("--cut-handling", default="none",
                        choices=["none", "exclude", "reset"],
                        help="剪接素材的處理方式：none=不處理／"
                             "exclude=把剪接後 3 秒的幀排除在指標外（建議）／"
                             "reset=清空 AcT 視窗（實測會讓 F1 變差，見 is_scene_cut docstring）")
    parser.add_argument("--reset-on-cut", action="store_true",
                        help="等同 --cut-handling reset（保留舊名稱）")
    parser.add_argument("--cut-threshold", type=float, default=0.45,
                        help="畫面切換的直方圖差異門檻，預設 0.45")
    parser.add_argument("--trigger-mode", default=DEFAULT_TRIGGER_MODE,
                        choices=sorted(TRIGGER_MODES),
                        help="觸發策略：current=正式管線現況／"
                             "geo-first=AcT 不能單獨觸發／geo-strict=OCCLUDED 也要 AcT 附議")
    parser.add_argument("--occ-height", type=float, default=OCCLUDED_HEIGHT_RATIO,
                        help=f"遮擋判斷的高度門檻，預設 {OCCLUDED_HEIGHT_RATIO}（＝正式管線現況）；"
                             f"實測 0.50 可把彎腰／坐下的誤報砍掉一半")
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
    # 把「現在跑的是哪一組設定」印在最前面。手動測時最容易踩的坑就是不知道自己
    # 跑的是哪一組，看到誤報就以為改善無效。
    matches_production = (args.trigger_mode == DEFAULT_TRIGGER_MODE
                          and args.occ_height == OCCLUDED_HEIGHT_RATIO)
    print(f"🚀 裝置：{device}")
    print(f"⚙️  策略 {args.trigger_mode}｜遮擋高度門檻 {args.occ_height}"
          f"　←　{'＝正式管線現況' if matches_production else '⚠ 與正式管線不同（自訂對照組）'}")
    print(f"📦 載入 pose：{pose_path.name}｜AcT：{act_path.name}")
    pose_model = YOLO(str(pose_path))
    pose_model.to(device)
    act_model = load_act_model(act_path, device)
    print(f"🎚  觸發策略：{args.trigger_mode}"
          f"（AcT 可單獨觸發={TRIGGER_MODES[args.trigger_mode]['act_alone']}，"
          f"OCCLUDED 需 AcT 附議={TRIGGER_MODES[args.trigger_mode]['occluded_needs_act']}）")
    print("🔥 兩顆模型就緒（rt_detr 那條防線本地不跑，見檔頭說明）")
    print("▶️  播放中：q 離開、空白鍵暫停／繼續\n")

    source_fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    frame_delay = 1.0 / (source_fps * max(args.speed, 0.01))

    segments = []
    if args.labels:
        segments = parse_label_file(args.labels, source_fps)
        if not segments:
            print(f"⚠️ 標註檔解析不到任何時間段：{args.labels}")
        else:
            covered = sum(end - start for start, end in segments) / source_fps
            print(f"🏷  標註 {len(segments)} 段真跌倒，共 {covered:.0f} 秒")

    start_frame = 0
    if args.start:
        seconds = parse_time_to_seconds(args.start)
        if seconds is None:
            print(f"❌ 看不懂 --start 的值：{args.start}")
            return 1
        # 帶冒號一律當時間，純數字當幀號（6.2 分鐘的片子，2400 一定是幀不是秒）
        start_frame = int(round(seconds * source_fps)) if ":" in str(args.start) else int(seconds)
        capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        print(f"⏩ 從第 {start_frame} 幀（{start_frame / source_fps:.1f} 秒）開始")

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
    frame_count = start_frame
    processed_count = 0
    records = []
    has_seen_person = False
    ever_detected_fall = False
    normal_height_reference = None
    trigger_count = 0
    fps_value = 0.0
    paused = False
    previous_hist = None
    cut_count = 0
    last_cut_frame = None
    cut_handling = "reset" if args.reset_on_cut else args.cut_handling
    # 剪接後多久內的幀算被污染：AcT 視窗 30 個處理幀，跳幀時對應原始幀要 ×2
    cut_pollution_span = WINDOW_SIZE * (1 if args.no_skip else 2)

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

            # 畫面切換偵測。只在剪接素材上開，理由見 is_scene_cut()。
            if cut_handling != "none":
                current_hist = scene_histogram(frame)
                if previous_hist is not None and is_scene_cut(current_hist, previous_hist,
                                                              args.cut_threshold):
                    cut_count += 1
                    last_cut_frame = frame_count
                    if cut_handling == "reset":
                        frame_window.clear()
                        # 身高基準也一起重置：新場景的人距離鏡頭可能完全不同，
                        # 沿用舊基準會讓遮擋判斷（h/normal_h）整段失準
                        normal_height_reference = None
                previous_hist = current_hist

            image_height = frame.shape[0]
            result = pose_model(frame, verbose=False, conf=args.conf)[0]
            pose_state = extract_pose_state(result, normal_height_reference, image_height,
                                            args.occ_height)

            # 身高基準取前期幾幀，之後拿來判斷「突然變矮」（遮擋防線的分母）。
            # 正式管線用 10<frame_count<40 的原始幀號（:689），跳幀後約等於第 5~20 個處理幀。
            # 這裡改用處理幀計數：--start 跳著播時原始幀號早就超過 40，用它會永遠取不到基準。
            if normal_height_reference is None and 5 <= processed_count <= 20 and pose_state["valid"]:
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
                pose_state, len(frame_window), pred_class, act_confidence, has_seen_person,
                mode=args.trigger_mode,
            )
            if should_trigger:
                trigger_count += 1
                if not ever_detected_fall:
                    print(f"🚨 第 {frame_count} 幀觸發跌倒｜AcT conf={act_confidence:.2f}"
                          f"｜lying={pose_state['is_lying']}｜occluded={pose_state['is_occluded']}")
                ever_detected_fall = True

            # 逐幀留底給指標計算與 CSV。evaluable＝視窗滿且看過人，
            # 也就是「系統本來就該有能力判斷」的幀；誤報率只拿這種幀當分母才誠實。
            records.append({
                "frame": frame_count,
                "time_s": round(frame_count / source_fps, 2),
                "triggered": should_trigger,
                # exclude 模式：剪接後 3 秒內視窗仍混著上一段的姿態，這種幀的判斷
                # 結果不能代表系統能力，排除在指標之外（比清空視窗誠實——清空會製造
                # 一段 AcT 完全不作用的空窗，反而砍掉真跌倒，實測 F1 更差）
                "evaluable": (len(frame_window) == WINDOW_SIZE and has_seen_person
                              and not (cut_handling == "exclude" and last_cut_frame is not None
                                       and frame_count - last_cut_frame <= cut_pollution_span)),
                "act_fall": pred_class == 0,
                "act_conf": round(act_confidence, 4),
                "lying": pose_state["is_lying"],
                "occluded": pose_state["is_occluded"],
                "feature_valid": pose_state["valid"],
                "person_count": pose_state["person_count"],
                "pose_conf": round(pose_state["best_conf"], 4),
                "body_angle": round(pose_state["body_angle"], 1) if pose_state["body_angle"] is not None else "",
                "aspect_ratio": round(pose_state["aspect_ratio"], 3),
            })

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
                "frame": frame_count,
                "timestamp": f"{int(frame_count / source_fps) // 60:02d}:"
                             f"{int(frame_count / source_fps) % 60:02d}",
                "in_truth_segment": in_any_segment(frame_count, segments) if segments else False,
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
    print(f"讀取到第 {frame_count} 幀，實際處理 {processed_count} 幀")
    print(f"觸發跌倒 {trigger_count} 次｜曾偵測到人：{'是' if has_seen_person else '否'}")
    if cut_handling != "none":
        action = "清空 AcT 視窗" if cut_handling == "reset" else "把後續 3 秒的幀排除在指標外"
        print(f"偵測到畫面切換 {cut_count} 次，每次都{action}")
    if normal_height_reference:
        print(f"身高基準（遮擋判斷用）：{normal_height_reference:.0f} px")
    if writer:
        print(f"→ 已存標註影片到 {args.out}")

    if args.csv and records:
        csv_path = Path(args.csv)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer_csv = csv.DictWriter(handle, fieldnames=list(records[0].keys()))
            writer_csv.writeheader()
            writer_csv.writerows(records)
        print(f"→ 逐幀數據已存 {csv_path}（{len(records)} 列）")

    if segments and records:
        report_metrics(records, segments, source_fps, args.trigger_mode)
    return 0


if __name__ == "__main__":
    sys.exit(main())
