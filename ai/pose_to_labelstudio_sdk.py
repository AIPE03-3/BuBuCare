#!/usr/bin/env python3
"""Label Studio 串接（骨架版）：把 AI 預標的關節點推進去、把人工標註拉回成 YOLO-Pose 標籤。

與 `ai/inference_to_labelstudio_sdk.py` 是同一件事的姿態版本，共用
`ai/labelstudio_client.py` 的連線管線。**它是 YOLO-Pose 重訓鏈唯一的資料來源** ——
沒有它，`ai/prepare_dataset.py --task pose` 沒有 `pose_labels/` 可讀，
`ai/clearml_pose_train_pipeline.py` 就沒有資料可訓練。

    邊緣端快照 ──> Label Studio（KeyPointLabels 專案）──> AI 預標註（框＋17 點）
                                                              │
                                                      人工開箱審核 / 修正 / Submit
                                                              │
                                                              v
                  active_learning_dataset/pose_labels/  ──> prepare_dataset --task pose
                                                              ──> clearml_pose_train_pipeline

## 與上游 `Fall/tools/pose_to_labelstudio_sdk.py` 的差異

上游那支是**單向的**（只推預標註，沒有把人工標註拉回本地的路徑），所以它產不出訓練
資料——它的 `active_learning_pose_dataset/` 要靠別的方式填。這裡補上回收方向，
整條鏈才閉合。其餘四處：

1. **拿掉寫死的帳號**（上游 `USERNAME` 預設是某人的 gmail）與寫死的 `TARGET_PROJECTS
   = [{"id": 1, ...}]`；帳密與專案 id 只從環境變數／根目錄 `.env` 讀。
2. **推論改打線上 Triton `yolo_pose`**，不再另外載一份本地 `.pt`。理由同偵測那支：
   要驗的是「線上這顆現在畫得如何」。
3. **預標註同時推框與關節點**。上游只推 keypointlabels，但 YOLO-Pose 的標註格式是
   「框 + 掛在框上的關節點」，少了框就湊不出訓練標籤，人工還得自己補框。
4. **關節點名稱與 Label Studio 介面對帳**，對不上直接停（不猜）。上游是照 `KPT_NAMES`
   的順序硬推，介面標籤名不同時 Label Studio 會收下但畫面不顯示，看起來像沒推成功。

## 人工標註怎麼還原成「某個人的 17 個關節點」

Label Studio 的 keypoint 各自獨立，不會告訴你哪幾點屬於同一個人。這裡用
**「關節點落在哪個框裡」** 還原：每個點指派給包含它的最小面積框。

⚠️ 這是有極限的啟發式：兩個人重疊時，落在交集區的點會被指派給比較小的那個框。
本專案的場景（俯視公共區域、人多半分開）夠用，但如果之後要標密集人群，
正確做法是改用 Label Studio 的 region grouping／relations，那是另一個題目。
真的標壞了看得出來——`--check` 會印出每個框收到幾個點，明顯偏少就是分錯了。

用法（先起好 Label Studio，見 ai/docker-compose-labelstudio.yml）：
    python ai/pose_to_labelstudio_sdk.py                # 雙向同步
    python ai/pose_to_labelstudio_sdk.py --pull-only    # 只把人工標註拉回本地
    python ai/pose_to_labelstudio_sdk.py --sync-storage
    python ai/pose_to_labelstudio_sdk.py --check        # 只印對帳資訊，不動任何資料
"""
import argparse
import os
import sys
from collections import Counter

import numpy as np

from labelstudio_client import (ensure_local_image, fail, get_project, get_task,
                                list_tasks, local_image_path, login,
                                parse_label_config, replace_prediction,
                                resolve_image_url, sync_storage)
from mlops_paths import AI_DIR, RAW_POSE_LABELS_DIR, cfg

# ⚠️ 專案 id 與偵測那支（LS_PROJECT_ID）**必須不同**：兩邊的標註介面不一樣，
# 一個是 RectangleLabels、一個要再加 KeyPointLabels。指到同一個專案時下面的
# 介面檢查會擋下來。
LS_POSE_PROJECT_ID = int(cfg("LS_POSE_PROJECT_ID", "2"))
CONF_THRES = float(cfg("LS_POSE_CONF_THRES", "0.35"))

# COCO 17 點，順序**就是** YOLO-Pose 標籤檔裡關節點的排列順序，不能改。
# 這 17 個名字必須與 Label Studio 的 KeyPointLabels 標籤值逐字相同（下面會對帳）。
KEYPOINT_NAMES = [
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
]
NUM_KEYPOINTS = len(KEYPOINT_NAMES)
# YOLO-Pose 是單類別任務；框的標籤名固定是 person（對上 ai/pose_data.yaml 的 names）
PERSON_LABEL = "person"
# Label Studio 標註的 visibility 一律當「已標註且可見」。介面上沒有「被遮擋但存在」
# 這個狀態可選，硬要區分只會變成標註者各憑感覺，不如統一。沒標到的點才是 0。
VISIBLE = 2


def pct(v: float) -> float:
    """轉成 Label Studio 用的百分比。

    ⚠️ 一定要 float()：numpy 的 float32 過不了 json.dumps
    （TypeError: Object of type float32 is not JSON serializable），
    而 round() 拿到 np.float32 回傳的仍是 np.float32，不會幫你轉。
    """
    return float(round(float(v) * 100, 4))


# ── 推：AI 預標註 ────────────────────────────────────────────────────────────
def build_prediction(result, kp_from: str, box_from: str, to_name: str) -> list[dict]:
    """把一張圖的 YOLO-Pose 推論結果轉成 Label Studio 的 result 陣列。"""
    items: list[dict] = []
    boxes = getattr(result, "boxes", None)
    kpts = getattr(result, "keypoints", None)
    if boxes is None or len(boxes) == 0:
        return items

    # xyn 是正規化到 [0,1] 的關節點座標，(N, 17, 2)
    kpts_xyn = kpts.xyn.cpu().numpy() if kpts is not None and kpts.xyn is not None \
        else np.zeros((len(boxes), NUM_KEYPOINTS, 2))
    h, w = result.orig_shape[:2]

    for person_idx in range(len(boxes)):
        conf = float(boxes.conf[person_idx].item())
        x1, y1, x2, y2 = (float(v) for v in boxes.xyxy[person_idx].cpu().numpy())
        items.append({
            "id": f"person_{person_idx}",
            "from_name": box_from, "to_name": to_name, "type": "rectanglelabels",
            "value": {"x": pct(x1 / w), "y": pct(y1 / h),
                      "width": pct((x2 - x1) / w), "height": pct((y2 - y1) / h),
                      "rectanglelabels": [PERSON_LABEL]},
            "score": conf,
        })
        for kp_idx, (nx, ny) in enumerate(kpts_xyn[person_idx][:NUM_KEYPOINTS]):
            # (0, 0) 是 ultralytics 表示「這個關節點沒偵測到」的方式，不是畫面左上角。
            # 推上去會在圖片角落堆一坨假點，人工還要一個一個刪。
            if nx == 0 and ny == 0:
                continue
            items.append({
                "id": f"kp_{person_idx}_{kp_idx}",
                "from_name": kp_from, "to_name": to_name, "type": "keypointlabels",
                "value": {"x": pct(nx), "y": pct(ny), "width": 0.5,
                          "keypointlabels": [KEYPOINT_NAMES[kp_idx]]},
                "score": conf,
            })
    return items


# ── 拉：人工標註 → YOLO-Pose 標籤檔 ──────────────────────────────────────────
def _boxes_and_points(annotation: dict) -> tuple[list[dict], list[tuple[str, float, float]]]:
    """把一筆人工標註拆成 person 框清單與 (關節點名, x%, y%) 清單。"""
    boxes, points = [], []
    for item in annotation.get("result", []):
        value = item.get("value", {})
        if item.get("type") == "rectanglelabels":
            if PERSON_LABEL not in (value.get("rectanglelabels") or []):
                continue
            boxes.append({"x": value.get("x", 0.0), "y": value.get("y", 0.0),
                          "w": value.get("width", 0.0), "h": value.get("height", 0.0)})
        elif item.get("type") == "keypointlabels":
            names = value.get("keypointlabels") or []
            if names:
                points.append((names[0], value.get("x", 0.0), value.get("y", 0.0)))
    return boxes, points


def _assign_point(box_list: list[dict], x: float, y: float) -> int | None:
    """把一個關節點指派給包含它的**最小面積**框；沒有框包得住回 None。"""
    best, best_area = None, None
    for i, b in enumerate(box_list):
        if not (b["x"] <= x <= b["x"] + b["w"] and b["y"] <= y <= b["y"] + b["h"]):
            continue
        area = b["w"] * b["h"]
        if best_area is None or area < best_area:
            best, best_area = i, area
    return best


def annotation_to_pose_lines(annotation: dict, stats: Counter) -> list[str]:
    """人工標註 → YOLO-Pose 標籤行（每個人一行，5 + 17×3 = 56 欄）。"""
    boxes, points = _boxes_and_points(annotation)
    if not boxes:
        stats["略過・這筆標註沒有 person 框"] += 1
        return []

    # 每個框備好 17 組 (x, y, v)，預設全 0＝未標註
    per_box: list[list[list[float]]] = [
        [[0.0, 0.0, 0.0] for _ in range(NUM_KEYPOINTS)] for _ in boxes
    ]
    for name, x, y in points:
        if name not in KEYPOINT_NAMES:
            stats["丟棄・關節點名不在 COCO 17 點裡"] += 1
            continue
        idx = _assign_point(boxes, x, y)
        if idx is None:
            # 標在框外的點沒有歸屬，收進來只會變成某個人身上的錯誤關節
            stats["丟棄・關節點不在任何 person 框內"] += 1
            continue
        per_box[idx][KEYPOINT_NAMES.index(name)] = [x / 100, y / 100, float(VISIBLE)]

    lines = []
    for b, kpts in zip(boxes, per_box):
        marked = sum(1 for k in kpts if k[2] > 0)
        if marked == 0:
            # 一個關節點都沒收到的框，對 pose 訓練沒有監督訊號
            stats["丟棄・框收不到任何關節點"] += 1
            continue
        cx, cy = (b["x"] + b["w"] / 2) / 100, (b["y"] + b["h"] / 2) / 100
        nw, nh = b["w"] / 100, b["h"] / 100
        clip = lambda v: min(max(v, 0.0), 1.0)  # noqa: E731
        flat = " ".join(f"{clip(k[0]):.6f} {clip(k[1]):.6f} {k[2]:.0f}" for k in kpts)
        lines.append(f"0 {clip(cx):.6f} {clip(cy):.6f} {clip(nw):.6f} {clip(nh):.6f} {flat}")
        stats["拉回・人物"] += 1
        stats[f"關節點數 {marked}/{NUM_KEYPOINTS}"] += 1
    return lines


def pull_annotation(detail: dict, stem: str, stats: Counter) -> bool:
    """有人工標註就寫成本地 pose 標籤檔。回傳有沒有處理過這個 task。"""
    annotations = detail.get("annotations") or []
    if not annotations:
        return False
    lines = annotation_to_pose_lines(annotations[-1], stats)   # 取最新那一筆
    os.makedirs(RAW_POSE_LABELS_DIR, exist_ok=True)
    with open(os.path.join(RAW_POSE_LABELS_DIR, f"{stem}.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + ("\n" if lines else ""))
    stats["拉回・圖片"] += 1
    return True


# ── 介面對帳 ─────────────────────────────────────────────────────────────────
def check_label_config(label_config: str) -> tuple[str, str, str]:
    """確認專案介面同時有 KeyPointLabels 與 RectangleLabels，回傳三個 name。

    對不上就停。不猜的理由：`parse_label_config` 找不到指定控制項時會退回寬鬆比對
    （為了相容偵測那支），如果這裡不擋，把 LS_POSE_PROJECT_ID 指到偵測專案時
    會拿到 RectangleLabels 的 name 當成關節點控制項——Label Studio 收下 200，
    但畫面上一個點都不會顯示，看起來像「推成功了但沒作用」。
    """
    if "<KeyPointLabels" not in label_config:
        fail(f"專案 {LS_POSE_PROJECT_ID} 的標註介面沒有 <KeyPointLabels>。\n"
             f"   這支要的是骨架標註專案，不是偵測框專案（那個是 LS_PROJECT_ID）。\n"
             f"   設定 LS_POSE_PROJECT_ID 指到正確的專案，或在該專案加上 KeyPointLabels 控制項。")
    if "<RectangleLabels" not in label_config:
        fail(f"專案 {LS_POSE_PROJECT_ID} 的標註介面沒有 <RectangleLabels>。\n"
             f"   YOLO-Pose 的標註是「框＋掛在框上的關節點」，少了框湊不出訓練標籤。")

    kp_from, kp_to, kp_labels = parse_label_config(label_config, "KeyPointLabels")
    box_from, box_to, box_labels = parse_label_config(label_config, "RectangleLabels")

    missing = set(KEYPOINT_NAMES) - kp_labels
    if missing:
        fail(f"Label Studio 的 KeyPointLabels 缺這些關節點標籤：{sorted(missing)}\n"
             f"   介面上有的是：{sorted(kp_labels)}\n"
             f"   名稱必須與 COCO 17 點逐字相同，否則拉回來的關節點會對錯位置。")
    if PERSON_LABEL not in box_labels:
        fail(f"Label Studio 的 RectangleLabels 沒有 '{PERSON_LABEL}' 標籤"
             f"（有的是 {sorted(box_labels)}）")
    if kp_to != box_to:
        fail(f"KeyPointLabels 與 RectangleLabels 的 toName 不一致"
             f"（{kp_to} vs {box_to}）—— 兩者必須標在同一張圖上")
    return kp_from, box_from, kp_to


def main() -> int:
    ap = argparse.ArgumentParser(description="Label Studio 骨架標註雙向同步（YOLO-Pose）")
    ap.add_argument("--pull-only", action="store_true", help="只把人工標註拉回本地，不做推論")
    ap.add_argument("--sync-storage", action="store_true", help="先要求 Label Studio 重新同步 S3 來源")
    ap.add_argument("--check", action="store_true", help="只做介面對帳與統計，不寫任何資料")
    ap.add_argument("--limit", type=int, help="只處理前 N 個 task（除錯用）")
    args = ap.parse_args()

    s = login()
    project = get_project(s, LS_POSE_PROJECT_ID)
    kp_from, box_from, to_name = check_label_config(project.get("label_config", ""))
    print(f"專案：{project.get('title')}（task {project.get('task_number')}，"
          f"已標註 {project.get('num_tasks_with_annotations')}）")
    print(f"標註介面：關節點 {kp_from} / 框 {box_from} → {to_name}")
    print(f"COCO {NUM_KEYPOINTS} 點與介面標籤對帳通過")
    if args.check:
        print("\nℹ️ --check：只做對帳，沒有寫出任何檔案")
        return 0

    if args.sync_storage:
        sync_storage(s, LS_POSE_PROJECT_ID)

    tasks = list_tasks(s, LS_POSE_PROJECT_ID)
    if args.limit:
        tasks = tasks[:args.limit]
    print(f"共 {len(tasks)} 個 task 要處理\n")

    model = None
    stats = Counter()

    for i, task in enumerate(tasks, 1):
        image_url = resolve_image_url(task)
        path = local_image_path(image_url, task["id"])
        stem = os.path.splitext(os.path.basename(path))[0]
        detail = get_task(s, task["id"])

        if pull_annotation(detail, stem, stats):
            print(f"[{i}/{len(tasks)}] ⬅️  {stem}：已有人工標註，拉回本地")
            continue
        if args.pull_only:
            stats["略過・尚未標註"] += 1
            continue

        img = ensure_local_image(image_url, path)
        if img is None:
            stats["略過・取不到影像"] += 1
            print(f"[{i}/{len(tasks)}] ⚠️  {stem}：取不到影像，跳過")
            continue

        if model is None:
            # 延遲載入：--pull-only 或全部都已標註時完全不必碰 Triton
            from mlops_paths import TRITON_HTTP_URL
            from triton_pose_client import TritonPoseModel
            url = cfg("TRITON_POSE_URL") or f"{TRITON_HTTP_URL}/yolo_pose"
            print(f"📦 推論走線上 Triton：{url}")
            model = TritonPoseModel(url)

        results = model(img, conf=CONF_THRES, verbose=False)
        items = build_prediction(results[0], kp_from, box_from, to_name) if results else []
        scores = [it["score"] for it in items]
        ok, err = replace_prediction(s, task["id"], "yolo_pose@triton", items,
                                     float(np.mean(scores)) if scores else 0.0)
        if ok:
            stats["推入・AI 預標註"] += 1
            stats["推入・關節點數"] += sum(1 for it in items
                                     if it["type"] == "keypointlabels")
            stats["推入・框數"] += sum(1 for it in items
                                   if it["type"] == "rectanglelabels")
            print(f"[{i}/{len(tasks)}] ➡️  {stem}：推入預標註（{len(items)} 個標記）")
        else:
            stats["推入・失敗"] += 1
            print(f"[{i}/{len(tasks)}] ❌ {stem}：預標註注入失敗 {err}")

    print("\n── 統計 ──")
    for k, v in sorted(stats.items()):
        print(f"  {k:<28} {v}")
    print(f"\n本地 pose 標籤目錄：{os.path.relpath(RAW_POSE_LABELS_DIR, AI_DIR)}")
    print("接著清洗與切分：python ai/prepare_dataset.py --task pose")
    return 0


if __name__ == "__main__":
    sys.exit(main())
