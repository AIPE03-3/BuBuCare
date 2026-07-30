#!/usr/bin/env python3
"""把 `ai/active_learning_dataset/` 清洗成可以直接餵給 RT-DETR 訓練的偵測資料集。

移植自 `origin/albert_chiang:Fall/tools/clean_pose_to_det.py`（43 行），做的事一樣：
把 pose 格式的標註（`class x y w h px1 py1 pv1 …`）降維成純偵測格式（只留前 5 欄），
因為 RT-DETR 看不懂關節點。但上游那份「無條件截前 5 欄」在本專案的資料上會出事，
所以這裡多了三道檢查。

## 為什麼不能照抄「截前 5 欄」

實際掃過 `ai/active_learning_dataset/labels/`（111 個檔）發現兩種垃圾：

1. **20 個檔混了 `# vlm_fall_reason_item: …` 中文註解行** —— 上游腳本的
   `len(parts) >= 5` 剛好會濾掉（那些行只有 3 欄），但那是巧合不是設計。

2. **21 個檔是舊 `vlm_worker` 寫死的假 pose 行**：
   `0 0.500 0.600 0.300 0.500  0.500 0.550 2.0  0.500 0.550 2.0 …`
   17 個關節點座標**完全相同**，每張圖也都一模一樣，與畫面內容無關。
   截成前 5 欄之後會變成 `0 0.500 0.600 0.300 0.500` —— 一個**看起來很合理、其實是
   憑空捏造的框**混進訓練集。這比不收這張圖更糟：拿假標註回訓會讓模型學到錯的東西，
   而且之後完全看不出來是假的（理由同
   `ai/active_learning_dataset/agent_shadow/README.md` 對假標註的說明）。

   偵測規則用「**所有關節點座標完全相同**」而不是比對那串常數 —— 真實姿態不可能 17 個
   關節點疊在同一點，這條規則對變形過的假資料一樣擋得住。

## 產出

    ai/detection_dataset/            ← 訓練真正吃的（機器產物，不進 repo）
      images/  labels/               ← 清洗後只剩合法的 5 欄標註
      train.txt  val.txt             ← 絕對路徑清單，data.yaml 指到這裡
      _quarantine/                   ← 清完 0 個框的圖，不參與訓練
    ai/dataset_splits/               ← **這個進版控**
      train.txt  val.txt             ← 只有檔名，換機器可重現同一組切分

原始的 `active_learning_dataset/` 一個位元都不動（清洗是複製出去做的）。

## 為什麼要切 train/val

上游的 `data.yaml` 把 `train:` 與 `val:` 指到同一個 `images/` 目錄，等於拿念過的題目
考自己，mAP 會虛高、拿來對門檻沒有意義。這裡固定 seed 切 80/20，val 不參與訓練。

用法：
    python ai/prepare_dataset.py              # 清洗 + 切分
    python ai/prepare_dataset.py --val-ratio 0.3 --seed 42
"""
import argparse
import os
import random
import shutil
import sys
from collections import Counter

from mlops_paths import AI_DIR, DATASET_DIR, RAW_DATASET_DIR, SPLITS_DIR

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp")
DEFAULT_SEED = 20260729
DEFAULT_VAL_RATIO = 0.2

# 與 ai/data.yaml 的 names 對齊；超出範圍的 class id 一律丟棄
NUM_CLASSES = 5


class Stats(Counter):
    def show(self, title: str, keys: list[str]) -> None:
        print(f"\n{title}")
        for k in keys:
            print(f"  {k:<28} {self[k]}")


def clean_label_lines(raw: str, stats: Stats) -> list[str]:
    """把一份標註檔的內容清成合法的 5 欄偵測標註。"""
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            stats["丟棄・註解行"] += 1
            continue

        parts = line.split()
        # pose 格式：5 欄框 + 每個關節點 3 欄（x, y, visibility）
        is_pose = len(parts) > 5 and (len(parts) - 5) % 3 == 0
        if len(parts) != 5 and not is_pose:
            stats["丟棄・欄位數不合法"] += 1
            continue

        try:
            cls_id = int(float(parts[0]))
            box = [float(v) for v in parts[1:5]]
        except ValueError:
            stats["丟棄・數值解析失敗"] += 1
            continue

        if is_pose:
            kpts = [tuple(parts[i:i + 3]) for i in range(5, len(parts), 3)]
            # 真實姿態不可能 17 個關節點疊在同一點 → 這是寫死的假標註，整行丟掉。
            # 不截成前 5 欄，那會產出一個看起來合理但捏造的框（見檔頭說明）。
            if len(kpts) > 1 and len(set(kpts)) == 1:
                stats["丟棄・寫死的假 pose 行"] += 1
                continue
            stats["轉換・pose 降維成偵測框"] += 1

        if not 0 <= cls_id < NUM_CLASSES:
            stats["丟棄・class id 超出範圍"] += 1
            continue
        cx, cy, w, h = box
        if not (0 < w <= 1 and 0 < h <= 1 and 0 <= cx <= 1 and 0 <= cy <= 1):
            stats["丟棄・座標超出 [0,1]"] += 1
            continue

        stats["保留・合法標註"] += 1
        stats[f"類別 {cls_id}"] += 1
        out.append(f"{cls_id} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
    return out


def build_dataset(stats: Stats) -> list[str]:
    """清洗 raw → detection_dataset，回傳可用的圖片檔名（不含路徑）。"""
    src_images = os.path.join(RAW_DATASET_DIR, "images")
    src_labels = os.path.join(RAW_DATASET_DIR, "labels")
    if not os.path.isdir(src_images):
        sys.exit(f"❌ 找不到來源資料集：{src_images}\n"
                 f"   這是執行時產物（.gitignore 排除），要先跑過 AI 端讓它落地，"
                 f"或跟組員取得。")

    dst_images = os.path.join(DATASET_DIR, "images")
    dst_labels = os.path.join(DATASET_DIR, "labels")
    quarantine = os.path.join(DATASET_DIR, "_quarantine")
    # 每次重跑都從乾淨狀態開始，避免上一輪的殘留混進來
    if os.path.exists(DATASET_DIR):
        shutil.rmtree(DATASET_DIR)
    for d in (dst_images, dst_labels, os.path.join(quarantine, "images")):
        os.makedirs(d, exist_ok=True)

    usable = []
    for fname in sorted(os.listdir(src_images)):
        if not fname.lower().endswith(IMAGE_EXTS):
            continue
        stem = os.path.splitext(fname)[0]
        stats["來源圖片"] += 1

        label_src = os.path.join(src_labels, f"{stem}.txt")
        if not os.path.isfile(label_src):
            stats["隔離・沒有對應標註"] += 1
            shutil.copy2(os.path.join(src_images, fname),
                         os.path.join(quarantine, "images", fname))
            continue

        with open(label_src, encoding="utf-8", errors="replace") as f:
            lines = clean_label_lines(f.read(), stats)

        if not lines:
            # 清完一個框都不剩＝這張圖沒有可用的監督訊號，排除，不要餵給訓練
            stats["隔離・清完 0 個框"] += 1
            shutil.copy2(os.path.join(src_images, fname),
                         os.path.join(quarantine, "images", fname))
            continue

        shutil.copy2(os.path.join(src_images, fname), os.path.join(dst_images, fname))
        with open(os.path.join(dst_labels, f"{stem}.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        usable.append(fname)
        stats["可用圖片"] += 1

    return usable


def write_splits(usable: list[str], val_ratio: float, seed: int, stats: Stats) -> None:
    """固定 seed 切 train/val，同時寫兩份：進版控的檔名清單 + 給 ultralytics 的絕對路徑清單。"""
    names = sorted(usable)          # 先排序才能保證同一個 seed 每次切出同一組
    rng = random.Random(seed)
    rng.shuffle(names)
    n_val = max(1, round(len(names) * val_ratio)) if names else 0
    val, train = names[:n_val], names[n_val:]

    os.makedirs(SPLITS_DIR, exist_ok=True)
    header = (f"# 由 ai/prepare_dataset.py 產生（seed={seed}, val_ratio={val_ratio}）。\n"
              f"# 只放檔名不放路徑，換一台機器照樣可重現同一組切分。\n")
    for split_name, items in (("train", train), ("val", val)):
        with open(os.path.join(SPLITS_DIR, f"{split_name}.txt"), "w", encoding="utf-8") as f:
            f.write(header)
            f.write("\n".join(sorted(items)) + "\n")
        # ultralytics 讀的那份：絕對路徑，放在 detection_dataset 裡（不進 repo）
        with open(os.path.join(DATASET_DIR, f"{split_name}.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(os.path.join(DATASET_DIR, "images", n)
                              for n in sorted(items)) + "\n")

    stats["train 張數"] = len(train)
    stats["val 張數"] = len(val)


def main() -> int:
    ap = argparse.ArgumentParser(description="清洗主動學習資料集並切 train/val")
    ap.add_argument("--val-ratio", type=float, default=DEFAULT_VAL_RATIO,
                    help=f"val 佔比（預設 {DEFAULT_VAL_RATIO}）")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED,
                    help=f"切分亂數種子（預設 {DEFAULT_SEED}）——固定才可重現")
    args = ap.parse_args()

    print(f"來源：{os.path.relpath(RAW_DATASET_DIR, AI_DIR)}")
    print(f"產出：{os.path.relpath(DATASET_DIR, AI_DIR)}")

    stats = Stats()
    usable = build_dataset(stats)
    write_splits(usable, args.val_ratio, args.seed, stats)

    stats.show("── 標註行 ──", [
        "保留・合法標註", "轉換・pose 降維成偵測框",
        "丟棄・寫死的假 pose 行", "丟棄・註解行", "丟棄・欄位數不合法",
        "丟棄・數值解析失敗", "丟棄・class id 超出範圍", "丟棄・座標超出 [0,1]",
    ])
    stats.show("── 圖片 ──", [
        "來源圖片", "可用圖片", "隔離・清完 0 個框", "隔離・沒有對應標註",
        "train 張數", "val 張數",
    ])
    stats.show("── 各類別標註數 ──",
               [f"類別 {i}" for i in range(NUM_CLASSES) if stats[f"類別 {i}"]])

    if not usable:
        print("\n❌ 清洗後沒有任何可用圖片，訓練不會有意義")
        return 1
    print(f"\n✅ 切分名單已寫入 {os.path.relpath(SPLITS_DIR, AI_DIR)}/（這份進版控）")
    print(f"   接著可以訓練：python ai/clearml_train_pipeline.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
