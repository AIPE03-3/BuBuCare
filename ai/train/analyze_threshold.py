#!/usr/bin/env python3
"""AcT 的閾值分析：PR 曲線與操作點選擇。

為什麼需要這支：
    正式管線的 DIRECT_TRIGGER_CONF = 0.55 是**為舊模型挑的**，重訓後從沒重選過。
    新模型的機率分布不同，沿用舊閾值等於隨便挑一個操作點。
    這支腳本掃描整條曲線，在「誤報率不超過上限」的約束下找最佳召回。

指標定義（幀級，與 evaluate_act.py 一致）：
    正例 = 跌倒影片標註區間內的幀
    負例 = 正常影片的所有幀 ＋ 跌倒影片標註區間外的幀
    分數 = AcT 輸出的 P(跌倒)

⚠ 召回率天生偏低：AcT 視窗涵蓋前 3 秒，跌落剛開始那幾幀的視窗裡還沒有跌落動作，
   不可能被判為跌倒。看曲線的**相對形狀**與操作點取捨，不要看絕對值。

用法：
    ai/.venv/bin/python ai/train/analyze_threshold.py \\
        --models ai/action_transformer.pth ai/train/runs/act_s42_st1.pth
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import torch  # noqa: E402

_AI_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_AI_DIR))

from local_pipeline_eval import (  # noqa: E402
    DIRECT_TRIGGER_CONF, WINDOW_SIZE, ActionTransformer, pick_device,
)
from evaluate_act import (  # noqa: E402
    file_digest, load_model, load_test_videos, weights_feature_norm,
)
from pose_features import DEFAULT_FEATURE_NORM, FEATURE_NORMS  # noqa: E402
from plot_eval import setup_font  # noqa: E402

DEFAULT_DATASET = _AI_DIR / "train" / "dataset"
DEFAULT_OUT_DIR = _AI_DIR / "train" / "eval_results"
# 操作點的約束：正常影片誤報率上限。對齊重訓計畫第 4 章的驗收標準
FPR_BUDGET = 0.02


def fall_probability(model, features, device, batch_size=256):
    """回傳每個處理幀的 P(跌倒)。視窗未滿的前 29 幀給 0（正式管線在那裡不跑 AcT）。"""
    total = len(features)
    scores = np.zeros(total, dtype=np.float32)
    if total < WINDOW_SIZE:
        return scores
    windows = np.stack([features[i - WINDOW_SIZE + 1:i + 1]
                        for i in range(WINDOW_SIZE - 1, total)])
    chunks = []
    with torch.no_grad():
        for start in range(0, len(windows), batch_size):
            batch = torch.from_numpy(windows[start:start + batch_size]).to(device)
            chunks.append(torch.softmax(model(batch), dim=1)[:, 0].cpu().numpy())
    scores[WINDOW_SIZE - 1:] = np.concatenate(chunks)
    return scores


def collect_scores(model, videos, features_by_stem, device):
    """把整個測試集攤平成 (分數, 標籤, 是否為正常影片) 三個等長 array。"""
    scores, labels, from_normal = [], [], []
    for stem, is_fall, span_mask, _ in videos:
        probability = fall_probability(model, features_by_stem[stem], device)
        scores.append(probability)
        labels.append(span_mask.astype(np.int8))
        from_normal.append(np.full(len(probability), not is_fall))
    return (np.concatenate(scores), np.concatenate(labels), np.concatenate(from_normal))


def precision_recall_curve(scores, labels):
    """自己算 PR 曲線（不引入 sklearn，少一個依賴）。回傳 (precision, recall, 閾值, AP)。"""
    order = np.argsort(-scores)
    sorted_labels = labels[order]
    true_positive = np.cumsum(sorted_labels == 1)
    false_positive = np.cumsum(sorted_labels == 0)
    total_positive = max(int((labels == 1).sum()), 1)
    precision = true_positive / np.maximum(true_positive + false_positive, 1)
    recall = true_positive / total_positive
    # AP＝以召回增量為權重的精確度加權和（PR 曲線下面積的標準離散近似）
    average_precision = float(np.sum(np.diff(np.concatenate([[0.0], recall])) * precision))
    return precision, recall, scores[order], average_precision


def sweep_thresholds(scores, labels, from_normal, steps=200):
    """掃描閾值，回傳每個閾值下的召回率與「正常影片誤報率」。

    誤報率刻意只算正常影片：跌倒影片裡「人已躺在地上」那段被報，
    在真實場景未必算錯，混進來會讓誤報率虛高、操作點選得太保守。
    """
    thresholds = np.linspace(0.05, 0.99, steps)
    positive_mask = labels == 1
    normal_mask = from_normal
    recalls, normal_fprs = [], []
    for threshold in thresholds:
        fired = scores > threshold
        recalls.append(float(fired[positive_mask].mean()) if positive_mask.any() else 0.0)
        normal_fprs.append(float(fired[normal_mask].mean()) if normal_mask.any() else 0.0)
    return thresholds, np.array(recalls), np.array(normal_fprs)


def best_operating_point(thresholds, recalls, normal_fprs, budget):
    """在誤報率 ≤ budget 的約束下，取召回率最高的閾值。"""
    feasible = np.flatnonzero(normal_fprs <= budget)
    if feasible.size == 0:
        return None
    best = feasible[int(np.argmax(recalls[feasible]))]
    return {"threshold": float(thresholds[best]),
            "recall": float(recalls[best]),
            "normal_fpr": float(normal_fprs[best])}


def value_at(thresholds, values, target):
    """取最接近 target 閾值處的數值。"""
    return float(values[int(np.argmin(np.abs(thresholds - target)))])


def plot(results, out_path):
    setup_font()
    figure, axes = plt.subplots(1, 2, figsize=(14, 5.8))
    colors = plt.cm.tab10.colors

    for index, (name, data) in enumerate(results.items()):
        color = colors[index % len(colors)]
        axes[0].plot(data["recall_curve"], data["precision_curve"], color=color,
                     label=f"{name}（AP={data['average_precision']:.3f}）", linewidth=1.8)
        axes[1].plot(data["thresholds"], np.array(data["normal_fpr_curve"]) * 100,
                     color=color, linestyle="-", linewidth=1.8, label=f"{name}：誤報")
        axes[1].plot(data["thresholds"], np.array(data["recall_curve_by_threshold"]) * 100,
                     color=color, linestyle="--", linewidth=1.5, label=f"{name}：召回")
        point = data["best_operating_point"]
        if point:
            axes[1].scatter([point["threshold"]], [point["recall"] * 100], color=color,
                            s=90, zorder=5, marker="*")

    axes[0].set_xlabel("召回率 Recall")
    axes[0].set_ylabel("精確率 Precision")
    axes[0].set_title("PR 曲線（幀級）", fontsize=13)
    axes[0].grid(alpha=0.25, linestyle="--")
    axes[0].legend(fontsize=9)
    axes[0].set_xlim(0, 1)
    axes[0].set_ylim(0, 1.02)

    axes[1].axvline(DIRECT_TRIGGER_CONF, color="#c0392b", linestyle=":", linewidth=2,
                    label=f"現行閾值 {DIRECT_TRIGGER_CONF}")
    axes[1].axhline(FPR_BUDGET * 100, color="#7f8c8d", linestyle=":", linewidth=1.5,
                    label=f"誤報上限 {FPR_BUDGET:.0%}")
    axes[1].set_xlabel("閾值 P(跌倒)")
    axes[1].set_ylabel("百分比 (%)")
    axes[1].set_title("閾值 vs 召回／誤報（★＝誤報 ≤2% 下的最佳召回）", fontsize=13)
    axes[1].grid(alpha=0.25, linestyle="--")
    axes[1].legend(fontsize=8, loc="upper right")
    axes[1].set_ylim(-2, 60)

    figure.suptitle("AcT 閾值分析（test split：S2/S5/S10）", fontsize=15)
    figure.tight_layout(rect=[0, 0, 1, 0.94])
    figure.savefig(out_path, dpi=150)
    plt.close(figure)


def parse_args():
    parser = argparse.ArgumentParser(description="AcT 閾值分析與 PR 曲線")
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--split", default="test")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--fpr-budget", type=float, default=FPR_BUDGET)
    parser.add_argument("--feature-norm", default=DEFAULT_FEATURE_NORM, choices=FEATURE_NORMS,
                        help="用哪一份特徵。會跟權重 run.json 記的模式核對")
    return parser.parse_args()


def main():
    args = parse_args()
    dataset_dir = Path(args.dataset).resolve()

    mismatched = [(Path(p).name, weights_feature_norm(p)) for p in args.models
                  if weights_feature_norm(p) != args.feature_norm]
    if mismatched:
        print(f"❌ 以下權重不是用 {args.feature_norm} 特徵訓練的：", file=sys.stderr)
        for name, norm in mismatched:
            print(f"   {name}（訓練時用 {norm}）", file=sys.stderr)
        return 1

    videos, features_by_stem, _, skipped = load_test_videos(
        dataset_dir, args.split, args.feature_norm)
    if not videos:
        print("❌ 測試集沒有可用影片", file=sys.stderr)
        return 1

    device = pick_device()
    results = {}
    print(f"📊 {args.split} split：{len(videos)} 支｜誤報上限 {args.fpr_budget:.0%}")
    print("-" * 76)

    for weights_path in args.models:
        path = Path(weights_path).resolve()
        name = path.stem
        model = load_model(path, device)
        scores, labels, from_normal = collect_scores(model, videos, features_by_stem, device)
        precision, recall, thresholds_sorted, average_precision = \
            precision_recall_curve(scores, labels)
        thresholds, recalls, normal_fprs = sweep_thresholds(scores, labels, from_normal)
        point = best_operating_point(thresholds, recalls, normal_fprs, args.fpr_budget)

        current_recall = value_at(thresholds, recalls, DIRECT_TRIGGER_CONF)
        current_fpr = value_at(thresholds, normal_fprs, DIRECT_TRIGGER_CONF)
        results[name] = {
            "path": str(path.relative_to(_AI_DIR.parent)),
            "sha256": file_digest(path),
            "average_precision": average_precision,
            "precision_curve": precision.tolist(),
            "recall_curve": recall.tolist(),
            "thresholds": thresholds.tolist(),
            "recall_curve_by_threshold": recalls.tolist(),
            "normal_fpr_curve": normal_fprs.tolist(),
            "at_current_threshold": {"threshold": DIRECT_TRIGGER_CONF,
                                     "recall": current_recall, "normal_fpr": current_fpr},
            "best_operating_point": point,
        }
        print(f"{name}")
        print(f"  AP = {average_precision:.3f}")
        print(f"  現行閾值 {DIRECT_TRIGGER_CONF}｜召回 {current_recall:.1%}"
              f"｜誤報 {current_fpr:.1%}")
        if point:
            gain = point["recall"] - current_recall
            print(f"  最佳閾值 {point['threshold']:.2f}｜召回 {point['recall']:.1%}"
                  f"｜誤報 {point['normal_fpr']:.1%}"
                  f"｜{'召回 ' + format(gain, '+.1%') if abs(gain) > 1e-9 else '與現行相同'}")
        else:
            print(f"  ⚠ 沒有任何閾值能把誤報壓到 {args.fpr_budget:.0%} 以下")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    png_path = out_dir / f"threshold-{stamp}.png"
    json_path = out_dir / f"threshold-{stamp}.json"
    plot(results, png_path)
    # 曲線本身很長，JSON 只留摘要，圖檔已經表達形狀
    summary = {name: {k: v for k, v in data.items()
                      if not k.endswith("_curve") and k != "thresholds"}
               for name, data in results.items()}
    json_path.write_text(json.dumps(
        {"evaluated_at": datetime.now().isoformat(timespec="seconds"),
         "split": args.split, "fpr_budget": args.fpr_budget,
         "feature_norm": args.feature_norm,
         "videos": len(videos), "skipped": skipped, "models": summary},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("-" * 76)
    print(f"📊 {png_path}")
    print(f"📄 {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
