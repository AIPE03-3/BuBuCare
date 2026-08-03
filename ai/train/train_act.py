#!/usr/bin/env python3
"""訓練 AcT（時序跌倒分類器）。

⚠ 三條不可違反的規則，違反了數字會好看但結論無效：
   1. 模型架構 import 自 `local_pipeline_eval`，與 `inference_test.py:309` 逐字一致。
      架構不一致 → 權重載不進正式管線，或載進去但語意不同。
   2. 檔案清單一律讀 `splits.json`，**不 glob videos/**。
      glob 會把測試集與被排除的鏡像檔一起吃進訓練。
   3. 鏡像檔（S>10）的標註取自來源檔——水平翻轉不改時間軸。
      見 `dataset_utils.label_source_stem()`。

視窗標籤規則（見 ai/docs/2026-07-29-act-retrain-plan.md 5.5 節）：
    視窗 30 幀（3 秒）遠比跌落動作（0.5~1.6 秒）長，
    所以判準是「這個視窗有沒有涵蓋整場跌倒」，不是「視窗有幾成是跌倒」。
        視窗 ∩ 跌落 ≥ 跌落長度 × POSITIVE_COVERAGE → 正樣本（class 0）
        視窗 ∩ 跌落 = 0                            → 負樣本（class 1）
        其餘（只看到半場）                          → 丟棄

用法：
    ai/.venv/bin/python ai/train/train_act.py
    ai/.venv/bin/python ai/train/train_act.py --epochs 200 --stride 1
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

_AI_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_AI_DIR))

from local_pipeline_eval import (  # noqa: E402
    WINDOW_SIZE, ActionTransformer, parse_label_file, pick_device,
)
from pose_features import DEFAULT_FEATURE_NORM, FEATURE_NORMS  # noqa: E402
import dataset_utils as du  # noqa: E402

DEFAULT_DATASET = _AI_DIR / "train" / "dataset"
DEFAULT_OUT = _AI_DIR / "action_transformer_v2.pth"

FRAME_SKIP = 2      # 與 extract_features.py 一致
SOURCE_FPS = 20.0   # CAUCAFall 全部 20fps（已驗證 100 支）
CLASS_FALL, CLASS_NORMAL = 0, 1   # 對齊 inference_test.py 的 index 語意
POSITIVE_COVERAGE = 0.8           # 視窗要涵蓋跌落的幾成才算正樣本


def load_fall_spans(dataset_dir, stem):
    """讀這支影片的跌落區間，回傳處理幀座標的 [(start, end), …]。

    回傳 None 表示「這支是跌倒影片但沒有標註」——必須跳過，不能當成沒跌倒，
    否則會把真跌倒餵成負樣本。
    """
    if not du.is_fall_video(stem):
        return []
    label_path = du.label_path_for(dataset_dir, stem)
    if not label_path.is_file():
        return None
    segments = parse_label_file(label_path, SOURCE_FPS)
    if not segments:
        return None
    return [(start // FRAME_SKIP, end // FRAME_SKIP) for start, end in segments]


def make_windows(features, spans, stride, valid=None, min_valid_ratio=0.0):
    """把逐幀特徵切成視窗並貼標籤。回傳 (X, y, 因偵測率被丟棄的視窗數)。

    `min_valid_ratio` 過濾 pose 偵測率過低的視窗：那些視窗裡大量是全零向量
    （沒偵測到人），對模型而言是雜訊而非訊號。實測鏡像檔的偵測率中位只比來源
    低 1%，但尾端有掉到 -34% 的（YOLO 對鏡像影像的偵測本來就不完全對稱），
    在視窗層級過濾比整支丟掉精確。
    """
    windows, labels = [], []
    total = len(features)
    dropped_low_detection = 0
    for start in range(0, total - WINDOW_SIZE + 1, stride):
        end = start + WINDOW_SIZE
        if valid is not None and min_valid_ratio > 0:
            if float(valid[start:end].mean()) < min_valid_ratio:
                dropped_low_detection += 1
                continue
        best_ratio = 0.0
        overlapped = False
        for span_start, span_end in spans:
            span_length = max(1, span_end - span_start)
            overlap = max(0, min(end, span_end) - max(start, span_start))
            if overlap > 0:
                overlapped = True
                best_ratio = max(best_ratio, overlap / span_length)

        if best_ratio >= POSITIVE_COVERAGE:
            label = CLASS_FALL
        elif not overlapped:
            label = CLASS_NORMAL
        else:
            continue  # 只看到半場跌倒，標什麼都不對，丟掉
        windows.append(features[start:end])
        labels.append(label)
    return windows, labels, dropped_low_detection


def build_split(dataset_dir, splits, split_name, stride, min_valid_ratio=0.0,
                exclude_flipped=False, feature_norm=DEFAULT_FEATURE_NORM):
    """組出一個 split 的訓練樣本。回傳 (X, y, 統計 dict)。

    `exclude_flipped` 用來做鏡像增強的消融——不排除的話，無從證明鏡像有沒有貢獻。
    """
    features_dir = du.features_dir(dataset_dir, feature_norm)
    all_windows, all_labels = [], []
    stats = {"videos": 0, "missing_features": [], "missing_labels": [],
             "draft_labels": set(), "dropped_low_detection": 0, "excluded_flipped": 0,
             "wrong_norm": []}

    for name in du.split_files(splits, split_name):
        stem = Path(name).stem
        if exclude_flipped and du.is_flipped(stem):
            stats["excluded_flipped"] += 1
            continue
        feature_path = features_dir / f"{stem}.npz"
        if not feature_path.is_file():
            stats["missing_features"].append(stem)
            continue

        spans = load_fall_spans(dataset_dir, stem)
        if spans is None:
            stats["missing_labels"].append(stem)
            continue
        if spans and du.is_draft_label(du.label_path_for(dataset_dir, stem)):
            # 鏡像檔會指向同一份標註，用 set 收斂成「幾份標註」而不是「幾支影片」
            stats["draft_labels"].add(du.label_source_stem(stem))

        stored = np.load(feature_path)
        # 目錄名與內容不符時擋下來。混用兩種正規化訓練出的模型完全沒有意義，
        # 但數值上看不出異常（都是 34 維 float32），不主動檢查就會靜默通過
        if du.read_feature_norm(stored) != feature_norm:
            stats["wrong_norm"].append(stem)
            continue
        features = stored["features"]
        if len(features) < WINDOW_SIZE:
            continue
        windows, labels, dropped = make_windows(
            features, spans, stride, stored.get("valid"), min_valid_ratio
        )
        all_windows.extend(windows)
        all_labels.extend(labels)
        stats["dropped_low_detection"] += dropped
        stats["videos"] += 1

    if not all_windows:
        return None, None, stats
    X = torch.from_numpy(np.asarray(all_windows, dtype=np.float32))
    y = torch.from_numpy(np.asarray(all_labels, dtype=np.int64))
    return X, y, stats


def evaluate(model, loader, device):
    """回傳 (loss, 準確率, 跌倒類 precision, 跌倒類 recall)。"""
    model.eval()
    criterion = nn.CrossEntropyLoss()
    total_loss, total = 0.0, 0
    true_positive, false_positive, false_negative, correct = 0, 0, 0, 0
    with torch.no_grad():
        for batch_x, batch_y in loader:
            batch_x, batch_y = batch_x.to(device), batch_y.to(device)
            logits = model(batch_x)
            total_loss += float(criterion(logits, batch_y)) * len(batch_y)
            predicted = logits.argmax(dim=1)
            correct += int((predicted == batch_y).sum())
            true_positive += int(((predicted == CLASS_FALL) & (batch_y == CLASS_FALL)).sum())
            false_positive += int(((predicted == CLASS_FALL) & (batch_y == CLASS_NORMAL)).sum())
            false_negative += int(((predicted == CLASS_NORMAL) & (batch_y == CLASS_FALL)).sum())
            total += len(batch_y)
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    return total_loss / max(total, 1), correct / max(total, 1), precision, recall


def parse_args():
    parser = argparse.ArgumentParser(description="訓練 AcT 時序跌倒分類器")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--out", default=str(DEFAULT_OUT),
                        help="輸出權重路徑（預設不覆蓋既有的 action_transformer.pth）")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--stride", type=int, default=1, help="視窗滑動步長")
    parser.add_argument("--min-valid-ratio", type=float, default=0.5,
                        help="視窗內 pose 偵測率低於此就丟棄（0 = 不過濾）")
    parser.add_argument("--patience", type=int, default=20, help="val loss 幾輪沒進步就停")
    parser.add_argument("--exclude-flipped", action="store_true",
                        help="訓練時排除鏡像檔（做資料增強的消融對照）")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--feature-norm", default=DEFAULT_FEATURE_NORM, choices=FEATURE_NORMS,
                        help="讀哪一份特徵：image=dataset/features／bbox=dataset/features-bbox。"
                             "會寫進 run.json，推論端必須用同一個")
    return parser.parse_args()


def main():
    args = parse_args()
    dataset_dir = Path(args.dataset).resolve()
    out_path = Path(args.out).resolve()
    if out_path.exists():
        print(f"❌ {out_path} 已存在。請換個 --out，不要覆蓋既有權重"
              f"（那是回滾用的，且不在版控）", file=sys.stderr)
        return 1

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    splits = du.load_splits(dataset_dir)

    print("📦 組訓練樣本…")
    datasets = {}
    draft_counts = {}
    for split_name in ("train", "val"):
        X, y, stats = build_split(dataset_dir, splits, split_name, args.stride,
                                  args.min_valid_ratio,
                                  exclude_flipped=args.exclude_flipped,
                                  feature_norm=args.feature_norm)
        # 正規化不符一律當致命錯誤，不是警告。混著訓練出來的權重毫無意義，
        # 但看起來一切正常——讓它跑完只會產生一份沒人知道是壞的模型
        if stats["wrong_norm"]:
            print(f"❌ {split_name} 有 {len(stats['wrong_norm'])} 支 npz 的 feature_norm "
                  f"不是 {args.feature_norm}：{', '.join(stats['wrong_norm'][:5])}"
                  f"{' …' if len(stats['wrong_norm']) > 5 else ''}", file=sys.stderr)
            print(f"   請重跑：extract_features.py --feature-norm {args.feature_norm} "
                  f"--overwrite", file=sys.stderr)
            return 1
        if X is None:
            print(f"❌ {split_name} 沒有任何可用樣本", file=sys.stderr)
            if stats["missing_features"]:
                print(f"   缺特徵 {len(stats['missing_features'])} 支"
                      f"（先跑 extract_features.py）", file=sys.stderr)
            if stats["missing_labels"]:
                print(f"   缺標註 {len(stats['missing_labels'])} 支"
                      f"（校正初稿後存到 dataset/labels/）", file=sys.stderr)
            return 1
        datasets[split_name] = (X, y)
        fall_count = int((y == CLASS_FALL).sum())
        print(f"  {split_name}: {stats['videos']} 支影片 → {len(y)} 視窗"
              f"（跌倒 {fall_count} / 正常 {len(y) - fall_count}）")
        if stats["missing_labels"]:
            print(f"    ⚠ 缺標註而跳過 {len(stats['missing_labels'])} 支："
                  f"{', '.join(stats['missing_labels'][:5])}"
                  f"{' …' if len(stats['missing_labels']) > 5 else ''}")
        if stats["missing_features"]:
            print(f"    ⚠ 缺特徵而跳過 {len(stats['missing_features'])} 支")
        if stats["excluded_flipped"]:
            print(f"    排除鏡像檔 {stats['excluded_flipped']} 支（消融對照）")
        if stats["dropped_low_detection"]:
            print(f"    偵測率不足而丟棄 {stats['dropped_low_detection']} 個視窗"
                  f"（門檻 {args.min_valid_ratio:.0%}）")
        if stats["draft_labels"]:
            draft_counts[split_name] = len(stats["draft_labels"])
            print(f"    ⚠ 有 {len(stats['draft_labels'])} 份標註還是未校正的初稿"
                  f"（STATUS: DRAFT）")

    if draft_counts:
        total_drafts = sum(draft_counts.values())
        print(f"\n⚠️  警告：{total_drafts} 份標註仍是未校正的初稿。")
        print("   初稿是幾何規則猜的，直接訓練等於拿雜訊當真值——這一輪的數字不可信。")
        print("   校正方式：看 dataset/labels_review/*.jpg，改 dataset/labels/*.txt，")
        print("   校正完把檔案裡的 `# STATUS: DRAFT` 改成 `# STATUS: REVIEWED`。\n")

    train_x, train_y = datasets["train"]
    val_x, val_y = datasets["val"]
    train_loader = DataLoader(TensorDataset(train_x, train_y),
                              batch_size=args.batch_size, shuffle=True)
    val_loader = DataLoader(TensorDataset(val_x, val_y), batch_size=args.batch_size)

    device = pick_device()
    model = ActionTransformer(input_dim=34, seq_len=WINDOW_SIZE, num_classes=2).to(device)

    # 跌倒是少數類，不加權重模型會學成「一律說正常」然後拿高準確率
    class_counts = torch.bincount(train_y, minlength=2).float()
    class_weights = (class_counts.sum() / (2.0 * class_counts.clamp(min=1))).to(device)
    print(f"⚖️  類別權重：跌倒 {class_weights[CLASS_FALL]:.2f} / "
          f"正常 {class_weights[CLASS_NORMAL]:.2f}｜裝置 {device}")

    criterion = nn.CrossEntropyLoss(weight=class_weights)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)

    best_loss, best_state, best_epoch, stale = float("inf"), None, 0, 0
    # 逐輪歷史。只印在終端不留檔的話，之後畫不出收斂曲線，也無從證明有沒有過擬合
    history = []
    print("-" * 68)
    for epoch in range(1, args.epochs + 1):
        model.train()
        epoch_loss, seen = 0.0, 0
        for batch_x, batch_y in train_loader:
            batch_x, batch_y = batch_x.to(device), batch_y.to(device)
            optimizer.zero_grad()
            loss = criterion(model(batch_x), batch_y)
            loss.backward()
            optimizer.step()
            # 用 .detach()：直接 float(loss) 會對還掛在計算圖上的 tensor 取值，torch 會警告
            epoch_loss += float(loss.detach()) * len(batch_y)
            seen += len(batch_y)

        val_loss, val_acc, val_precision, val_recall = evaluate(model, val_loader, device)
        history.append({"epoch": epoch, "train_loss": epoch_loss / max(seen, 1),
                        "val_loss": val_loss, "val_acc": val_acc,
                        "val_precision": val_precision, "val_recall": val_recall})
        if val_loss < best_loss:
            best_loss, best_epoch, stale = val_loss, epoch, 0
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            marker = " ★"
        else:
            stale += 1
            marker = ""
        if epoch % 5 == 0 or marker:
            print(f"epoch {epoch:3d}｜train {epoch_loss / max(seen, 1):.4f}"
                  f"｜val {val_loss:.4f} acc {val_acc:.3f}"
                  f" P {val_precision:.3f} R {val_recall:.3f}{marker}")
        if stale >= args.patience:
            print(f"⏹  val loss 連續 {args.patience} 輪沒進步，早停")
            break

    if best_state is None:
        print("❌ 沒有產生任何有效權重", file=sys.stderr)
        return 1

    model.load_state_dict(best_state)
    val_loss, val_acc, val_precision, val_recall = evaluate(model, val_loader, device)
    torch.save(best_state, out_path)

    run_record = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "weights": str(out_path),
        "best_epoch": best_epoch,
        "val": {"loss": val_loss, "accuracy": val_acc,
                "fall_precision": val_precision, "fall_recall": val_recall},
        "hyperparams": {"epochs": args.epochs, "batch_size": args.batch_size,
                        "lr": args.lr, "stride": args.stride, "seed": args.seed},
        "window_rule": {"window_size": WINDOW_SIZE, "frame_skip": FRAME_SKIP,
                        "positive_coverage": POSITIVE_COVERAGE},
        "samples": {"train": len(train_y), "val": len(val_y),
                    "train_fall": int((train_y == CLASS_FALL).sum()),
                    "val_fall": int((val_y == CLASS_FALL).sum())},
        "exclude_flipped": args.exclude_flipped,
        # 這顆權重只在這個正規化下有意義。推論端（inference_test 的 ACT_FEATURE_NORM、
        # local_pipeline_eval 的 --feature-norm）必須設成一樣，evaluate_act 會擋不一致
        "feature_norm": args.feature_norm,
        "history": history,
        "splits_rules": splits["rules"],
    }
    record_path = out_path.with_suffix(".run.json")
    record_path.write_text(json.dumps(run_record, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")

    print("-" * 68)
    print(f"✅ best epoch {best_epoch}｜val acc {val_acc:.3f}"
          f"｜跌倒 P {val_precision:.3f} R {val_recall:.3f}")
    print(f"💾 {out_path}")
    print(f"📄 {record_path}")
    print("\n⚠ 這是視窗級指標，不是驗收標準。")
    print("   驗收要跑管線級評估：先 export_onnx.py，再用 batch_eval.py 看幀召回率與誤報率。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
