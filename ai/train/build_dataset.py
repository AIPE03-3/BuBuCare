#!/usr/bin/env python3
"""把原始素材與鏡像素材整併成單一資料集，並產出切分定義。

背景見 `ai/docs/2026-07-29-act-retrain-plan.md` 第 5 章。

設計取捨：**切分寫進 `splits.json`，不用資料夾表達。**
    受試者編號就寫在檔名裡（`FallForwardS7` → S7），切分規則能直接算出來。
    用目錄位置去表達切分，會讓「改切分」變成「重搬 200 個檔案」，而且搬錯不可逆。
    資料放一份、切分是 metadata——要調整切分只需改本檔上方的 SPLIT_SUBJECTS。

⚠ 鏡像資料的鐵則（這是本腳本存在的主要理由）：
    `S<n+10>` 是 `S<n>` 的水平鏡像，**是同一個人**。
    若把 S1 放 train、S11 放 test，測試集就洩漏了，而且從指標上完全看不出來。
    因此鏡像檔只會被分配到「來源受試者所屬的 split」，
    且**只有 train 的鏡像會被採用**——驗證集與測試集不做資料增強。

用法：
    ai/.venv/bin/python ai/train/build_dataset.py            # 實際整併（搬移）
    ai/.venv/bin/python ai/train/build_dataset.py --dry-run  # 只看會做什麼
    ai/.venv/bin/python ai/train/build_dataset.py --copy     # 複製而非搬移（保留來源）
"""

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

_AI_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SOURCES = [_AI_DIR / "train" / "train_data", _AI_DIR / "train" / "train_data_flipped"]
DEFAULT_DEST = _AI_DIR / "train" / "dataset"

VIDEO_SUFFIXES = {".mp4", ".avi", ".mov", ".mkv"}
_SUBJECT_PATTERN = re.compile(r"S(\d+)$", re.IGNORECASE)

# ── 切分定義（唯一的真實來源，要改切分改這裡）──────────────────────────────
# 依 ai/docs/2026-07-29-act-retrain-plan.md 5.6 節：
# test 選 S2/S5/S10，是因為原本 ai/test_demo/ 那 13 支基準影片全落在這三個受試者，
# 其中 4 支跌倒基準（前跌/後跌/左跌/右跌）剛好一支不漏。
SPLIT_SUBJECTS = {
    "train": [1, 3, 4, 6, 7],
    "val": [8, 9],
    "test": [2, 5, 10],
}
# 鏡像檔的受試者編號偏移，要與 flip_videos.py 的 --renumber-offset 一致
FLIP_OFFSET = 10
# 哪些 split 可以使用鏡像增強。測試集與驗證集必須維持原始分布，不得增強。
SPLITS_ALLOWING_FLIP = {"train"}
# ─────────────────────────────────────────────────────────────────────────


def parse_subject(stem):
    """從檔名取出受試者編號（int）。取不到回 None。"""
    match = _SUBJECT_PATTERN.search(stem)
    return int(match.group(1)) if match else None


def build_subject_index():
    """算出「受試者編號 → (split, 是否為鏡像)」的對照。

    把規則展開成一張表，後面分派檔案時就只是查表，不必到處寫 if。
    未被採用的鏡像（val/test 的鏡像）標成 split=None，理由記在 excluded。
    """
    index = {}
    for split_name, subjects in SPLIT_SUBJECTS.items():
        for subject in subjects:
            index[subject] = (split_name, False)
            flipped_subject = subject + FLIP_OFFSET
            if split_name in SPLITS_ALLOWING_FLIP:
                index[flipped_subject] = (split_name, True)
            else:
                index[flipped_subject] = (None, True)
    return index


def collect_videos(source_dirs):
    """遞迴掃出所有影片檔。回傳排序後的清單。"""
    videos = []
    for source_dir in source_dirs:
        if not source_dir.is_dir():
            continue
        videos.extend(
            path for path in source_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES
        )
    return sorted(videos, key=lambda path: path.name)


def transfer(source_path, dest_path, copy, dry_run):
    """搬移或複製單一檔案。回傳 (是否處理, 說明)。"""
    if dest_path.exists():
        return False, "已存在"
    if dry_run:
        return True, "dry-run"
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if copy:
        shutil.copy2(source_path, dest_path)
    else:
        shutil.move(str(source_path), str(dest_path))
    return True, ""


def write_splits(dest_dir, assignments, excluded, unknown):
    """把切分結果寫成 splits.json。訓練腳本讀這份，不要自己重算規則。"""
    payload = {
        "note": "AcT 重訓資料集切分。改切分請改 ai/train/build_dataset.py 的 SPLIT_SUBJECTS 後重跑。",
        "rules": {
            "split_subjects": SPLIT_SUBJECTS,
            "flip_offset": FLIP_OFFSET,
            "splits_allowing_flip": sorted(SPLITS_ALLOWING_FLIP),
            "critical": (
                f"S<n+{FLIP_OFFSET}> 是 S<n> 的水平鏡像，是同一個人。"
                "兩者必須在同一個 split，否則測試集洩漏且指標看不出異常。"
            ),
        },
        "counts": {name: len(files) for name, files in assignments.items()},
        "splits": {name: sorted(files) for name, files in assignments.items()},
        "excluded": {
            "reason": "驗證集與測試集不做資料增強，這些鏡像檔不得用於任何 split。",
            "files": sorted(excluded),
        },
        "unassigned": sorted(unknown),
    }
    (dest_dir / "splits.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def write_readme(dest_dir, assignments, excluded):
    """產出給人看的說明。接手的人會先開這份。"""
    train_original = sum(
        1 for name in assignments["train"] if (parse_subject(Path(name).stem) or 0) <= FLIP_OFFSET
    )
    train_flipped = len(assignments["train"]) - train_original
    lines = [
        "# AcT 重訓資料集",
        "",
        "來源：CAUCAFall（10 受試者 × 10 動作 = 100 支）＋ 其水平鏡像（100 支）。",
        "規格：720×480 / 20fps。整併與切分由 `ai/train/build_dataset.py` 產生。",
        "",
        "## 目錄",
        "",
        "```",
        "dataset/",
        "├── README.md          ← 本檔",
        "├── splits.json        ← 切分定義（訓練腳本讀這份）",
        "├── FLIP_MANIFEST.md   ← 鏡像檔的來源對照",
        "└── videos/            ← 全部影片，扁平存放",
        "```",
        "",
        "標籤從檔名前綴取得（`Fall*` = 跌倒、其餘 = 正常），",
        "沿用 `ai/batch_eval.py` 的 `classify_video()`，不需要目錄結構。",
        "",
        "幀級標註（跌落起訖）之後請放 `dataset/labels/<影片檔名>.txt`，",
        "格式見 `ai/local_pipeline_eval.py` 的 `parse_label_file()`。",
        "",
        "## ⚠ 兩條鐵則",
        "",
        f"1. **`S<n+{FLIP_OFFSET}>` 與 `S<n>` 是同一個人**（鏡像），必須在同一個 split。"
        "拆開放會造成測試集洩漏，而且從指標上看不出來。",
        "2. **只有訓練集使用鏡像增強。** 驗證集與測試集必須維持原始分布，"
        f"因此 {len(excluded)} 支鏡像檔被列入 `splits.json` 的 `excluded`，不得使用。",
        "",
        "## 切分",
        "",
        "| split | 受試者 | 支數 | 說明 |",
        "|---|---|---:|---|",
        f"| train | {SPLIT_SUBJECTS['train']} ＋其鏡像 | {len(assignments['train'])} | "
        f"原始 {train_original}＋鏡像 {train_flipped} |",
        f"| val | {SPLIT_SUBJECTS['val']} | {len(assignments['val'])} | 不增強 |",
        f"| test | {SPLIT_SUBJECTS['test']} | {len(assignments['test'])} | 不增強。"
        "選這三位是因為原 `ai/test_demo/` 的基準影片全落在此，含全部 4 支跌倒基準 |",
        f"| （排除） | val/test 的鏡像 | {len(excluded)} | 不得使用 |",
        "",
        "改切分：改 `ai/train/build_dataset.py` 的 `SPLIT_SUBJECTS` 後重跑，不要搬檔案。",
        "",
        "## ⚠ 本目錄不在版控",
        "",
        "`.gitignore` 排除 `*.mp4`。這些素材只存在於本機，**請另外備份**。",
    ]
    (dest_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args():
    parser = argparse.ArgumentParser(description="整併資料集並產出切分定義")
    parser.add_argument("--sources", nargs="*", default=[str(path) for path in DEFAULT_SOURCES],
                        help="來源目錄（預設 train_data 與 train_data_flipped）")
    parser.add_argument("--dest", default=str(DEFAULT_DEST), help="輸出資料集目錄")
    parser.add_argument("--copy", action="store_true", help="複製而非搬移（保留來源）")
    parser.add_argument("--dry-run", action="store_true", help="只列出會做什麼")
    return parser.parse_args()


def main():
    args = parse_args()
    source_dirs = [Path(path).resolve() for path in args.sources]
    dest_dir = Path(args.dest).resolve()
    videos_dir = dest_dir / "videos"

    videos = collect_videos(source_dirs)
    if not videos:
        print(f"❌ 來源目錄裡沒有影片：{', '.join(str(p) for p in source_dirs)}", file=sys.stderr)
        return 1

    subject_index = build_subject_index()
    assignments = {name: [] for name in SPLIT_SUBJECTS}
    excluded, unknown = [], []
    transferred = 0

    print(f"📁 來源：{len(videos)} 支")
    print(f"📁 輸出：{videos_dir}")
    print(f"🔧 模式：{'複製' if args.copy else '搬移'}{'（dry-run）' if args.dry_run else ''}")
    print("-" * 68)

    for source_path in videos:
        subject = parse_subject(source_path.stem)
        if subject is None or subject not in subject_index:
            print(f"⚠️  {source_path.name}｜受試者編號 {subject} 不在切分定義內，未分配")
            unknown.append(source_path.name)
            continue

        split_name, is_flipped = subject_index[subject]
        dest_path = videos_dir / source_path.name
        moved, _ = transfer(source_path, dest_path, args.copy, args.dry_run)
        if moved:
            transferred += 1

        if split_name is None:
            excluded.append(source_path.name)
        else:
            assignments[split_name].append(source_path.name)

        label_source = source_path.with_suffix(".txt")
        if label_source.is_file():
            transfer(label_source, dest_dir / "labels" / label_source.name,
                     args.copy, args.dry_run)

    if not args.dry_run:
        dest_dir.mkdir(parents=True, exist_ok=True)
        # 鏡像來源對照表一併帶進資料集目錄，別讓它留在即將清空的舊目錄
        for source_dir in source_dirs:
            manifest = source_dir / "FLIP_MANIFEST.md"
            if manifest.is_file():
                transfer(manifest, dest_dir / manifest.name, args.copy, args.dry_run)
        write_splits(dest_dir, assignments, excluded, unknown)
        write_readme(dest_dir, assignments, excluded)

    action = "會處理" if args.dry_run else ("複製" if args.copy else "搬移")
    print(f"{action} {transferred} 支")
    print("-" * 68)
    for name in ("train", "val", "test"):
        subjects = SPLIT_SUBJECTS[name]
        flip_note = "＋鏡像" if name in SPLITS_ALLOWING_FLIP else "（不增強）"
        print(f"{name:6s} {len(assignments[name]):3d} 支｜受試者 {subjects}{flip_note}")
    print(f"排除   {len(excluded):3d} 支｜val/test 的鏡像，不得使用")
    if unknown:
        print(f"未分配 {len(unknown):3d} 支")
    if not args.dry_run:
        print("-" * 68)
        print(f"📄 {dest_dir / 'splits.json'}")
        print(f"📄 {dest_dir / 'README.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
