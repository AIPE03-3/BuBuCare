"""驗證 Triton 側與本地側算出來的**東西一樣** —— 效能對照的前置條件。

為什麼要有這支：效能數字只有在「兩條路做的是同一件事」時才有意義。如果本地側因為
前處理不同、權重載錯、或後處理漏了一步而算出不同的框，那它「比較快」是假的。
所以在信任 bench_triton.py 的任何數字之前，先跑這支。

比什麼：
  · yolo_pose  —— box xyxy 與 keypoints xy 的最大絕對誤差（原圖像素座標）
  · action_transformer —— logits (1,2) 的最大絕對誤差
  · rt_detr    —— **只報告、不設門檻**（見下）

門檻怎麼定：
  yolo_pose 與 action_transformer 兩邊是同一顆權重的不同格式
  （.pt 走 PyTorch vs 同一顆匯出的 ONNX 走 Triton），FP32 下算的是同一組浮點運算，
  差異只來自 kernel 實作與運算順序。logits 這種小網路應該落在 1e-3 量級；
  pose 的框是像素座標（0~1920），同樣的相對誤差會放大成較大的絕對值，
  所以門檻分開設（見 THRESH）。

  rt_detr 兩邊**根本不是同一顆模型**（Triton 是 v2 重訓的 5 類 TensorRT plan，
  本地是 rtdetr-l.pt 的 COCO 80 類 PyTorch），框對不上是預期的，比對它沒有意義。
  這裡仍然跑一次並印出兩側各偵測到幾個框、類別分別是什麼，用途是「確認兩邊都活著」
  以及讓對照文件的附表有據可查，**不參與 pass/fail 判定**。

用法（Triton 需在 8010 且三顆 ready）：
    cd ai && .venv/bin/python verify_backend_parity.py
    cd ai && .venv/bin/python verify_backend_parity.py --frames 10 --video test_demo/test2.mp4
"""
import argparse
import os
import sys

import numpy as np

from av_reader import open_source

_AI_DIR = os.path.dirname(os.path.abspath(__file__))

# 最大絕對誤差門檻。pose 是原圖像素座標（可到 1920），act 是 logits（量級 ~1）。
THRESH = {
    "pose_box_px": 2.0,      # 框座標差 2 px 內視為同一個框
    "pose_kpt_px": 2.0,      # 關鍵點同理
    "act_logit": 1e-2,       # logits 差 0.01 內（softmax 後對 class 判定無影響）
}


def load_frames(video: str, count: int) -> list:
    """與 bench_triton.load_frames 同一套（PyAV，test_demo 的影片是 AV1，cv2 解不動）。"""
    cap = open_source(video)
    if not cap.isOpened():
        raise SystemExit(f"❌ 開不了影片：{video}")
    frames = []
    while len(frames) < count:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    cap.release()
    if not frames:
        raise SystemExit(f"❌ 影片讀不到任何幀：{video}")
    return frames


def _sorted_boxes(res) -> np.ndarray:
    """取 (N,4) xyxy 並依 (x1,y1) 排序 —— 兩側偵測順序不保證相同，排序後才能逐列比。"""
    b = res.boxes.xyxy.cpu().numpy()
    if len(b) == 0:
        return b
    return b[np.lexsort((b[:, 1], b[:, 0]))]


def compare_pose(triton_res, local_res, report: dict) -> None:
    tb, lb = _sorted_boxes(triton_res), _sorted_boxes(local_res)
    report["pose_n_triton"].append(len(tb))
    report["pose_n_local"].append(len(lb))
    if len(tb) != len(lb):
        report["pose_count_mismatch"] += 1
        return  # 框數不同就沒得逐列比，記下來即可
    if len(tb) == 0:
        return
    report["pose_box_px"].append(float(np.abs(tb - lb).max()))

    # keypoints：xy 是原圖座標，形狀 (N,17,2)。同樣要先對齊順序，
    # 用 boxes 的排序索引重排 keypoints 才對得上。
    def kpts_sorted(res):
        b = res.boxes.xyxy.cpu().numpy()
        order = np.lexsort((b[:, 1], b[:, 0]))
        return res.keypoints.xy.cpu().numpy()[order]

    if triton_res.keypoints is not None and local_res.keypoints is not None:
        tk, lk = kpts_sorted(triton_res), kpts_sorted(local_res)
        if tk.shape == lk.shape and tk.size:
            report["pose_kpt_px"].append(float(np.abs(tk - lk).max()))


def main():
    ap = argparse.ArgumentParser()
    # 預設與 bench_triton.py 同一支（test8）：理由見該檔 --video 的註解。
    # 注意 test1 仍是有價值的 parity 輸入（rt_detr v2 在它上面 0 偵測就是這支抓出來的），
    # 要複驗那個現象就傳 --video test_demo/test1.mp4。
    ap.add_argument("--video", default=os.path.join(_AI_DIR, "test_demo", "test8.mp4"))
    ap.add_argument("--frames", type=int, default=15)
    ap.add_argument("--base", default="http://127.0.0.1:8010", help="Triton HTTP base URL")
    ap.add_argument("--pose-model", default="yolo_pose")
    ap.add_argument("--detr-model", default="rt_detr")
    ap.add_argument("--act-model", default="action_transformer")
    args = ap.parse_args()

    from local_act_client import LocalActModel
    from local_detr_client import LocalDetrModel
    from local_pose_client import LocalPoseModel
    from triton_act_client import TritonActModel
    from triton_detr_client import TritonDetrModel
    from triton_pose_client import TritonPoseModel

    base = args.base.rstrip("/")
    frames = load_frames(args.video, args.frames)
    print(f"🔍 一致性驗證：{os.path.basename(args.video)} 前 {len(frames)} 幀   Triton={base}")

    t_pose = TritonPoseModel(f"{base}/{args.pose_model}")
    t_detr = TritonDetrModel(f"{base}/{args.detr_model}")
    t_act = TritonActModel(f"{base}/{args.act_model}")
    l_pose, l_detr, l_act = LocalPoseModel(), LocalDetrModel(), LocalActModel()

    report = {"pose_box_px": [], "pose_kpt_px": [], "act_logit": [],
              "pose_n_triton": [], "pose_n_local": [], "pose_count_mismatch": 0,
              "detr_n_triton": [], "detr_n_local": []}

    # AcT 的輸入用固定 seed，與 bench_triton.py 同一份（可重現、兩側完全相同）。
    rng = np.random.default_rng(20260727)

    for i, frame in enumerate(frames):
        compare_pose(t_pose(frame, conf=0.45)[0], l_pose(frame, conf=0.45)[0], report)

        # rt_detr：只記框數，不比座標（兩邊不同權重，見 docstring）
        report["detr_n_triton"].append(len(t_detr(frame, conf=0.35)[0].boxes))
        report["detr_n_local"].append(len(l_detr(frame, conf=0.35)[0].boxes))

        feats = rng.random((30, 34), dtype=np.float32)
        report["act_logit"].append(
            float(np.abs(np.asarray(t_act(feats), dtype=np.float32)
                         - np.asarray(l_act(feats), dtype=np.float32)).max()))

    # ── 判定 ────────────────────────────────────────────────────────────────
    print("\n── 主表模型（兩邊同權重，要過門檻）──")
    failed = []
    for key, label in (("pose_box_px", "yolo_pose box (px)"),
                       ("pose_kpt_px", "yolo_pose keypoint (px)"),
                       ("act_logit", "action_transformer logits")):
        vals = report[key]
        if not vals:
            print(f"   ⚠️ {label:<30} 沒有可比的樣本（兩側框數全不同或全無偵測）")
            failed.append(f"{label}：無樣本可比")
            continue
        mx, mean = max(vals), sum(vals) / len(vals)
        ok = mx <= THRESH[key]
        print(f"   {'✅' if ok else '❌'} {label:<30} max {mx:>10.6f}   mean {mean:>10.6f}"
              f"   (門檻 {THRESH[key]})   n={len(vals)}")
        if not ok:
            failed.append(f"{label}：max {mx:.6f} > 門檻 {THRESH[key]}")

    if report["pose_count_mismatch"]:
        n = report["pose_count_mismatch"]
        print(f"   ⚠️ yolo_pose 有 {n}/{len(frames)} 幀兩側偵測到的人數不同"
              f"（Triton {report['pose_n_triton']} vs 本地 {report['pose_n_local']}）")
        # 人數不同代表 conf 邊界上有框被一側濾掉。少量可接受（浮點邊界），
        # 過半就是真的有問題。
        if n > len(frames) / 2:
            failed.append(f"yolo_pose 過半幀（{n}/{len(frames)}）兩側人數不同")

    print("\n── 附表模型（兩邊不同權重，只報告不判定）──")
    print(f"   ℹ️ rt_detr 偵測框數  Triton(v2/5類) {report['detr_n_triton']}")
    print(f"                        本地(COCO/80類) {report['detr_n_local']}")
    print("      ↑ 兩側不同是預期的：不同權重、不同類別數。詳見 BENCHMARK_TRITON_VS_LOCAL.md")

    if failed:
        print("\n❌ 一致性驗證未通過：")
        for f in failed:
            print(f"   · {f}")
        print("   → 效能數字在這關過之前不可信，先查兩側前後處理與權重來源。")
        sys.exit(1)
    print("\n✅ 一致性驗證通過：兩條路算出來的東西一致，效能數字可信。")


if __name__ == "__main__":
    main()
