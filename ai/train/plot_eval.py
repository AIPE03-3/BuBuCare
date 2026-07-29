#!/usr/bin/env python3
"""把 evaluate_act.py 的 JSON 畫成對照圖（PNG）。

讀最新一份 eval_results/eval-*.json，輸出兩張圖：
    eval-<時間戳>-overview.png    重訓前後對照（主圖）
    eval-<時間戳>-variance.png    各次訓練的離散度

設計原則：
    - 第一個模型視為 baseline（重訓前），其餘視為重訓後的多次訓練
    - 重訓後一律畫「平均值 + 全距」，不畫單次最佳值。
      單次最佳是挑出來的，會系統性高估真實能力
    - 每張圖都標出 geometry_only 基準線：AcT 要有意義，必須明顯優於「完全不用 AcT」

用法：
    ai/.venv/bin/python ai/train/plot_eval.py
    ai/.venv/bin/python ai/train/plot_eval.py --json ai/train/eval_results/eval-xxx.json
"""

import argparse
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib import font_manager  # noqa: E402

_AI_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DIR = _AI_DIR / "train" / "eval_results"

# 指標定義：(JSON key, 顯示名稱, 是否越低越好)
METRICS = [
    ("normal_fpr", "正常影片誤報率", True),
    ("fall_recall", "跌倒幀召回率", False),
    ("forward_recall", "前跌幀召回率", False),
    ("post_fall_fpr", "非跌落段誤報率", True),
]
STRATEGY_LABELS = {
    "act_only": "AcT 隔離",
    "pipeline_geo_first": "管線 geo-first",
    "pipeline_current": "管線 current",
}
COLOR_BEFORE = "#c0392b"
COLOR_AFTER = "#2471a3"
COLOR_GEOMETRY = "#7f8c8d"


def setup_font():
    """挑一個系統有的中文字型，避免標籤變豆腐字。"""
    available = {f.name for f in font_manager.fontManager.ttflist}
    for candidate in ("PingFang HK", "PingFang SC", "Heiti TC", "Arial Unicode MS"):
        if candidate in available:
            plt.rcParams["font.sans-serif"] = [candidate]
            break
    plt.rcParams["axes.unicode_minus"] = False


def latest_json(directory):
    files = sorted(Path(directory).glob("eval-*.json"))
    if not files:
        raise FileNotFoundError(f"{directory} 裡沒有 eval-*.json，先跑 evaluate_act.py")
    return files[-1]


def collect(report, strategy, key):
    """回傳 (baseline 值, 重訓後各次的值 list)。"""
    names = list(report["results"].keys())
    baseline = report["results"][names[0]][strategy][key]
    after = [report["results"][n][strategy][key] for n in names[1:]]
    return baseline, after


def plot_overview(report, out_path):
    """主圖：三種策略 × 四個指標，重訓前 vs 重訓後（平均＋全距）。"""
    strategies = [s for s in report["strategies"] if s in STRATEGY_LABELS]
    figure, axes = plt.subplots(1, len(strategies), figsize=(5.2 * len(strategies), 5.4))
    if len(strategies) == 1:
        axes = [axes]

    positions = np.arange(len(METRICS))
    width = 0.36
    for axis, strategy in zip(axes, strategies):
        before_values, after_means, after_errors = [], [], []
        for key, _, _ in METRICS:
            baseline, after = collect(report, strategy, key)
            before_values.append(baseline * 100)
            mean = float(np.mean(after)) * 100
            after_means.append(mean)
            # 誤差棒畫全距（最小到最大），比標準差更誠實地表達「跑幾次會落在哪」
            after_errors.append([mean - min(after) * 100, max(after) * 100 - mean])

        axis.bar(positions - width / 2, before_values, width,
                 label="重訓前", color=COLOR_BEFORE, alpha=0.85)
        axis.bar(positions + width / 2, after_means, width,
                 yerr=np.array(after_errors).T, capsize=4,
                 label=f"重訓後（{len(collect(report, strategy, 'fall_recall')[1])} 次平均）",
                 color=COLOR_AFTER, alpha=0.85)

        for index, value in enumerate(before_values):
            axis.text(index - width / 2, value + 1.5, f"{value:.1f}", ha="center", fontsize=8)
        for index, value in enumerate(after_means):
            axis.text(index + width / 2, value + 1.5, f"{value:.1f}", ha="center", fontsize=8)

        axis.set_title(STRATEGY_LABELS[strategy], fontsize=13, pad=10)
        axis.set_xticks(positions)
        axis.set_xticklabels([f"{name}\n({'↓' if lower else '↑'})"
                              for _, name, lower in METRICS], fontsize=9)
        axis.set_ylim(0, 105)
        axis.set_ylabel("百分比 (%)")
        axis.grid(axis="y", alpha=0.25, linestyle="--")
        axis.legend(fontsize=9, loc="upper right")

    figure.suptitle("AcT 重訓前後對照（test split：受試者 S2/S5/S10，30 支影片）",
                    fontsize=15, y=0.99)
    figure.text(0.5, 0.005,
                "↓ 越低越好　↑ 越高越好　｜　誤差棒為多次訓練的全距（最小～最大）",
                ha="center", fontsize=9, color="#555")
    figure.tight_layout(rect=[0, 0.03, 1, 0.96])
    figure.savefig(out_path, dpi=150)
    plt.close(figure)


def plot_variance(report, out_path):
    """離散度圖：每次訓練是一個點，看指標穩不穩定。"""
    names = list(report["results"].keys())[1:]
    strategy = "act_only"
    figure, axes = plt.subplots(1, len(METRICS), figsize=(4.0 * len(METRICS), 4.6))

    for axis, (key, label, lower_better) in zip(axes, METRICS):
        baseline, after = collect(report, strategy, key)
        values = np.array(after) * 100
        axis.scatter(np.arange(len(values)), values, s=90, color=COLOR_AFTER,
                     zorder=3, label="各次訓練")
        axis.axhline(float(values.mean()), color=COLOR_AFTER, linestyle="-",
                     alpha=0.5, label=f"平均 {values.mean():.1f}%")
        axis.axhline(baseline * 100, color=COLOR_BEFORE, linestyle="--",
                     label=f"重訓前 {baseline * 100:.1f}%")
        geometry = report["baselines"]["geometry_only"][key] * 100
        axis.axhline(geometry, color=COLOR_GEOMETRY, linestyle=":",
                     label=f"純幾何 {geometry:.1f}%")

        axis.set_title(f"{label}\n({'越低越好' if lower_better else '越高越好'})", fontsize=11)
        axis.set_xticks(np.arange(len(names)))
        axis.set_xticklabels([n.replace("act_", "") for n in names], rotation=45,
                             ha="right", fontsize=8)
        axis.grid(axis="y", alpha=0.25, linestyle="--")
        axis.legend(fontsize=7.5, loc="best")
        span = values.max() - values.min()
        axis.set_ylim(max(-2, min(values.min(), baseline * 100, geometry) - max(span, 5)),
                      max(values.max(), baseline * 100, geometry) + max(span, 5) + 2)

    figure.suptitle("各次訓練的離散度（AcT 隔離評估）—— 看數字穩不穩定，而非單次最佳",
                    fontsize=14, y=0.99)
    figure.tight_layout(rect=[0, 0, 1, 0.93])
    figure.savefig(out_path, dpi=150)
    plt.close(figure)


def parse_args():
    parser = argparse.ArgumentParser(description="把評估結果畫成 PNG")
    parser.add_argument("--json", default=None, help="指定 eval JSON（預設取最新一份）")
    parser.add_argument("--out-dir", default=str(DEFAULT_DIR))
    return parser.parse_args()


def main():
    args = parse_args()
    setup_font()
    json_path = Path(args.json) if args.json else latest_json(args.out_dir)
    report = json.loads(json_path.read_text(encoding="utf-8"))
    if len(report["results"]) < 2:
        print("❌ 至少要有 2 顆模型才畫得出對照圖", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir)
    stem = json_path.stem
    overview_path = out_dir / f"{stem}-overview.png"
    variance_path = out_dir / f"{stem}-variance.png"
    plot_overview(report, overview_path)
    plot_variance(report, variance_path)

    print(f"📊 {overview_path}")
    print(f"📊 {variance_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
