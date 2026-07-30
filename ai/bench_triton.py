"""單顆模型效能量測——同機對照用。

支援兩個對照軸：
  · **GPU vs CPU**（`--base` 指到不同的 Triton）—— 見 ai/BENCHMARK_GPU_VS_CPU.md
  · **有 Triton vs 沒 Triton**（`--backend triton|local`）—— 見 ai/BENCHMARK_TRITON_VS_LOCAL.md
    `local` 把權重直接載進本 process，不經任何伺服器，是「不用 Triton」的 baseline。
    此模式沒有 server 端 /metrics 可抓，只有 client 端指標（這是預期的）。


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

    順帶一提：這個端點就是之後接 Prometheus 時要 scrape 的同一個端點（見 docs/NEXT_STAGE.md
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


def build_models(backend: str, base: str, args):
    """依 backend 建三顆模型的 client。兩邊介面相同，回傳 (pose, detr, act)。

    `triton` 走 triton_*_client（HTTP 或 gRPC，看 base 的 scheme）；
    `local` 走 local_*_client（權重直接載進這個 process，不經任何伺服器）。
    import 放在函式內：`--backend local` 時不必要求 Triton client 可 import，反之亦然。
    """
    if backend == "triton":
        from triton_act_client import TritonActModel
        from triton_detr_client import TritonDetrModel
        from triton_pose_client import TritonPoseModel
        return (TritonPoseModel(f"{base}/{args.pose_model}"),
                TritonDetrModel(f"{base}/{args.detr_model}"),
                TritonActModel(f"{base}/{args.act_model}"))
    if backend == "local":
        from local_act_client import LocalActModel
        from local_detr_client import LocalDetrModel
        from local_pose_client import LocalPoseModel
        return LocalPoseModel(), LocalDetrModel(), LocalActModel()
    raise SystemExit(f"❌ 不認得的 --backend：{backend}（只有 triton / local）")


def gpu_mem_mb() -> float | None:
    """目前這張 GPU 的已用顯存（MB）。量「本地各載一份權重 vs Triton 共用一份」的差別。"""
    try:
        out = subprocess.run(
            "nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits",
            shell=True, capture_output=True, text=True, timeout=10).stdout.strip()
        return float(out.split("\n")[0])
    except Exception:
        return None


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
    ap.add_argument("--label", required=True, help="這一輪的名字，例：triton-http / local")
    ap.add_argument("--backend", default="triton", choices=("triton", "local"),
                    help="triton=模型架在 Triton 伺服器上；local=權重直接載進本 process")
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
    print(f"🔬 量測 [{args.label}]  backend={args.backend}  "
          f"{'base=' + base if args.backend == 'triton' else '本地權重（不經伺服器）'}")
    print(f"   影片={os.path.basename(args.video)}  取 {len(frames)} 幀  "
          f"warmup={args.warmup} iters={args.iters}")

    # 冷啟成本：從「建 client」到「第一次推論拿到結果」。
    # Triton 是容器啟動時就把權重載進顯存，程式端幾乎即時；本地要現場把 .pt 讀進顯存，
    # 會花數秒。只量穩態延遲會漏掉這項差異，所以在這裡記一筆。
    mem_before = gpu_mem_mb()
    t_build = time.perf_counter()
    pose, detr, act = build_models(args.backend, base, args)
    build_s = time.perf_counter() - t_build

    # AcT 的輸入是 30 幀 pose 特徵。用固定 seed 產生一份，兩側完全相同。
    # 內容不影響 Transformer 的計算量（形狀固定 (1,30,34)），只要兩邊一致即可。
    rng = np.random.default_rng(20260727)
    act_feats = rng.random((30, 34), dtype=np.float32)

    # 三顆各打第一發（thread-local 建連 / 權重載入都發生在這裡）
    t_first = time.perf_counter()
    pose(frames[0], conf=0.45)
    detr(frames[0], conf=0.35)
    act(act_feats)
    first_infer_s = time.perf_counter() - t_first
    mem_after = gpu_mem_mb()
    print(f"   冷啟：建 client {build_s * 1000:.0f} ms + 首次三顆推論 "
          f"{first_infer_s * 1000:.0f} ms = {(build_s + first_infer_s) * 1000:.0f} ms")
    if mem_before is not None and mem_after is not None:
        print(f"   GPU 顯存：{mem_before:.0f} → {mem_after:.0f} MB"
              f"（本 process 增加 {mem_after - mem_before:+.0f} MB）")

    results = {"label": args.label, "backend": args.backend,
               "base": base if args.backend == "triton" else None,
               "env": env_snapshot(),
               "config": {"pose": args.pose_model, "detr": args.detr_model,
                          "act": args.act_model, "iters": args.iters,
                          "warmup": args.warmup, "frames": len(frames),
                          "video": os.path.basename(args.video)},
               "cold_start": {"build_client_ms": round(build_s * 1000, 1),
                              "first_infer_3models_ms": round(first_infer_s * 1000, 1),
                              "total_ms": round((build_s + first_infer_s) * 1000, 1)},
               "gpu_mem": {"before_mb": mem_before, "after_mb": mem_after,
                           "delta_mb": (None if mem_before is None or mem_after is None
                                        else round(mem_after - mem_before, 1))},
               "models": {}}

    for key, model_name, fn in (
        ("pose", args.pose_model, lambda i: pose(frames[i % len(frames)], conf=0.45)),
        ("detr", args.detr_model, lambda i: detr(frames[i % len(frames)], conf=0.35)),
        ("act", args.act_model, lambda i: act(act_feats)),
    ):
        # local backend 沒有 server 端指標可抓（scrape 會回空 dict 並印警告），
        # 所以乾脆不抓：省掉兩次沒意義的 HTTP 與那行警告。client 端指標仍完整。
        before = scrape(args.metrics) if args.backend == "triton" else {}
        s = bench(model_name, fn, args.iters, args.warmup)
        if args.backend == "triton":
            s.update(server_side(before, scrape(args.metrics), model_name))
        results["models"][key] = {"model": model_name, **s}

    os.makedirs(args.out_dir, exist_ok=True)
    out = os.path.join(args.out_dir,
                       f"{datetime.now():%Y%m%d_%H%M%S}_{args.label}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n💾 已寫入 {out}")


if __name__ == "__main__":
    main()
