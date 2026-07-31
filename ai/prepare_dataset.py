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

## 兩種產出：偵測 與 姿態（`--task`）

同一份原始標註要清成兩種格式，因為 RT-DETR 看不懂關節點、YOLO-Pose 沒有關節點就
訓練不了。兩者共用同一套清洗規則與同一套切分演算法，只差「關節點留不留」。

    來源                              --task detect（預設）      --task pose
    active_learning_dataset/
      images/           ─── 共用 ──>  detection_dataset/        pose_dataset/
      labels/       ────────────────>   images/ labels/ ← 5 欄
      pose_labels/  ──────────────────────────────────────>  images/ labels/ ← 56 欄
                                        train.txt val.txt       train.txt val.txt
                                        _quarantine/            _quarantine/
                       ai/dataset_splits/（**這個進版控**）
                                        train.txt val.txt   pose_train.txt pose_val.txt

`ai/data.yaml` 指向前者、`ai/pose_data.yaml` 指向後者。
原始的 `active_learning_dataset/` 一個位元都不動（清洗是複製出去做的）。

pose 模式多兩道限制：**關節點必須剛好 17 組**（對上 `kpt_shape: [17, 3]`，不足或多出
都是格式不合的標註），以及**只收 class 0（person）**——YOLO-Pose 是單類別任務，
`nc: 1`，收進 chair/sofa 只會讓 class id 語意錯位。純 5 欄的偵測標註在 pose 模式會被
丟掉（它沒有關節點，餵進去 ultralytics 會拿到全 0 的骨架當成監督訊號）。

## 為什麼要切 train/val

上游的 `data.yaml` 把 `train:` 與 `val:` 指到同一個 `images/` 目錄，等於拿念過的題目
考自己，mAP 會虛高、拿來對門檻沒有意義。這裡切 80/20，val 不參與訓練。

## 切分演算法：平衡抽樣（`--split-strategy balanced`，預設）

移植自 `origin/albert_chiang:Fall/tools/clearml_train_pipeline.py` 的
「Stratified Split by Rarest Class」，解類別不平衡：

1. 統計每個類別在全部標註裡出現幾次
2. 每張圖的**主類別**＝它出現過的類別中**全域最稀有**的那個
3. 依主類別分組，每組**各自**切 80/20 再合併

為什麼要這樣：本專案的類別分佈很偏（實測 tv 179 個框、sofa 只有 5 個）。純隨機切
80/20 時，只出現在 5 張圖裡的 sofa 很可能**整組落在 train**（機率約 0.8⁵≈33%）或
整組落在 val。前者讓 val 完全評估不到這個類別、mAP 虛高；後者讓模型根本沒學過它，
那一類必定 0 分。按主類別分組後，每個類別都保證同時出現在兩邊。

**與上游的四處差異**：

1. 上游每組換一次 seed（`random.seed(42 + p_cls)`），本專案用單一 seed 打亂已排序的
   清單——同一個 seed 在任何機器上都切出同一組，這是 `dataset_splits/` 進版控的前提。
2. 上游用 `int(len * 0.8)` 截斷，一張圖的小組會變成 train=0、val=1，**最稀有的那個
   類別反而完全沒進訓練集**——正好打死這個演算法要解的問題。這裡改成 `round()`
   並強制「每組至少留 1 張給 train」：稀有類別寧可 val 評估不到，也不能讓模型沒學過。
3. 上游沒有處理「沒有任何標註的圖」（主類別 -1）；這裡那種圖在清洗階段就被隔離了。
4. **「稀有」算的是「幾張圖含這個類別」，不是上游的「總共幾個框」。** 因為切分切的是
   圖，脆弱的是「只有 2 張圖帶著這個類別」而不是「只有 2 個框」——一個類別就算有 100
   個框、全擠在 2 張圖裡，隨機切分照樣可能讓它整組落到同一邊。按框數算會把這種情況
   誤判成常見類別而不去保護它。

`--split-strategy random` 可退回舊的純隨機切分。留這條路是因為 `ai/MLOPS.md` 記錄的
mAP50=0.9912 是用舊切分跑出來的，要重現那個數字得用同一套切法。

用法：
    python ai/prepare_dataset.py                       # 偵測資料集（RT-DETR）
    python ai/prepare_dataset.py --task pose           # 姿態資料集（YOLO-Pose）
    python ai/prepare_dataset.py --val-ratio 0.3 --seed 42
    python ai/prepare_dataset.py --split-strategy random   # 舊的純隨機切分
    python ai/prepare_dataset.py --dry-run             # 只印統計，不寫任何檔案
"""
import argparse
import os
import random
import shutil
import sys
from collections import Counter, defaultdict

from mlops_paths import (AI_DIR, DATASET_DIR, POSE_DATASET_DIR, RAW_DATASET_DIR,
                         RAW_LABELS_DIR, RAW_POSE_LABELS_DIR, SPLITS_DIR)

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp")
DEFAULT_SEED = 20260729
DEFAULT_VAL_RATIO = 0.2

# 與 ai/data.yaml 的 names 對齊；超出範圍的 class id 一律丟棄
NUM_CLASSES = 5

# YOLO-Pose 的關節點數，對上 ai/pose_data.yaml 的 kpt_shape: [17, 3]（COCO 17 點）
NUM_KEYPOINTS = 17
# YOLO-Pose 是單類別任務，只認 person。這個值必須是 ai/data.yaml 裡 person 的 class id。
POSE_CLASS_ID = 0


def dataset_dir_for(task: str) -> str:
    return POSE_DATASET_DIR if task == "pose" else DATASET_DIR


def splits_prefix_for(task: str) -> str:
    """pose 的切分名單加前綴，才不會蓋掉偵測那組（兩者都在 dataset_splits/ 底下）。"""
    return "pose_" if task == "pose" else ""


class Stats(Counter):
    def show(self, title: str, keys: list[str]) -> None:
        print(f"\n{title}")
        for k in keys:
            print(f"  {k:<28} {self[k]}")


def clean_label_lines(raw: str, stats: Stats, task: str = "detect") -> list[str]:
    """把一份標註檔的內容清成合法的標註行。

    `task="detect"` 產出 5 欄偵測標註；`task="pose"` 保留關節點產出 56 欄姿態標註。
    兩者共用同一套「這行資料是不是垃圾」的判斷，差別只在最後輸出什麼。
    """
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

        kpts_raw: list[tuple[str, ...]] = []
        if is_pose:
            kpts_raw = [tuple(parts[i:i + 3]) for i in range(5, len(parts), 3)]
            # 真實姿態不可能 17 個關節點疊在同一點 → 這是寫死的假標註，整行丟掉。
            # 不截成前 5 欄，那會產出一個看起來合理但捏造的框（見檔頭說明）。
            if len(kpts_raw) > 1 and len(set(kpts_raw)) == 1:
                stats["丟棄・寫死的假 pose 行"] += 1
                continue

        if task == "pose":
            # 純偵測標註沒有關節點，餵給 YOLO-Pose 等於給它一副全 0 的骨架當答案
            if not is_pose:
                stats["丟棄・pose 模式：這行沒有關節點"] += 1
                continue
            if len(kpts_raw) != NUM_KEYPOINTS:
                stats[f"丟棄・pose 模式：關節點不是 {NUM_KEYPOINTS} 組"] += 1
                continue
            if cls_id != POSE_CLASS_ID:
                stats["丟棄・pose 模式：非 person 類別"] += 1
                continue
        elif is_pose:
            stats["轉換・pose 降維成偵測框"] += 1

        if not 0 <= cls_id < NUM_CLASSES:
            stats["丟棄・class id 超出範圍"] += 1
            continue
        cx, cy, w, h = box
        if not (0 < w <= 1 and 0 < h <= 1 and 0 <= cx <= 1 and 0 <= cy <= 1):
            stats["丟棄・座標超出 [0,1]"] += 1
            continue

        if task == "pose":
            kpts = parse_keypoints(kpts_raw, stats)
            if kpts is None:
                continue
            fields = " ".join(f"{v:.6f}" for v in kpts)
            stats["保留・合法標註"] += 1
            stats[f"類別 {cls_id}"] += 1
            out.append(f"{POSE_CLASS_ID} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f} {fields}")
            continue

        stats["保留・合法標註"] += 1
        stats[f"類別 {cls_id}"] += 1
        out.append(f"{cls_id} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
    return out


def parse_keypoints(kpts_raw: list[tuple[str, ...]], stats: Stats) -> list[float] | None:
    """把 17 組 (x, y, visibility) 字串解析成 51 個浮點數；解不了回 None。

    座標**夾回 [0,1] 而不是丟棄**：關節點落在畫面外一點點是真實標註的常態
    （手伸出鏡頭邊緣），為此丟掉整個人太浪費。visibility 只認 0/1/2，
    其他值一律當 0（未標註）——ultralytics 讀到範圍外的 v 不會報錯，
    會當成「可見」去算 loss，那是拿雜訊當監督訊號。
    """
    flat: list[float] = []
    for kx, ky, kv in kpts_raw:
        try:
            x, y, v = float(kx), float(ky), int(float(kv))
        except ValueError:
            stats["丟棄・pose 模式：關節點數值解析失敗"] += 1
            return None
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            stats["夾回・關節點座標超出 [0,1]"] += 1
            x, y = min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0)
        if v not in (0, 1, 2):
            stats["修正・visibility 非 0/1/2 當成未標註"] += 1
            v = 0
        flat.extend((x, y, float(v)))
    return flat


def build_dataset(stats: Stats, task: str, dry_run: bool) -> dict[str, set[int]]:
    """清洗 raw → 目標資料集目錄，回傳 {可用圖片檔名: 該圖出現過的 class id 集合}。

    回傳型別帶著類別集合而不只是檔名，是因為平衡抽樣要靠它決定每張圖的主類別。
    在這裡順手收集，比切分階段再把標註檔讀第二遍便宜也少一個不同步的機會。
    """
    src_images = os.path.join(RAW_DATASET_DIR, "images")
    src_labels = RAW_POSE_LABELS_DIR if task == "pose" else RAW_LABELS_DIR
    if not os.path.isdir(src_images):
        sys.exit(f"❌ 找不到來源資料集：{src_images}\n"
                 f"   這是執行時產物（.gitignore 排除），要先跑過 AI 端讓它落地，"
                 f"或跟組員取得。")
    if not os.path.isdir(src_labels):
        sys.exit(f"❌ 找不到標註目錄：{src_labels}\n"
                 + ("   pose 標註是 ai/pose_to_labelstudio_sdk.py 把人工標的骨架拉回來寫的，\n"
                    "   先跑過它（或跟組員取得）再回來清洗。"
                    if task == "pose" else
                    "   偵測標註由 ai/inference_to_labelstudio_sdk.py 拉回本地。"))

    out_dir = dataset_dir_for(task)
    dst_images = os.path.join(out_dir, "images")
    dst_labels = os.path.join(out_dir, "labels")
    quarantine = os.path.join(out_dir, "_quarantine")
    if not dry_run:
        # 每次重跑都從乾淨狀態開始，避免上一輪的殘留混進來
        if os.path.exists(out_dir):
            shutil.rmtree(out_dir)
        for d in (dst_images, dst_labels, os.path.join(quarantine, "images")):
            os.makedirs(d, exist_ok=True)

    usable: dict[str, set[int]] = {}
    for fname in sorted(os.listdir(src_images)):
        if not fname.lower().endswith(IMAGE_EXTS):
            continue
        stem = os.path.splitext(fname)[0]
        stats["來源圖片"] += 1

        label_src = os.path.join(src_labels, f"{stem}.txt")
        if not os.path.isfile(label_src):
            stats["隔離・沒有對應標註"] += 1
            if not dry_run:
                shutil.copy2(os.path.join(src_images, fname),
                             os.path.join(quarantine, "images", fname))
            continue

        with open(label_src, encoding="utf-8", errors="replace") as f:
            lines = clean_label_lines(f.read(), stats, task)

        if not lines:
            # 清完一個框都不剩＝這張圖沒有可用的監督訊號，排除，不要餵給訓練
            stats["隔離・清完 0 個框"] += 1
            if not dry_run:
                shutil.copy2(os.path.join(src_images, fname),
                             os.path.join(quarantine, "images", fname))
            continue

        if not dry_run:
            shutil.copy2(os.path.join(src_images, fname), os.path.join(dst_images, fname))
            with open(os.path.join(dst_labels, f"{stem}.txt"), "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        usable[fname] = {int(line.split()[0]) for line in lines}
        stats["可用圖片"] += 1

    return usable


def _primary_class(classes: set[int], global_counts: Counter) -> int:
    """一張圖的主類別＝它出現過的類別裡「全域最稀有」的那個。

    同票時取較小的 class id，純粹為了讓結果與機器無關（set 的迭代順序不保證）。
    """
    if not classes:
        return -1
    return min(classes, key=lambda c: (global_counts[c], c))


def balanced_split(usable: dict[str, set[int]], val_ratio: float,
                   seed: int, stats: Stats) -> tuple[list[str], list[str]]:
    """依主類別分組後各組各自切 80/20（Stratified Split by Rarest Class）。"""
    global_counts = Counter()
    for classes in usable.values():
        global_counts.update(classes)

    groups: dict[int, list[str]] = defaultdict(list)
    for name, classes in usable.items():
        groups[_primary_class(classes, global_counts)].append(name)

    rng = random.Random(seed)
    train: list[str] = []
    val: list[str] = []
    for p_cls in sorted(groups):
        items = sorted(groups[p_cls])   # 先排序，同一個 seed 才會在任何機器上切出同一組
        rng.shuffle(items)
        # 每組至少留 1 張給 train：稀有類別寧可 val 評估不到，也不能讓模型完全沒學過
        n_val = min(round(len(items) * val_ratio), len(items) - 1)
        val.extend(items[:n_val])
        train.extend(items[n_val:])
        stats[f"分組・主類別 {p_cls}"] = f"{len(items)} 張 → train {len(items) - n_val} / val {n_val}"
    return sorted(train), sorted(val)


def random_split(usable: dict[str, set[int]], val_ratio: float,
                 seed: int) -> tuple[list[str], list[str]]:
    """舊的純隨機切分。留著是為了重現 MLOPS.md 記錄的既有數字（見檔頭）。"""
    names = sorted(usable)
    rng = random.Random(seed)
    rng.shuffle(names)
    n_val = max(1, round(len(names) * val_ratio)) if names else 0
    return sorted(names[n_val:]), sorted(names[:n_val])


def write_splits(usable: dict[str, set[int]], val_ratio: float, seed: int,
                 strategy: str, task: str, dry_run: bool, stats: Stats) -> None:
    """切 train/val，寫兩份：進版控的檔名清單 + 給 ultralytics 的絕對路徑清單。"""
    if strategy == "balanced":
        train, val = balanced_split(usable, val_ratio, seed, stats)
    else:
        train, val = random_split(usable, val_ratio, seed)

    stats["train 張數"] = len(train)
    stats["val 張數"] = len(val)
    if dry_run:
        return

    out_dir = dataset_dir_for(task)
    prefix = splits_prefix_for(task)
    os.makedirs(SPLITS_DIR, exist_ok=True)
    header = (f"# 由 ai/prepare_dataset.py 產生"
              f"（task={task}, strategy={strategy}, seed={seed}, val_ratio={val_ratio}）。\n"
              f"# 只放檔名不放路徑，換一台機器照樣可重現同一組切分。\n")
    for split_name, items in (("train", train), ("val", val)):
        with open(os.path.join(SPLITS_DIR, f"{prefix}{split_name}.txt"),
                  "w", encoding="utf-8") as f:
            f.write(header)
            f.write("\n".join(items) + "\n")
        # ultralytics 讀的那份：絕對路徑，放在資料集目錄裡（不進 repo）
        with open(os.path.join(out_dir, f"{split_name}.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(os.path.join(out_dir, "images", n) for n in items) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="清洗主動學習資料集並切 train/val")
    ap.add_argument("--task", choices=("detect", "pose"), default="detect",
                    help="detect＝RT-DETR 的偵測資料集（預設）；pose＝YOLO-Pose 的姿態資料集")
    ap.add_argument("--val-ratio", type=float, default=DEFAULT_VAL_RATIO,
                    help=f"val 佔比（預設 {DEFAULT_VAL_RATIO}）")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED,
                    help=f"切分亂數種子（預設 {DEFAULT_SEED}）——固定才可重現")
    ap.add_argument("--split-strategy", choices=("balanced", "random"), default="balanced",
                    help="balanced＝依最稀有類別分組後各組切 80/20（預設）；random＝舊的純隨機")
    ap.add_argument("--dry-run", action="store_true",
                    help="只印統計，不寫任何檔案（不會動到 dataset_splits/）")
    args = ap.parse_args()

    out_dir = dataset_dir_for(args.task)
    print(f"任務：{args.task}（切分策略 {args.split_strategy}）")
    print(f"來源：{os.path.relpath(RAW_DATASET_DIR, AI_DIR)}")
    print(f"產出：{os.path.relpath(out_dir, AI_DIR)}"
          + ("（dry-run，不寫檔）" if args.dry_run else ""))

    stats = Stats()
    usable = build_dataset(stats, args.task, args.dry_run)
    write_splits(usable, args.val_ratio, args.seed, args.split_strategy,
                 args.task, args.dry_run, stats)

    stats.show("── 標註行 ──", [
        "保留・合法標註", "轉換・pose 降維成偵測框",
        "丟棄・寫死的假 pose 行", "丟棄・註解行", "丟棄・欄位數不合法",
        "丟棄・數值解析失敗", "丟棄・class id 超出範圍", "丟棄・座標超出 [0,1]",
        "丟棄・pose 模式：這行沒有關節點",
        f"丟棄・pose 模式：關節點不是 {NUM_KEYPOINTS} 組",
        "丟棄・pose 模式：非 person 類別", "丟棄・pose 模式：關節點數值解析失敗",
        "夾回・關節點座標超出 [0,1]", "修正・visibility 非 0/1/2 當成未標註",
    ])
    stats.show("── 圖片 ──", [
        "來源圖片", "可用圖片", "隔離・清完 0 個框", "隔離・沒有對應標註",
        "train 張數", "val 張數",
    ])
    stats.show("── 各類別標註數 ──",
               [f"類別 {i}" for i in range(NUM_CLASSES) if stats[f"類別 {i}"]])
    if args.split_strategy == "balanced":
        stats.show("── 平衡抽樣分組 ──",
                   sorted(k for k in stats if k.startswith("分組・")))

    if not usable:
        print("\n❌ 清洗後沒有任何可用圖片，訓練不會有意義")
        return 1
    if args.dry_run:
        print("\nℹ️ dry-run：沒有寫出任何檔案")
        return 0

    prefix = splits_prefix_for(args.task)
    print(f"\n✅ 切分名單已寫入 {os.path.relpath(SPLITS_DIR, AI_DIR)}/"
          f"{prefix}train.txt、{prefix}val.txt（這份進版控）")
    print("   接著可以訓練：python ai/"
          + ("clearml_pose_train_pipeline.py" if args.task == "pose"
             else "clearml_train_pipeline.py"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
