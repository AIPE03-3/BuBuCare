"""掃描遮擋判斷的參數，找出「擋掉彎腰誤報、又不漏掉跌倒」的最佳組合。

## 要解決的問題

現行遮擋判斷只看當下這一幀，**立即觸發**：

    if (h_box / normal_h) < 0.70 and y2 > img_h * 0.5:
        is_occluded = True

它分不出三種「變矮」：撿東西（1~2 秒就恢復）、坐下（穩定在椅子高度）、
跌倒（持續不恢復且掉更低）。實測撿東西 4/5、坐下 2/2 誤報，全走這條。

但這條規則同時也是重要的召回來源（FallLeftS5 就是靠它報出來的），
所以不能直接砍掉——`geo-strict`（要求 AcT 附議）已經試過，跌倒幀召回崩到 9.2%。

## 這支怎麼找答案

兩個旋鈕一起掃：

  height_ratio 門檻：要「矮到什麼程度」才算（現況 0.70）
  confirm_frames  ：要「持續幾個處理幀」才算（現況 1＝立即）

每支影片只推論一次，兩個參數都在離線階段套用，所以掃 30 種組合的成本
跟跑 1 種一樣。

## 用法

```bash
ai/.venv/bin/python ai/tune_occlusion.py
ai/.venv/bin/python ai/tune_occlusion.py --mode geo-first
```
"""
import argparse
import sys
from pathlib import Path

from ultralytics import YOLO

from batch_eval import classify_video, run_inference
from local_pipeline_eval import (
    AI_THINKING_CONF, DEFAULT_ACT_WEIGHTS, DEFAULT_POSE_WEIGHTS, DIRECT_TRIGGER_CONF,
    POSE_CONF, TRIGGER_MODES, WINDOW_SIZE, load_act_model, pick_device,
)

# 掃描範圍。現況＝(0.70, 1)：矮到 70% 以下、且不需要持續就立即觸發
HEIGHT_RATIOS = [0.70, 0.60, 0.50, 0.40]
CONFIRM_FRAMES = [1, 3, 5, 8, 12, 16]

# 「這支跌倒片算有抓到」的門檻：幀召回要達到這個比例。
#
# ⚠ 不能用「有報過任何一幀」當標準——這個專案已經被同一個錯誤坑過三次
# （段級召回率虛高、geo-strict 的『抓到 4/4』假象、本檔第一版的挑選規則）。
# FallForwardS2 在現況下幀召回只有 3.8%（123 幀裡報 4~5 幀），實務上等同漏報，
# 但用「報過就算」的標準它會被計為成功，進而讓所有更嚴格的參數組合被淘汰。
#
# 15% 的依據：真跌倒後人會持續躺著，系統理應在該片段的相當比例上持續示警；
# 低於這個數字代表只是零星閃現，訊號可能還沒送出去人就已經躺很久了。
MIN_FRAME_RECALL = 0.15


def recompute_occluded(records, height_ratio, confirm_frames):
    """用新參數重算每幀的 is_occluded（就地改寫 records 裡的 pose_state）。

    持續判定：連續 confirm_frames 個處理幀都「矮且偏下」才成立。
    中斷即歸零——撿東西起身那一刻就會把計數清掉，這正是要擋的行為。
    """
    streak = 0
    for record in records:
        state = record["pose_state"]
        ratio = state.get("height_ratio")
        low_and_down = (ratio is not None and ratio < height_ratio
                        and state.get("y2_ratio", 0.0) > 0.5)
        streak = streak + 1 if low_and_down else 0
        state["is_occluded"] = streak >= confirm_frames


def trigger_with(record, mode):
    """套用觸發策略。與 local_pipeline_eval.decide_trigger 同邏輯，
    但這裡直接吃已被 recompute_occluded 改寫過的 pose_state。"""
    rules = TRIGGER_MODES[mode]
    state = record["pose_state"]
    window_full = record["window_len"] == WINDOW_SIZE
    ai_thinks_fall = (window_full and record["pred_class"] == 0
                      and record["act_conf"] > AI_THINKING_CONF)
    if not record["has_seen_person"]:
        return False
    if state["is_lying"] or state["is_occluded"]:
        if not window_full or ai_thinks_fall:
            return True
        if state["is_occluded"] and not rules["occluded_needs_act"]:
            return True
        return False
    if rules["act_alone"] and window_full and record["pred_class"] == 0 \
            and record["act_conf"] > DIRECT_TRIGGER_CONF:
        return True
    return False


def evaluate(all_records, mode, height_ratio, confirm_frames):
    """回傳 (跌倒片抓到數, 跌倒片總數, 正常片誤報數, 正常片總數, 跌倒幀召回)。"""
    caught = fall_total = false_fired = normal_total = 0
    fall_frames = fall_fired = 0
    for _, should_fire, records in all_records:
        recompute_occluded(records, height_ratio, confirm_frames)
        fired = sum(1 for r in records if trigger_with(r, mode))
        rate = fired / len(records) if records else 0.0
        if should_fire:
            fall_total += 1
            fall_frames += len(records)
            fall_fired += fired
            # 用幀召回門檻而非「報過就算」，理由見 MIN_FRAME_RECALL
            caught += 1 if rate >= MIN_FRAME_RECALL else 0
        else:
            normal_total += 1
            false_fired += 1 if fired > 0 else 0
    recall = fall_fired / fall_frames if fall_frames else 0.0
    return caught, fall_total, false_fired, normal_total, recall


def main():
    parser = argparse.ArgumentParser(description="掃描遮擋判斷參數")
    parser.add_argument("--dir", default=str(Path(__file__).resolve().parent / "test_demo"))
    parser.add_argument("--mode", default="geo-first", choices=sorted(TRIGGER_MODES))
    args = parser.parse_args()

    video_dir = Path(args.dir)
    targets = []
    for path in sorted(video_dir.glob("*.mp4")):
        classified = classify_video(path)
        if classified is not None:
            targets.append((path, *classified))
    if not targets:
        print(f"❌ {video_dir} 裡沒有可辨識的短片")
        return 1

    device = pick_device()
    print(f"🚀 裝置：{device}｜{len(targets)} 支影片｜策略 {args.mode}")
    print("   每支只推論一次，所有參數組合離線套用\n")
    pose_model = YOLO(str(DEFAULT_POSE_WEIGHTS))
    pose_model.to(device)
    act_model = load_act_model(DEFAULT_ACT_WEIGHTS, device)

    all_records = []
    for path, _, should_fire in targets:
        records = run_inference(path, pose_model, act_model, device, POSE_CONF)
        if records:
            all_records.append((path.name, should_fire, records))
            print(f"  ✓ {path.name}")

    print(f"\n{'=' * 78}")
    print("遮擋參數掃描（左＝矮到多少才算，上＝要持續幾個處理幀）")
    print(f"每格：跌倒片抓到 / 正常片誤報數"
          f"（『抓到』＝幀召回 ≥ {MIN_FRAME_RECALL:.0%}，不是『報過一幀就算』）")
    print(f"{'=' * 78}\n")

    header = f"{'高度門檻':<10}"
    for frames in CONFIRM_FRAMES:
        header += f"{f'{frames}幀':>13}"
    print(header)
    print("-" * (10 + 13 * len(CONFIRM_FRAMES)))

    results = []
    for ratio in HEIGHT_RATIOS:
        row = f"{ratio:<10.2f}"
        for frames in CONFIRM_FRAMES:
            caught, fall_total, false_fired, normal_total, recall = evaluate(
                all_records, args.mode, ratio, frames)
            row += f"{f'{caught}/{fall_total}  {false_fired}/{normal_total}':>13}"
            results.append((ratio, frames, caught, fall_total, false_fired,
                            normal_total, recall))
        print(row)

    # 挑推薦：先要求跌倒片全抓到，再取誤報最少者；同分時取幀召回最高的
    perfect = [r for r in results if r[2] == r[3]]
    print(f"\n{'─' * 78}")
    if not perfect:
        print("⚠️ 沒有任何參數組合能抓到全部跌倒片，需放寬門檻或改進判斷方式")
        return 0

    best = sorted(perfect, key=lambda r: (r[4], -r[6]))[:5]
    print("推薦組合（先要求跌倒片全抓到，再取誤報最少、幀召回最高）")
    print(f"{'─' * 78}")
    print(f"{'高度門檻':<10}{'持續幀':<10}{'跌倒抓到':<12}{'正常誤報':<12}{'跌倒幀召回'}")
    for ratio, frames, caught, fall_total, false_fired, normal_total, recall in best:
        print(f"{ratio:<10.2f}{frames:<10}{f'{caught}/{fall_total}':<12}"
              f"{f'{false_fired}/{normal_total}':<12}{recall:.1%}")

    baseline = next((r for r in results if r[0] == 0.70 and r[1] == 1), None)
    if baseline:
        print(f"\n現況（0.70 / 1 幀）：跌倒抓到 {baseline[2]}/{baseline[3]}、"
              f"正常誤報 {baseline[4]}/{baseline[5]}、幀召回 {baseline[6]:.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
