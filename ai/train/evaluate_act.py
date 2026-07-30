#!/usr/bin/env python3
"""比較多顆 AcT 權重在同一測試集上的表現，輸出並排對照表。

設計重點：**所有模型走完全相同的程式碼路徑**，這是公平比較的前提。
評估直接讀 features/*.npz（不重跑 YOLO），所以幾秒就能跑完，可以反覆試。

為什麼要分三層看（只看管線級會誤導）：
    AcT 目前被降權成「只能附議」（ACT_ALONE_CAN_TRIGGER=false），
    幾何防線會把兩顆模型的差異吃掉大半。所以必須有 AcT 隔離評估。

四個指標，各自回答一個問題：
    fall_recall        真跌倒抓到幾成？
    forward_recall     **前跌**抓到幾成？（現行系統的盲區，本次重訓的核心目標）
    normal_fpr         正常動作影片誤報率
    post_fall_fpr      跌倒影片「標註區間外」的誤報率
                       ← 這欄專門抓「模型學成躺著＝跌倒」的失敗模式。
                         人跌完躺在地上那段若持續報，代表只學會辨識姿勢、
                         沒學會辨識動作。管線級指標看不出這件事。

兩個對照組（沒有它們，任何數字都無法解讀）：
    always_fire     每幀都報。召回 100%、誤報 100%。
                    上一輪就是漏了這個，把「段級召回 95%」誤讀成很準。
    geometry_only   AcT 停用，只靠幾何防線。
                    回答「AcT 到底貢獻了什麼」——若新舊模型都跟它沒差，重訓就沒意義。

用法：
    ai/.venv/bin/python ai/train/evaluate_act.py \\
        --models ai/action_transformer.pth ai/action_transformer_v2.pth
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import torch

_AI_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_AI_DIR))

from local_pipeline_eval import (  # noqa: E402
    AI_THINKING_CONF, DIRECT_TRIGGER_CONF, WINDOW_SIZE, ActionTransformer,
    decide_trigger, parse_label_file, pick_device,
)
from pose_features import DEFAULT_FEATURE_NORM, FEATURE_NORMS  # noqa: E402
from fall_chain import DEFAULT_LYING_RULE, LYING_RULES, decide_lying  # noqa: E402
import dataset_utils as du  # noqa: E402

DEFAULT_DATASET = _AI_DIR / "train" / "dataset"
DEFAULT_OUT_DIR = _AI_DIR / "train" / "eval_results"
FRAME_SKIP = 2
SOURCE_FPS = 20.0
EFFECTIVE_FPS = SOURCE_FPS / FRAME_SKIP   # 跳幀後的等效幀率，換算延遲用
CLASS_FALL = 0


def file_digest(path):
    """權重檔的 sha256 前 12 碼。訓練幾輪後光看檔名分不清哪個數字對應哪顆權重。"""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]


def load_model(weights_path, device):
    model = ActionTransformer(input_dim=34, seq_len=WINDOW_SIZE, num_classes=2)
    state = torch.load(weights_path, map_location="cpu")
    if hasattr(state, "state_dict"):
        state = state.state_dict()
    model.load_state_dict(state)
    return model.to(device).eval()


def run_act_over_video(model, features, device, batch_size=256):
    """對整支影片逐幀推論。回傳 (pred_class, confidence) 兩個等長 array。

    前 29 個處理幀視窗未滿，正式管線在那裡不跑 AcT，這裡比照辦理：
    pred=1（正常）、conf=0。
    """
    total = len(features)
    pred = np.ones(total, dtype=np.int64)
    conf = np.zeros(total, dtype=np.float32)
    if total < WINDOW_SIZE:
        return pred, conf

    windows = np.stack([features[i - WINDOW_SIZE + 1:i + 1]
                        for i in range(WINDOW_SIZE - 1, total)])
    outputs = []
    with torch.no_grad():
        for start in range(0, len(windows), batch_size):
            batch = torch.from_numpy(windows[start:start + batch_size]).to(device)
            outputs.append(torch.softmax(model(batch), dim=1).cpu().numpy())
    probability = np.concatenate(outputs)
    pred[WINDOW_SIZE - 1:] = probability.argmax(axis=1)
    conf[WINDOW_SIZE - 1:] = probability.max(axis=1)
    return pred, conf


def triggers_for_strategy(strategy, data, pred, conf):
    """依策略算出逐幀的觸發布林陣列。

    所有策略共用同一份 pose 幾何資料，差別只在「怎麼用 AcT」——
    攤成一個函式，避免各策略各寫一套迴圈而悄悄長出差異。
    """
    total = len(pred)
    is_lying = data["is_lying"]
    is_occluded = data["is_occluded"]
    valid = data["valid"]

    if strategy == "always_fire":
        return np.ones(total, dtype=bool)
    if strategy == "geometry_only":
        # 對齊正式管線的降級行為（inference_test.py:756）：Triton 掛掉時
        # pred_class 改由 is_physically_lying 決定，AcT 完全不參與
        seen = np.maximum.accumulate(valid)
        return seen & (is_lying | is_occluded)

    mode = "current" if strategy == "pipeline_current" else "geo-first"
    fired = np.zeros(total, dtype=bool)
    has_seen_person = False
    for idx in range(total):
        has_seen_person = has_seen_person or bool(valid[idx])
        pose_state = {"is_lying": bool(is_lying[idx]), "is_occluded": bool(is_occluded[idx])}
        should_fire, _ = decide_trigger(
            pose_state, min(idx + 1, WINDOW_SIZE), int(pred[idx]), float(conf[idx]),
            has_seen_person, mode=mode,
        )
        fired[idx] = should_fire
    return fired


def act_only_triggers(pred, conf, threshold):
    """AcT 自己的判定，完全不看幾何。門檻沿用正式管線的兩個常數之一。"""
    return (pred == CLASS_FALL) & (conf > threshold)


def evaluate_strategy(videos, fired_by_video):
    """彙總指標。videos 是 [(stem, is_fall, span_mask, total)]。"""
    fall_hit = fall_total = 0
    forward_hit = forward_total = 0
    normal_fire = normal_total = 0
    post_fire = post_total = 0
    latencies = []

    for stem, is_fall, span_mask, total in videos:
        fired = fired_by_video[stem]
        if not is_fall:
            normal_fire += int(fired.sum())
            normal_total += total
            continue

        in_span = fired & span_mask
        fall_hit += int(in_span.sum())
        fall_total += int(span_mask.sum())
        if "forward" in stem.lower():
            forward_hit += int(in_span.sum())
            forward_total += int(span_mask.sum())

        outside = ~span_mask
        post_fire += int((fired & outside).sum())
        post_total += int(outside.sum())

        span_indices = np.flatnonzero(span_mask)
        fired_indices = np.flatnonzero(fired)
        if span_indices.size and fired_indices.size:
            after = fired_indices[fired_indices >= span_indices[0]]
            if after.size:
                latencies.append((after[0] - span_indices[0]) / EFFECTIVE_FPS)

    ratio = lambda hit, total: (hit / total) if total else 0.0
    return {
        "fall_recall": ratio(fall_hit, fall_total),
        "forward_recall": ratio(forward_hit, forward_total),
        "normal_fpr": ratio(normal_fire, normal_total),
        "post_fall_fpr": ratio(post_fire, post_total),
        "mean_latency_s": float(np.mean(latencies)) if latencies else None,
        "detected_videos": int(sum(
            1 for stem, is_fall, span_mask, _ in videos
            if is_fall and (fired_by_video[stem] & span_mask).any()
        )),
    }


def load_test_videos(dataset_dir, split, feature_norm=DEFAULT_FEATURE_NORM,
                     lying_rule=DEFAULT_LYING_RULE, crop_guard=False):
    """載入該 split 的特徵與標註遮罩。回傳 (videos, features_by_stem, data_by_stem)。"""
    splits = du.load_splits(dataset_dir)
    features_dir = du.features_dir(dataset_dir, feature_norm)
    videos, features_by_stem, data_by_stem = [], {}, {}
    skipped = []

    for name in du.split_files(splits, split):
        stem = Path(name).stem
        feature_path = features_dir / f"{stem}.npz"
        if not feature_path.is_file():
            skipped.append(stem)
            continue
        data = np.load(feature_path)
        if du.read_feature_norm(data) != feature_norm:
            raise ValueError(
                f"{feature_path} 的 feature_norm 是 {du.read_feature_norm(data)}，"
                f"但要求 {feature_norm}。目錄與內容不符，請重抽特徵"
            )
        features = data["features"]
        total = len(features)
        if total < WINDOW_SIZE:
            skipped.append(stem)
            continue

        is_fall = du.is_fall_video(stem)
        span_mask = np.zeros(total, dtype=bool)
        if is_fall:
            label_path = du.label_path_for(dataset_dir, stem)
            segments = parse_label_file(label_path, SOURCE_FPS) if label_path.is_file() else []
            if not segments:
                skipped.append(stem)
                continue
            for start, end in segments:
                span_mask[max(0, start // FRAME_SKIP):min(total, end // FRAME_SKIP)] = True
            if not span_mask.any():
                skipped.append(stem)
                continue

        videos.append((stem, is_fall, span_mask, total))
        features_by_stem[stem] = features
        data_by_stem[stem] = {key: data[key] for key in ("is_lying", "is_occluded", "valid")}
        # 換躺平規則時用 npz 存的原始角度／寬高比重算，不重跑 YOLO。
        # 舊 npz（2026-07-30 前抽的）沒有這兩個欄位，只能用當初存好的 is_lying。
        if lying_rule != DEFAULT_LYING_RULE or crop_guard:
            if "body_angle" not in data.files or "aspect_ratio" not in data.files:
                raise ValueError(
                    f"{feature_path} 沒有 body_angle／aspect_ratio 欄位，無法重算躺平規則。"
                    f"請重抽特徵：extract_features.py --splits {split} --overwrite"
                )
            angles, aspects = data["body_angle"], data["aspect_ratio"]
            cropped = (data["body_cropped"] if "body_cropped" in data.files
                       else np.zeros(len(angles), dtype=bool))
            data_by_stem[stem]["is_lying"] = np.array([
                decide_lying(None if np.isnan(angle) else float(angle),
                             float(aspect), lying_rule, bool(crop), crop_guard)
                for angle, aspect, crop in zip(angles, aspects, cropped)
            ], dtype=bool)

    return videos, features_by_stem, data_by_stem, skipped


def format_markdown(report):
    """並排對照表。人看的版本。"""
    rows = [
        ("跌倒幀召回率", "fall_recall", "越高越好", True),
        ("**前跌幀召回率**", "forward_recall", "越高越好（核心指標）", True),
        ("正常影片誤報率", "normal_fpr", "越低越好", False),
        ("跌倒片非跌落段誤報率", "post_fall_fpr", "越低越好（躺著＝跌倒？）", False),
    ]
    names = list(report["results"].keys())
    lines = [
        f"# AcT 評估對照（{report['test_set']['split']} split）",
        "",
        f"測試集：受試者 {report['test_set']['subjects']}，{report['test_set']['videos']} 支"
        f"（鏡像檔已排除）｜評估時間 {report['evaluated_at']}",
        "",
        "## 模型",
        "",
        "| 代號 | 權重 | sha256 |",
        "|---|---|---|",
    ]
    for name in names:
        info = report["models"][name]
        lines.append(f"| {name} | `{info['path']}` | `{info['sha256']}` |")

    for strategy in report["strategies"]:
        lines += ["", f"## {strategy}", "",
                  "| 指標 | " + " | ".join(names) + " | 方向 |",
                  "|---|" + "---|" * len(names) + "---|"]
        for label, key, direction, _ in rows:
            cells = []
            for name in names:
                value = report["results"][name][strategy][key]
                cells.append(f"{value:.1%}")
            lines.append(f"| {label} | " + " | ".join(cells) + f" | {direction} |")
        latency_cells = []
        for name in names:
            value = report["results"][name][strategy]["mean_latency_s"]
            latency_cells.append("—" if value is None else f"{value:.2f}s")
        lines.append("| 平均觸發延遲 | " + " | ".join(latency_cells) + " | 越低越好 |")

    lines += ["", "## 對照組", "",
              "| 指標 | " + " | ".join(report["baselines"]) + " |",
              "|---|" + "---|" * len(report["baselines"])]
    for label, key, _, _ in rows:
        cells = [f"{report['baselines'][b][key]:.1%}" for b in report["baselines"]]
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    lines += ["",
              "> `always_fire` 每幀都報，召回必為 100%、誤報必為 100%。",
              "> 任何模型若誤報接近它，代表沒有鑑別力。",
              "> `geometry_only` 是 AcT 停用時的表現——模型要有意義，必須明顯優於它。"]
    return "\n".join(lines) + "\n"


def parse_args():
    parser = argparse.ArgumentParser(description="比較多顆 AcT 權重")
    parser.add_argument("--models", nargs="+", required=True, help="要比較的 .pth（可多個）")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--split", default="test")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--act-threshold", type=float, default=DIRECT_TRIGGER_CONF,
                        help=f"AcT 隔離評估的信心門檻（預設 {DIRECT_TRIGGER_CONF}，"
                             f"對齊正式管線單獨觸發的門檻）")
    parser.add_argument("--feature-norm", default=DEFAULT_FEATURE_NORM, choices=FEATURE_NORMS,
                        help="用哪一份特徵評估。會跟每顆權重 run.json 記的模式核對，"
                             "不一致直接擋下")
    parser.add_argument("--lying-rule", default=DEFAULT_LYING_RULE, choices=LYING_RULES,
                        help="躺平規則（防線 A）：current=現況 angle<40 或 w/h>1.25／"
                             "aspect=只看 w/h／wide=補上 angle>140。"
                             "非 current 時用 npz 存的原始角度重算，不重跑 YOLO")
    parser.add_argument("--crop-guard", action="store_true",
                        help="下半身不在框裡的人不採用 w/h（框不是完整人形，比例沒意義）")
    return parser.parse_args()


def weights_feature_norm(weights_path):
    """這顆權重是用哪種正規化訓練的。沒有 run.json 就當 image（舊權重都是）。"""
    record_path = Path(weights_path).with_suffix(".run.json")
    if not record_path.is_file():
        return DEFAULT_FEATURE_NORM
    record = json.loads(record_path.read_text(encoding="utf-8"))
    return du.check_feature_norm(record.get("feature_norm", DEFAULT_FEATURE_NORM))


def main():
    args = parse_args()
    dataset_dir = Path(args.dataset).resolve()

    # 先擋掉「權重與特徵不同調」，再花時間載模型跑推論。這種錯不會拋例外，
    # 只會安靜地產出一份錯的評估報告——那比直接失敗糟糕得多
    mismatched = [(Path(p).name, weights_feature_norm(p)) for p in args.models
                  if weights_feature_norm(p) != args.feature_norm]
    if mismatched:
        print(f"❌ 以下權重不是用 {args.feature_norm} 特徵訓練的：", file=sys.stderr)
        for name, norm in mismatched:
            print(f"   {name}（訓練時用 {norm}）", file=sys.stderr)
        print(f"   請改用 --feature-norm {mismatched[0][1]}，"
              f"或改比同一種正規化的權重", file=sys.stderr)
        return 1

    videos, features_by_stem, data_by_stem, skipped = load_test_videos(
        dataset_dir, args.split, args.feature_norm, args.lying_rule, args.crop_guard)
    if not videos:
        print("❌ 測試集沒有可用影片（先跑 extract_features.py）", file=sys.stderr)
        return 1

    fall_videos = sum(1 for _, is_fall, _, _ in videos if is_fall)
    print(f"📊 {args.split} split：{len(videos)} 支"
          f"（跌倒 {fall_videos} / 正常 {len(videos) - fall_videos}）")
    if skipped:
        print(f"   ⚠ 跳過 {len(skipped)} 支（缺特徵或缺標註）：{', '.join(skipped[:6])}")

    device = pick_device()
    strategies = ["act_only", "pipeline_geo_first", "pipeline_current"]
    report = {
        "evaluated_at": datetime.now().isoformat(timespec="seconds"),
        "test_set": {
            "split": args.split,
            "subjects": du.load_splits(dataset_dir)["rules"]["split_subjects"][args.split],
            "videos": len(videos),
            "fall_videos": fall_videos,
            "skipped": skipped,
        },
        "params": {"frame_skip": FRAME_SKIP, "window_size": WINDOW_SIZE,
                   "act_threshold": args.act_threshold,
                   "feature_norm": args.feature_norm,
                   "lying_rule": args.lying_rule,
                   "crop_guard": args.crop_guard,
                   "ai_thinking_conf": AI_THINKING_CONF,
                   "direct_trigger_conf": DIRECT_TRIGGER_CONF},
        "strategies": strategies,
        "models": {},
        "results": {},
        "baselines": {},
    }

    # 對照組不依賴任何模型，先算
    for strategy in ("always_fire", "geometry_only"):
        fired = {stem: triggers_for_strategy(strategy, data_by_stem[stem],
                                             np.ones(total, dtype=np.int64),
                                             np.zeros(total, dtype=np.float32))
                 for stem, _, _, total in videos}
        report["baselines"][strategy] = evaluate_strategy(videos, fired)

    for weights_path in args.models:
        path = Path(weights_path).resolve()
        if not path.is_file():
            print(f"❌ 找不到權重：{path}", file=sys.stderr)
            return 1
        name = path.stem
        print(f"🔍 {name} …", end="", flush=True)
        model = load_model(path, device)
        report["models"][name] = {"path": str(path.relative_to(_AI_DIR.parent)),
                                  "sha256": file_digest(path)}

        predictions = {}
        for stem, _, _, _ in videos:
            predictions[stem] = run_act_over_video(model, features_by_stem[stem], device)

        report["results"][name] = {}
        for strategy in strategies:
            if strategy == "act_only":
                fired = {stem: act_only_triggers(*predictions[stem], args.act_threshold)
                         for stem, _, _, _ in videos}
            else:
                fired = {stem: triggers_for_strategy(strategy, data_by_stem[stem],
                                                     *predictions[stem])
                         for stem, _, _, _ in videos}
            report["results"][name][strategy] = evaluate_strategy(videos, fired)
        print(" 完成")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = out_dir / f"eval-{stamp}.json"
    markdown_path = out_dir / f"eval-{stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    markdown = format_markdown(report)
    markdown_path.write_text(markdown, encoding="utf-8")

    print()
    print(markdown)
    print(f"📄 {json_path}")
    print(f"📄 {markdown_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
