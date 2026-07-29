#!/usr/bin/env python3
"""畫訓練曲線與鏡像增強消融對照。

兩張圖：
    training-curves.png   train/val loss 隨 epoch 變化 —— 收斂與過擬合的直接證據
    ablation-flip.png     有無鏡像增強的對照 —— 證明自己的設計有沒有貢獻

資料來源是 train_act.py 寫進 <權重>.run.json 的 `history` 欄位。
舊的 run.json 沒有 history（那時還沒開始記錄），會被自動略過。

用法：
    ai/.venv/bin/python ai/train/plot_training.py
    ai/.venv/bin/python ai/train/plot_training.py --runs ai/train/runs/ab_flip_s42.run.json
"""

import argparse
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

_AI_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_AI_DIR))
sys.path.insert(0, str(_AI_DIR / "train"))

from plot_eval import setup_font  # noqa: E402

DEFAULT_RUNS_DIR = _AI_DIR / "train" / "runs"
DEFAULT_OUT_DIR = _AI_DIR / "train" / "eval_results"
COLOR_FLIP = "#2471a3"
COLOR_NOFLIP = "#c0392b"


def load_runs(paths):
    """讀 run.json，只留有 history 的。回傳 [(名稱, record)]。"""
    runs = []
    for path in sorted(paths):
        record = json.loads(Path(path).read_text(encoding="utf-8"))
        if not record.get("history"):
            continue
        runs.append((Path(path).stem.replace(".run", ""), record))
    return runs


def plot_curves(runs, out_path):
    """train/val loss 曲線。

    配色按「有無鏡像」分組而非按 seed——6 條線各給一色會糊成一團，
    按組上色才看得出結構。組內每個 seed 一條，用低透明度疊加表示分布。
    """
    setup_font()
    figure, axes = plt.subplots(1, 2, figsize=(13.5, 5.4))
    seen_labels = set()

    for name, record in runs:
        no_flip = bool(record.get("exclude_flipped"))
        color = COLOR_NOFLIP if no_flip else COLOR_FLIP
        group = "無鏡像" if no_flip else "有鏡像"
        history = record["history"]
        epochs = [h["epoch"] for h in history]

        train_label = f"{group} train" if f"{group}-train" not in seen_labels else None
        val_label = f"{group} val" if f"{group}-val" not in seen_labels else None
        seen_labels.update({f"{group}-train", f"{group}-val"})

        axes[0].plot(epochs, [h["train_loss"] for h in history], color=color,
                     linewidth=1.5, alpha=0.75, label=train_label)
        axes[0].plot(epochs, [h["val_loss"] for h in history], color=color,
                     linewidth=1.2, linestyle="--", alpha=0.55, label=val_label)
        best = record.get("best_epoch")
        best_row = next((h for h in history if h["epoch"] == best), None) if best else None
        if best_row:
            axes[0].scatter([best], [best_row["val_loss"]], color=color, s=80,
                            marker="*", zorder=5, edgecolors="white", linewidths=0.6)
        axes[1].plot(epochs, [h["val_recall"] for h in history], color=color,
                     linewidth=1.5, alpha=0.75, label=train_label and f"{group} recall")
        axes[1].plot(epochs, [h["val_precision"] for h in history], color=color,
                     linewidth=1.2, linestyle="--", alpha=0.5,
                     label=val_label and f"{group} precision")

    axes[0].set_xlabel("Epoch")
    axes[0].set_ylabel("Loss（對數刻度）")
    axes[0].set_title("損失曲線（實線 train／虛線 val／★ 最佳輪）", fontsize=12)
    axes[0].grid(alpha=0.25, linestyle="--")
    axes[0].legend(fontsize=9)
    axes[0].set_yscale("log")
    # train 掉到 1e-4 而 val 停在 1e-2，兩個數量級的落差就是過擬合。
    # 這是 25 次獨立跌倒事件配 71K 參數的必然結果，早停負責挑出 val 最低的那一輪。
    axes[0].annotate("train 與 val 差約兩個數量級\n→ 過擬合（早停選 val 最低點）",
                     xy=(0.42, 0.12), xycoords="axes fraction", fontsize=9,
                     color="#444", bbox=dict(boxstyle="round,pad=0.4",
                                             facecolor="#f4f4f4", edgecolor="#ccc"))

    axes[1].set_xlabel("Epoch")
    axes[1].set_ylabel("比率")
    axes[1].set_title("驗證集跌倒類（實線 recall／虛線 precision）", fontsize=12)
    axes[1].grid(alpha=0.25, linestyle="--")
    axes[1].legend(fontsize=9, loc="lower right")
    axes[1].set_ylim(0, 1.05)

    figure.suptitle(f"AcT 訓練過程（{len(runs)} 次訓練：3 種子 × 有／無鏡像）", fontsize=15)
    figure.tight_layout(rect=[0, 0, 1, 0.94])
    figure.savefig(out_path, dpi=150)
    plt.close(figure)


def plot_ablation(eval_report, out_path, strategy="act_only"):
    """有無鏡像增強的對照，**用 test split 指標**。

    刻意不用訓練時的 val 指標：那是視窗級分類準確率，兩組都在 0.99 以上，
    看不出差異。真正的差別要在測試集的幀級指標上才顯現。
    模型以名稱含 "noflip" 分組（對應 --exclude-flipped）。
    """
    groups = {"flip": [], "noflip": []}
    for name, result in eval_report["results"].items():
        groups["noflip" if "noflip" in name else "flip"].append(result[strategy])
    if not groups["flip"] or not groups["noflip"]:
        return False

    setup_font()
    metrics = [("normal_fpr", "正常影片誤報率", True),
               ("fall_recall", "跌倒幀召回率", False),
               ("forward_recall", "前跌幀召回率", False),
               ("post_fall_fpr", "非跌落段誤報率", True)]
    figure, axes = plt.subplots(1, len(metrics), figsize=(3.9 * len(metrics), 4.9))

    for axis, (key, label, lower_better) in zip(axes, metrics):
        positions, values, errors, colors = [], [], [], []
        for offset, (group, color) in enumerate((("flip", COLOR_FLIP), ("noflip", COLOR_NOFLIP))):
            scores = [result[key] * 100 for result in groups[group]]
            positions.append(offset)
            values.append(float(np.mean(scores)))
            errors.append([float(np.mean(scores) - min(scores)),
                           float(max(scores) - np.mean(scores))])
            colors.append(color)
        axis.bar(positions, values, 0.55, yerr=np.array(errors).T, capsize=5,
                 color=colors, alpha=0.88)
        for position, value in zip(positions, values):
            axis.text(position, value + max(values) * 0.04 + 0.3, f"{value:.1f}%",
                      ha="center", fontsize=10)
        axis.set_xticks(positions)
        axis.set_xticklabels([f"有鏡像\n(n={len(groups['flip'])})",
                              f"無鏡像\n(n={len(groups['noflip'])})"], fontsize=10)
        axis.set_title(f"{label}\n({'越低越好' if lower_better else '越高越好'})", fontsize=11)
        axis.set_ylim(0, max(values) * 1.35 + 1)
        axis.grid(axis="y", alpha=0.25, linestyle="--")

    figure.suptitle("鏡像增強消融（test split，AcT 隔離）：多這 100 支鏡像影片，到底有沒有用？",
                    fontsize=14)
    figure.text(0.5, 0.01, "誤差棒為 3 個隨機種子的全距", ha="center", fontsize=9, color="#555")
    figure.tight_layout(rect=[0, 0.03, 1, 0.92])
    figure.savefig(out_path, dpi=150)
    plt.close(figure)
    return True


def parse_args():
    parser = argparse.ArgumentParser(description="畫訓練曲線與消融對照")
    parser.add_argument("--runs", nargs="*", default=None, help="指定 run.json（預設掃 runs/）")
    parser.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--eval-json", default=None,
                        help="消融圖用的 evaluate_act.py 輸出（預設取最新一份）")
    return parser.parse_args()


def main():
    args = parse_args()
    paths = args.runs if args.runs else list(Path(args.runs_dir).glob("*.run.json"))
    runs = load_runs(paths)
    if not runs:
        print("❌ 找不到含 history 的 run.json（需用新版 train_act.py 重跑）", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    curves_path = out_dir / "training-curves.png"
    plot_curves(runs, curves_path)
    print(f"📊 {curves_path}（{len(runs)} 次訓練）")

    eval_path = Path(args.eval_json) if args.eval_json else None
    if eval_path is None:
        candidates = sorted(out_dir.glob("eval-*.json"))
        eval_path = candidates[-1] if candidates else None
    if eval_path is None:
        print("⚠ 找不到 eval-*.json，跳過消融圖（先跑 evaluate_act.py）")
        return 0
    eval_report = json.loads(eval_path.read_text(encoding="utf-8"))
    ablation_path = out_dir / "ablation-flip.png"
    if plot_ablation(eval_report, ablation_path):
        print(f"📊 {ablation_path}")
    else:
        print(f"⚠ {eval_path.name} 裡沒有成對的有／無鏡像模型，跳過消融圖")
    return 0


if __name__ == "__main__":
    sys.exit(main())
