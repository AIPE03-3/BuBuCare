"""Triton 單顆模型效能量測——GPU vs CPU 同機對照用。

為什麼不用官方 perf_analyzer：perf_analyzer 餵的是合成隨機張量，量的是「模型服務上限」。
我們要的是「這條生產管線實際跑多快」，所以直接復用 inference_test.py 用的三支 client
（triton_pose_client / triton_detr_client / triton_act_client），連前處理、後處理、
thread-local 建連都跟線上完全一樣，量到的數字可以直接對照 ai/FPS_NOTES.md。

量兩層：
  · client 端 wall time —— 前處理 + 網路 + 推論 + 後處理，也就是主迴圈實際等待的時間
  · server 端 compute_infer —— 從 Triton 自己的 /metrics 前後差值算，排除網路與前後處理，
    這是「純模型計算」的時間，GPU vs CPU 的差距主要落在這裡

用法（GPU 側，Triton 在 8010/8002）：
    cd ai && .venv/bin/python bench_triton.py --label gpu \\
        --base http://127.0.0.1:8010 --metrics http://127.0.0.1:8002/metrics

CPU 側（Triton 在 8020/8022，rt_detr 必須換成 rt_detr_onnx——TensorRT 引擎不可能跑 CPU）：
    cd ai && .venv/bin/python bench_triton.py --label cpu \\
        --base http://127.0.0.1:8020 --metrics http://127.0.0.1:8022/metrics \\
        --detr-model rt_detr_onnx --iters 40

⚠️ 兩台 Triton 不要同時受測：CPU 版會吃滿所有核心，連帶拖慢 GPU 側 client 的前處理，
   量出來的數字兩邊都不對。跑哪一邊就把另一邊 docker stop。
"""
import argparse
import json
import os
import platform
import subprocess
import time
from datetime import datetime

import numpy as np

from av_reader import open_source
from triton_act_client import TritonActModel
from triton_detr_client import TritonDetrModel
from triton_pose_client import TritonPoseModel

_AI_DIR = os.path.dirname(os.path.abspath(__file__))

# 從 Triton /metrics 取這幾個累計量，前後相減 ÷ 這段期間的請求數 = 每次平均微秒數
_METRIC_KEYS = (
    "nv_inference_request_success",     # 分母：成功請求數
    "nv_inference_request_duration_us", # server 收到到回覆的總時間
    "nv_inference_queue_duration_us",   # 排隊等 instance 的時間
    "nv_inference_compute_infer_duration_us",  # 純模型計算時間 ← 最關鍵
)


def scrape(metrics_url: str) -> dict:
    """把 Triton 的 Prometheus 文字格式抓成 {(metric, model): value}。

    ⚠️ 同一個 (metric, model) 會出現**兩條** series：一條帶 gpu_uuid 標籤、一條不帶。
    GPU 上跑的模型真實數字記在帶 gpu_uuid 那條，不帶的那條是 0；CPU 上則相反。
    所以這裡取兩者的 max，不能後蓋前（早期版本就是後蓋前，GPU 側的 server 數字
    全被 0 蓋掉、算出 n=0 而整組消失）。

    順帶一提：這個端點就是之後接 Prometheus 時要 scrape 的同一個端點（見 NEXT_STAGE
    的 Prometheus 設計），這裡只是先手動讀它。
    """
    import urllib.request

    out = {}
    try:
        with urllib.request.urlopen(metrics_url, timeout=5) as r:
            text = r.read().decode("utf-8", "replace")
    except Exception as e:
        print(f"⚠️ 抓不到 {metrics_url}：{e}（server 端數字會缺，client 端仍有效）")
        return out
    for line in text.split("\n"):
        if not line or line.startswith("#"):
            continue
        name = line.split("{", 1)[0]
        if name not in _METRIC_KEYS or "{" not in line:
            continue
        labels, _, value = line.partition("}")
        model = None
        for part in labels.split("{", 1)[1].split(","):
            k, _, v = part.partition("=")
            if k.strip() == "model":
                model = v.strip().strip('"')
        if model:
            try:
                v = float(value.strip())
            except ValueError:
                continue
            out[(name, model)] = max(out.get((name, model), 0.0), v)
    return out


def server_side(before: dict, after: dict, model: str) -> dict:
    """從前後兩份 /metrics 快照算出這段期間的每次平均時間（毫秒）。"""
    n = after.get(("nv_inference_request_success", model), 0) - \
        before.get(("nv_inference_request_success", model), 0)
    if n <= 0:
        return {}
    out = {"server_requests": int(n)}
    for key, short in (
        ("nv_inference_request_duration_us", "server_request_ms"),
        ("nv_inference_queue_duration_us", "server_queue_ms"),
        ("nv_inference_compute_infer_duration_us", "server_compute_infer_ms"),
    ):
        delta = after.get((key, model), 0) - before.get((key, model), 0)
        out[short] = round(delta / n / 1000.0, 3)
    return out


def stats(samples_s: list[float]) -> dict:
    a = np.array(samples_s, dtype=np.float64) * 1000.0  # → ms
    return {
        "n": len(a),
        "mean_ms": round(float(a.mean()), 3),
        "p50_ms": round(float(np.percentile(a, 50)), 3),
        "p90_ms": round(float(np.percentile(a, 90)), 3),
        "p95_ms": round(float(np.percentile(a, 95)), 3),
        "p99_ms": round(float(np.percentile(a, 99)), 3),
        "min_ms": round(float(a.min()), 3),
        "max_ms": round(float(a.max()), 3),
        "throughput_ips": round(1000.0 / float(a.mean()), 2),  # 單執行緒序列吞吐
    }


def load_frames(video: str, count: int) -> list[np.ndarray]:
    """從影片取固定的前 N 幀。GPU/CPU 兩側餵的是同一批畫面，消除輸入差異。

    用 av_reader.open_source 而不是 cv2.VideoCapture：test_demo 的影片是 AV1 編碼，
    OpenCV 這邊解不動（會噴 "Your platform doesn't support hardware accelerated AV1
    decoding" 然後回不了任何幀），專案本來就是為了這個才有 av_reader（PyAV）。
    """
    cap = open_source(video)
    if not cap.isOpened():
        raise SystemExit(f"❌ 開不了影片：{video}")
    frames = []
    while len(frames) < count:
        ret, frame = cap.read()
        if not ret:
            break
        frames.append(frame)
    cap.release()
    if not frames:
        raise SystemExit(f"❌ 影片讀不到任何幀：{video}")
    return frames


def bench(name, call, iters, warmup):
    for i in range(warmup):
        call(i)
    samples = []
    for i in range(iters):
        t0 = time.perf_counter()
        call(i)
        samples.append(time.perf_counter() - t0)
    s = stats(samples)
    print(f"   {name:<20} mean {s['mean_ms']:>8.2f} ms   p95 {s['p95_ms']:>8.2f} ms"
          f"   {s['throughput_ips']:>7.2f} infer/s")
    return s


def env_snapshot() -> dict:
    def run(cmd):
        try:
            return subprocess.run(cmd, shell=True, capture_output=True, text=True,
                                  timeout=10).stdout.strip()
        except Exception:
            return ""
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "host": platform.node(),
        "python": platform.python_version(),
        "cpu": run("lscpu | grep 'Model name' | head -1 | cut -d: -f2 | xargs"),
        "cpu_count": os.cpu_count(),
        "gpu": run("nvidia-smi --query-gpu=name,driver_version --format=csv,noheader"),
        "docker_ps": run("docker ps --format '{{.Names}}:{{.Image}}'").replace("\n", " | "),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True, help="這一輪的名字，通常是 gpu 或 cpu")
    ap.add_argument("--base", default="http://127.0.0.1:8010", help="Triton HTTP base URL")
    ap.add_argument("--metrics", default="http://127.0.0.1:8002/metrics")
    ap.add_argument("--pose-model", default="yolo_pose")
    ap.add_argument("--detr-model", default="rt_detr",
                    help="CPU 側必須用 rt_detr_onnx：tensorrt_plan 不可能在 CPU 上跑")
    ap.add_argument("--act-model", default="action_transformer")
    ap.add_argument("--video", default=os.path.join(_AI_DIR, "test_demo", "test1.mp4"))
    ap.add_argument("--frames", type=int, default=30, help="取幾幀輪流餵")
    ap.add_argument("--iters", type=int, default=100)
    ap.add_argument("--warmup", type=int, default=10)
    ap.add_argument("--out-dir", default=os.path.join(_AI_DIR, "bench_results"))
    args = ap.parse_args()

    base = args.base.rstrip("/")
    frames = load_frames(args.video, args.frames)
    print(f"🔬 量測 [{args.label}]  base={base}")
    print(f"   影片={os.path.basename(args.video)}  取 {len(frames)} 幀  "
          f"warmup={args.warmup} iters={args.iters}")

    pose = TritonPoseModel(f"{base}/{args.pose_model}")
    detr = TritonDetrModel(f"{base}/{args.detr_model}")
    act = TritonActModel(f"{base}/{args.act_model}")

    # AcT 的輸入是 30 幀 pose 特徵。用固定 seed 產生一份，兩側完全相同。
    # 內容不影響 Transformer 的計算量（形狀固定 (1,30,34)），只要兩邊一致即可。
    rng = np.random.default_rng(20260727)
    act_feats = rng.random((30, 34), dtype=np.float32)

    results = {"label": args.label, "base": base, "env": env_snapshot(),
               "config": {"pose": args.pose_model, "detr": args.detr_model,
                          "act": args.act_model, "iters": args.iters,
                          "warmup": args.warmup, "frames": len(frames),
                          "video": os.path.basename(args.video)},
               "models": {}}

    for key, model_name, fn in (
        ("pose", args.pose_model, lambda i: pose(frames[i % len(frames)], conf=0.45)),
        ("detr", args.detr_model, lambda i: detr(frames[i % len(frames)], conf=0.35)),
        ("act", args.act_model, lambda i: act(act_feats)),
    ):
        before = scrape(args.metrics)
        s = bench(model_name, fn, args.iters, args.warmup)
        after = scrape(args.metrics)
        s.update(server_side(before, after, model_name))
        results["models"][key] = {"model": model_name, **s}

    os.makedirs(args.out_dir, exist_ok=True)
    out = os.path.join(args.out_dir,
                       f"{datetime.now():%Y%m%d_%H%M%S}_{args.label}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n💾 已寫入 {out}")


if __name__ == "__main__":
    main()
