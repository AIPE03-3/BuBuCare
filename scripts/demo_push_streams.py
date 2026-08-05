#!/usr/bin/env python3
"""把 ai/test_demo/ 的影片推進 MediaMTX 的多個頻道，每支播完隨機換下一支。

## 這支要解的問題

前端首頁是四宮格，四格各自綁一台裝置、各自開一條獨立的 WebRTC
（`frontend/src/pages/Home.tsx` 的 `gridCameras`）。後端 DB 也已經有四台 active 裝置
分別指向 `cam_in` / `phone_a` / `phone_b` / `phone_c` 四個 MediaMTX 頻道。
AI 端 `inference_test.py` 更是**一台相機一條 worker 執行緒**。

也就是說「四格各播各的、YOLO 各讀各的」這件事整條鏈路本來就通——
唯一缺的是**沒有任何影片被推進那四個頻道**，所以四格全是灰色占位框。這支就是補那一塊。

## 為什麼不用 `-stream_loop -1`

既有文件（docs/TEST-PLAN-E2E.md、docs/MAC_SETUP_WBS.md）都是用 `-stream_loop -1`
讓同一支影片無限重播。那個做法拿來當 demo 有兩個問題：

1. 每一輪跌倒發生的時間點完全一樣，看起來就是在跑錄影帶，不像隨機事件。
2. docs/NEXT_STAGE.md 第 16 項已經記過：`-stream_loop` 讓人物每輪都從頭走一次，
   位置漂移遠超過去重門檻，事件數會被放大到失真。

所以這裡改成「ffmpeg 播完一支就正常結束 → 本腳本隨機抽下一支重開」。
每個頻道各自獨立抽，四格的節奏自然錯開。

## 為什麼要 `--prepare` 先轉檔

`ai/test_demo/*.mp4` 是 **AV1** 編碼（這也是 `ai/av_reader.py` 存在的原因——cv2 解不了）。
AV1 即時解碼 ×4 路很吃 CPU，而且推流端跟 AI 端會重複解兩次。
`--prepare` 先一次性轉成 H.264 存快取，之後推流用 `-c:v copy` 直接搬位元流，執行期幾乎零成本。

## 用法

    python scripts/demo_push_streams.py --prepare   # 一次性，把 AV1 轉成 H.264 快取
    python scripts/demo_push_streams.py             # 開始推，Ctrl-C 全部收掉

搭配 AI 端（`CAMERA_SOURCE` 預設就是 backend，會自己去 GET /devices 拿這四個頻道）：

    HEADLESS=1 DETR_EVERY_N=10 DECODE_PREFETCH=1 ai/.venv/bin/python -u ai/inference_test.py
"""
from __future__ import annotations

import argparse
import os
import random
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# 對齊後端 DB 裡四台 active 裝置的 stream_channel（301/302/303/304）。
# 改這裡之前先確認 GET /devices 回來的頻道名，兩邊對不上 AI 端就拉不到流。
DEFAULT_CHANNELS = ("cam_in", "phone_a", "phone_b", "phone_c")

DEFAULT_VIDEO_DIR = REPO_ROOT / "ai" / "test_demo"

# test4.mp4 是 360 MB 的 FPS 壓測長片，不是 demo 素材：推起來要好幾分鐘才換片，
# 而且轉檔快取會多吃幾百 MB。其餘 test1~test26 都是十幾秒到一分鐘的短片。
EXCLUDE_NAMES = frozenset({"test4.mp4"})

# 轉檔快取放 scratchpad，不落在 repo 裡（*.mp4 本來就在 .gitignore，但也不該弄髒工作區）
DEFAULT_CACHE_DIR = Path(
    os.environ.get("DEMO_STREAM_CACHE_DIR")
    or (Path(os.environ.get("TMPDIR", "/tmp")) / "aipe03-demo-h264")
)

# 換節目之間的空檔。給 MediaMTX 一點時間把舊 publisher 收乾淨，
# 太短的話新的 ffmpeg 會撞上「path already has a publisher」。
GAP_SECONDS = 0.8

# 一次 ffmpeg 連續播幾支影片（concat 播放清單的長度）。
#
# 為什麼不是一支一支推：**MediaMTX 在推流端離開時會一併踢掉所有觀看者**
# （已實測：對 cam_in 開一個 RTSP reader，換片瞬間 reader 就結束了）。
# 素材只有 8~29 秒，一支一支推等於前端每二十幾秒黑一次畫面，很難看。
# 改成一次把 N 支隨機排好的影片用 concat demuxer 串成一個節目連續推，
# publisher 就能撐好幾分鐘不斷線，而「隨機」仍然成立——清單本身是隨機排的，
# 播完再重抽一份新的。
PLAYLIST_SIZE = 8

# concat demuxer 用 -c copy 串接的前提：所有片段的編碼參數要一致。
# 素材原生 fps/解析度並不一致，所以 --prepare 轉檔時一律正規化成下面這組。
NORMALISED_FPS = 20
NORMALISED_WIDTH = 1920
NORMALISED_HEIGHT = 1080
NORMALISED_TIMESCALE = 10240


# ─────────────────────────────────────────────────────────────────────────
# ffmpeg 執行檔
# ─────────────────────────────────────────────────────────────────────────
def find_ffmpeg() -> str:
    """找 ffmpeg。優先 PATH，退回 ai/.venv 裡 imageio-ffmpeg 附的靜態版。

    這台機器的 PATH 上沒有 ffmpeg，一直是靠 imageio-ffmpeg 帶的那顆
    （docs/TEST-PLAN-E2E.md 有記）。⚠ 不要改成 apt install ffmpeg：
    那會裝進系統汙染其他專案，而且 WSL2 重建又要再來一次。
    venv 重建後 imageio-ffmpeg 會不見（它不在 requirements 裡），補裝指令見下方錯誤訊息。
    """
    env_path = os.environ.get("DEMO_STREAM_FFMPEG", "").strip()
    if env_path:
        if not Path(env_path).is_file():
            sys.exit(f"❌ DEMO_STREAM_FFMPEG 指到的檔案不存在：{env_path}")
        return env_path

    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path

    venv_python = REPO_ROOT / "ai" / ".venv" / "bin" / "python"
    if venv_python.is_file():
        try:
            out = subprocess.run(
                [str(venv_python), "-c", "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())"],
                capture_output=True, text=True, timeout=30,
            )
            candidate = out.stdout.strip()
            if out.returncode == 0 and candidate and Path(candidate).is_file():
                return candidate
        except (subprocess.SubprocessError, OSError):
            pass

    sys.exit(
        "❌ 找不到 ffmpeg。\n"
        "   這台 PATH 上沒有 ffmpeg，本專案一律用 ai/.venv 裡 imageio-ffmpeg 附的靜態版。\n"
        "   補裝：ai/.venv/bin/python -m pip install imageio-ffmpeg\n"
        "   ⚠ 不要改用 apt install ffmpeg（會裝進系統汙染其他專案）。"
    )


# ─────────────────────────────────────────────────────────────────────────
# 素材
# ─────────────────────────────────────────────────────────────────────────
def list_source_videos(video_dir: Path) -> list[Path]:
    videos = sorted(
        p for p in video_dir.glob("*.mp4")
        if p.is_file() and p.name not in EXCLUDE_NAMES
    )
    if not videos:
        sys.exit(f"❌ {video_dir} 底下找不到可用的 mp4（已排除 {', '.join(sorted(EXCLUDE_NAMES))}）")
    return videos


def prepare_cache(ffmpeg: str, videos: list[Path], cache_dir: Path) -> None:
    """把 AV1 素材一次性轉成 H.264 存快取。已存在且比原檔新的就跳過。"""
    cache_dir.mkdir(parents=True, exist_ok=True)
    todo = [v for v in videos if not _cache_is_fresh(v, cache_dir / v.name)]

    print(f"📦 轉檔快取：{cache_dir}")
    print(f"   素材 {len(videos)} 支，需要轉 {len(todo)} 支（其餘已是最新）")
    if not todo:
        print("✅ 快取已是最新，不用轉")
        return

    for i, src in enumerate(todo, 1):
        dst = cache_dir / src.name
        print(f"   [{i}/{len(todo)}] {src.name} → H.264 …", flush=True)
        # -an：demo 不需要聲音，也省掉 RTSP 端的音訊協商
        # veryfast + crf 23：轉檔是一次性的，畫質比轉檔速度重要一點
        result = subprocess.run(
            [ffmpeg, "-nostdin", "-y", "-loglevel", "error", "-i", str(src),
             "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
             "-pix_fmt", "yuv420p", "-g", "30",
             # ↓ 這三個是為了讓 concat demuxer 能用 -c copy 串起來（見 build_playlist）。
             #   素材原生 fps 不一致（實測 test1 是 24、test9/20/26 是 20），
             #   時基也跟著不同；不統一的話 concat 出來的時間軸會亂跳。
             "-r", str(NORMALISED_FPS),
             "-vf", f"scale={NORMALISED_WIDTH}:{NORMALISED_HEIGHT}:force_original_aspect_ratio=decrease,"
                    f"pad={NORMALISED_WIDTH}:{NORMALISED_HEIGHT}:(ow-iw)/2:(oh-ih)/2",
             "-video_track_timescale", str(NORMALISED_TIMESCALE),
             str(dst)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            dst.unlink(missing_ok=True)
            sys.exit(f"❌ 轉檔失敗：{src.name}\n{result.stderr.strip()[:800]}")

    print(f"✅ 轉檔完成，共 {len(todo)} 支")


def _cache_is_fresh(src: Path, cached: Path) -> bool:
    return cached.is_file() and cached.stat().st_size > 0 and cached.stat().st_mtime >= src.stat().st_mtime


# ─────────────────────────────────────────────────────────────────────────
# 推流
# ─────────────────────────────────────────────────────────────────────────
class ChannelPusher(threading.Thread):
    """一個頻道一條執行緒：抽一支影片 → 推完 → 再抽一支，直到被叫停。

    刻意一個頻道一條執行緒而不是單執行緒輪詢：四個頻道的影片長度不一樣，
    換片時間點必須各自獨立，否則四格會同步換片、看起來像同一個節目在切台。
    """

    def __init__(self, ffmpeg: str, channel: str, videos: list[Path], rtsp_base: str,
                 rng: random.Random, playlist_dir: Path, playlist_size: int):
        super().__init__(name=f"push-{channel}", daemon=True)
        self.ffmpeg = ffmpeg
        self.channel = channel
        self.videos = videos
        self.url = f"{rtsp_base.rstrip('/')}/{channel}"
        self.rng = rng
        self.playlist_path = playlist_dir / f"{channel}.txt"
        self.playlist_size = playlist_size
        self.stop_event = threading.Event()
        self.proc: subprocess.Popen | None = None

    def _write_playlist(self) -> list[str]:
        """隨機排一份播放清單寫成 concat demuxer 吃的檔案，回傳片名供顯示。

        用 sample 而非逐次 choice：一輪之內不重複，四格同時看才不會有兩格在播同一支。
        素材不足 playlist_size 時就整個打亂當一輪（sample 會丟例外，所以要分開處理）。
        """
        if len(self.videos) <= self.playlist_size:
            picked = self.rng.sample(self.videos, len(self.videos))
        else:
            picked = self.rng.sample(self.videos, self.playlist_size)

        # concat demuxer 的格式：每行 file '<路徑>'。路徑裡的單引號要跳脫，
        # 素材檔名是 testN.mp4 不會有，但別讓它變成換個素材就炸的地雷。
        lines = [f"file '{str(p).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'" for p in picked]
        self.playlist_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return [p.name for p in picked]

    def run(self) -> None:
        while not self.stop_event.is_set():
            names = self._write_playlist()
            print(f"▶️  [{self.channel}] {' → '.join(names)}", flush=True)
            # -re：照原速推，不加的話 ffmpeg 會用最快速度灌完，畫面變快轉
            # -f concat：一次連續播完整份清單，publisher 不中斷（見 PLAYLIST_SIZE 的說明）
            # -safe 0：清單裡是絕對路徑，不加會被 concat demuxer 以安全理由拒收
            # -c:v copy：素材已正規化成同一組編碼參數（--prepare），直接搬位元流不重編
            # -rtsp_transport tcp：UDP 在 WSL2 會掉封包，docs/TEST-PLAN-E2E.md 記過這是必要的
            cmd = [
                self.ffmpeg, "-nostdin", "-re",
                "-f", "concat", "-safe", "0", "-i", str(self.playlist_path),
                "-an", "-c:v", "copy",
                "-f", "rtsp", "-rtsp_transport", "tcp", self.url,
            ]
            try:
                self.proc = subprocess.Popen(
                    cmd, stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                )
            except OSError as e:
                print(f"❌ [{self.channel}] 起 ffmpeg 失敗：{e}", flush=True)
                self.stop_event.wait(5)
                continue

            _, stderr = self.proc.communicate()
            code = self.proc.returncode
            self.proc = None

            if self.stop_event.is_set():
                return
            # 正常播完是 0；被 SIGTERM 收掉是負數，那是我們自己叫停的，不算錯
            if code not in (0, -signal.SIGTERM, -signal.SIGINT):
                msg = (stderr or b"").decode("utf-8", "replace").strip().splitlines()
                tail = msg[-1] if msg else f"return code {code}"
                print(f"⚠️  [{self.channel}] ffmpeg 結束（{tail}），2 秒後換下一輪", flush=True)
                self.stop_event.wait(2.0)
            else:
                self.stop_event.wait(GAP_SECONDS)

    def stop(self) -> None:
        self.stop_event.set()
        proc = self.proc
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="把 test_demo 影片推進 MediaMTX 多個頻道，每支播完隨機換下一支",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--channels", default=",".join(DEFAULT_CHANNELS),
                        help=f"逗號分隔的 MediaMTX 頻道名（預設 {','.join(DEFAULT_CHANNELS)}）")
    parser.add_argument("--dir", type=Path, default=DEFAULT_VIDEO_DIR, help="素材目錄")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR, help="H.264 轉檔快取目錄")
    parser.add_argument("--rtsp-base", default=os.environ.get("DEMO_STREAM_RTSP_BASE", "rtsp://127.0.0.1:8554"),
                        help="MediaMTX 的 RTSP 位址（預設 rtsp://127.0.0.1:8554）")
    parser.add_argument("--prepare", action="store_true",
                        help="只做一次性 AV1→H.264 轉檔快取，不推流")
    parser.add_argument("--playlist-size", type=int, default=PLAYLIST_SIZE,
                        help=f"一次 ffmpeg 連續播幾支（預設 {PLAYLIST_SIZE}；調小＝換得更頻繁但畫面會多黑一下）")
    parser.add_argument("--seed", type=int, default=None, help="固定隨機序列，方便重現某次 demo")
    args = parser.parse_args()

    ffmpeg = find_ffmpeg()
    sources = list_source_videos(args.dir)

    if args.prepare:
        prepare_cache(ffmpeg, sources, args.cache_dir)
        return 0

    # 沒轉過快取就先擋下來，不要靜默用 AV1 硬推（會很慢又佔 CPU，而且不好察覺）
    cached = [args.cache_dir / v.name for v in sources]
    missing = [c.name for c, v in zip(cached, sources) if not _cache_is_fresh(v, c)]
    if missing:
        sys.exit(
            f"❌ 轉檔快取缺 {len(missing)} 支（例如 {', '.join(missing[:3])}）。\n"
            f"   先跑一次：python {Path(__file__).relative_to(REPO_ROOT)} --prepare"
        )

    channels = [c.strip() for c in args.channels.split(",") if c.strip()]
    if not channels:
        sys.exit("❌ --channels 是空的")

    playlist_dir = args.cache_dir / "playlists"
    playlist_dir.mkdir(parents=True, exist_ok=True)

    rng_seed = args.seed
    print(f"🎬 ffmpeg   : {ffmpeg}")
    print(f"🎬 素材     : {len(cached)} 支（{args.cache_dir}）")
    print(f"🎬 頻道     : {', '.join(channels)} → {args.rtsp_base}")
    print(f"🎬 每輪     : {args.playlist_size} 支連續播（publisher 不中斷）")
    print(f"🎬 隨機種子 : {rng_seed if rng_seed is not None else '未固定'}")
    print("   Ctrl-C 收掉全部\n")

    pushers = [
        # 每個頻道各自一顆 rng：固定 seed 時四個頻道的序列才是可重現且互不相同的
        ChannelPusher(ffmpeg, ch, cached, args.rtsp_base,
                      random.Random(None if rng_seed is None else rng_seed + i),
                      playlist_dir, args.playlist_size)
        for i, ch in enumerate(channels)
    ]
    for p in pushers:
        p.start()

    try:
        while any(p.is_alive() for p in pushers):
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n🛑 收掉全部推流…")
    finally:
        for p in pushers:
            p.stop()
        for p in pushers:
            p.join(timeout=10)
    print("✅ 已停止")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
