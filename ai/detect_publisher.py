"""把 AI 畫好框的畫面推回 MediaMTX 的偵測頻道（cam_out / phone_a_out …）。

為什麼需要這支：前端的「即時／偵測」切換鈕、後端的 stream_channel_detect 欄位、
MediaMTX 的 cam_out 頻道，這三層 kelly 都已經做好了，但 cam_out 在 MediaMTX 裡是
`source: publisher` —— 意思是「頻道開著門等人推進來」，MediaMTX 自己不產生任何畫面。
在這支之前沒有任何程式在推，所以切到「偵測」永遠是空的。

推的是 inference_test.py 已經畫好的 annotated_frame（yolo_pose 的骨架與框 + YOLO-Seg
的物件輪廓 + 狀態列），本來就只送到本機 cv2.imshow，這支只是多開一條出口。
**事件片段與快照刻意維持無框的原始畫面**（組長決策：彈窗當下有框會干擾人工確認），
所以這支完全不碰 write_event_clip / snapshot 那條路。

做法：開一支 ffmpeg 子程序，stdin 收 BGR 原始幀，編成 H.264 推進 MediaMTX。
與 kelly 的 start-fake-detect.ps1 走同一條路（ffmpeg → rtsp），差別只在畫面來源
從「ffmpeg 自己畫的固定紅框」換成「AI 真正畫的骨架與框」——換的是 MediaMTX 上游，
前端、後端、資料庫都不用改。

⚠️ 需要機器上裝好 ffmpeg（`sudo apt install ffmpeg` / `winget install Gyan.FFmpeg`）。
   沒裝就不推流並印訊息，其餘功能完全不受影響。找不到時可用 DETECT_STREAM_FFMPEG
   指定完整路徑（裝在非標準位置、或用免安裝的靜態版時）。

設計上的四個取捨：

1. **滿了就丟幀，絕不阻塞推論迴圈。** 推流是「看畫面」的附加功能，跌倒偵測才是主線。
   編碼跟不上時，讓即時畫面掉幀，也不能讓偵測慢一拍 —— 所以用有界佇列，滿了丟最舊的。
   即時串流本來就該丟舊幀，而不是排隊播放過期畫面。

2. **時間戳走真實時鐘 + CFR 整流**（`-use_wallclock_as_timestamps 1` 搭 `-fps_mode cfr`）。
   只用其中一個都會出事，見 _build_cmd() 的說明 —— 這是實測踩過的坑。

3. **ffmpeg 死了自動重啟，但不重試到洗版。** MediaMTX 沒開、網路斷掉都會讓 ffmpeg
   立刻退出，若不退避會變成每秒 fork 一次程序。指數退避到 30 秒封頂，
   而且只在「狀態翻轉」時印訊息，不是每次重試都印。

4. **任何失敗都不得往上拋。** 推流壞掉最多就是前端看不到偵測畫面，不該讓一路相機的
   worker 掛掉、更不該影響已經發出去的警報。
"""

import collections
import os
import queue
import shutil
import subprocess
import threading

import cv2

from backend_devices import cfg

# 未設＝不推流，行為與加這支之前位元級相同。要開就設 DETECT_STREAM=1。
DETECT_STREAM_ENABLED = cfg("DETECT_STREAM", "").strip().lower() in ("1", "true", "yes", "on")

# ffmpeg 執行檔。預設吃 PATH；裝在非標準位置（或用免安裝靜態版）時指定完整路徑。
DETECT_STREAM_FFMPEG = cfg("DETECT_STREAM_FFMPEG", "ffmpeg")

# 推流用的畫面寬度。理由同片段緩衝的 CLIP_WIDTH：1080p 全解析度即時編碼很吃 CPU，
# 而「看得出人在哪、姿勢如何」640 寬綽綽有餘。設 0＝不縮放。
DETECT_STREAM_WIDTH = int(cfg("DETECT_STREAM_WIDTH", "640"))
DETECT_STREAM_WIDTH -= DETECT_STREAM_WIDTH % 2  # H.264 要求偶數邊長

# 目標張數。CFR 整流會把實際到達速率對齊到這個值（不足補幀、超過丟幀）。
DETECT_STREAM_FPS = float(cfg("DETECT_STREAM_FPS", "15"))

# 佇列深度。刻意設小：這是即時畫面，堆越多只是讓延遲越大。
DETECT_STREAM_QUEUE = int(cfg("DETECT_STREAM_QUEUE", "2"))

_MAX_BACKOFF = float(cfg("DETECT_STREAM_MAX_BACKOFF", "30"))


def ffmpeg_path() -> str:
    """ffmpeg 的可執行路徑；找不到回空字串。"""
    p = DETECT_STREAM_FFMPEG
    if os.path.sep in p:
        return p if os.path.isfile(p) and os.access(p, os.X_OK) else ""
    return shutil.which(p) or ""


class DetectStreamPublisher:
    """單路相機的偵測畫面推流器。publish() 可從推論迴圈直接呼叫，不會阻塞。"""

    def __init__(self, camera_id: str, rtsp_url: str,
                 fps: float = None, width: int = None):
        self.camera_id = camera_id
        self.rtsp_url = rtsp_url
        self.fps = fps or DETECT_STREAM_FPS
        self.width = DETECT_STREAM_WIDTH if width is None else width

        self._queue = queue.Queue(maxsize=max(1, DETECT_STREAM_QUEUE))
        self._stop = threading.Event()
        self._proc = None
        self._err_tail = collections.deque(maxlen=6)   # ffmpeg 最後幾行 stderr，失敗時當診斷
        self._err_thread = None
        # 尺寸在第一幀鎖定：rawvideo 的 -s 一旦告訴 ffmpeg 就不能中途變，
        # 之後的幀一律 resize 到同一個尺寸，否則 ffmpeg 會把畫面解析成花屏。
        self._size = None
        self._dropped = 0
        self._sent = 0
        self._last_state_ok = None   # 只在狀態翻轉時印訊息，避免洗版

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    # ── 對外：推論迴圈呼叫這支 ──────────────────────────────────────────
    def publish(self, frame) -> None:
        """把一幀丟進佇列。**永不阻塞、永不拋例外。**

        佇列滿代表編碼端跟不上，這時丟掉最舊的那幀再放新的 —— 即時畫面要的是「現在」，
        排隊播過期畫面沒有意義，而且會讓延遲一路累積。
        """
        if self._stop.is_set():
            return
        try:
            small = self._downscale(frame)
            try:
                self._queue.put_nowait(small)
            except queue.Full:
                # 丟掉最舊的一幀再放新的。get_nowait 可能剛好被消費者取走而 Empty，
                # 那就代表位置已經空出來了，直接放。
                try:
                    self._queue.get_nowait()
                    self._dropped += 1
                except queue.Empty:
                    pass
                try:
                    self._queue.put_nowait(small)
                except queue.Full:
                    self._dropped += 1
        except Exception:
            # 推流是附加功能，任何意外都不該影響推論主線。
            pass

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        _kill(self._proc)
        self._proc = None
        if self._sent or self._dropped:
            print(f"📤 [{self.camera_id}] 偵測推流結束（送出 {self._sent} 幀、"
                  f"丟棄 {self._dropped} 幀；丟幀屬正常，編碼跟不上時優先保推論）")

    @property
    def stats(self) -> dict:
        return {"sent": self._sent, "dropped": self._dropped}

    # ── 內部 ────────────────────────────────────────────────────────────
    def _downscale(self, frame):
        if self.width <= 0:
            return frame
        h, w = frame.shape[:2]
        if w <= self.width:
            return frame
        new_h = int(round(h * self.width / w))
        new_h -= new_h % 2
        return cv2.resize(frame, (self.width, max(new_h, 2)), interpolation=cv2.INTER_AREA)

    def _build_cmd(self, w: int, h: int) -> list:
        """組 ffmpeg 指令：stdin 收 BGR 原始幀 → H.264 → RTSP 推進 MediaMTX。

        時間戳這組參數是實測調出來的，兩個都不能少：

        · `-use_wallclock_as_timestamps 1`：時間戳取「幀真正到達的時刻」。少了它，
          rawvideo 會照 `-r` 推算時間，而推論的實際張數低於名目值且會變動，
          串流就會變成慢動作、延遲一路累積不會回頭。

        · `-fps_mode cfr`：把不規則的到達速率整流成固定張數（不足補幀、超過丟幀）。
          少了它，光靠真實時鐘會踩到另一個坑 —— 編碼器以 `-r` 的刻度記時間戳，
          推論速度一抖動、相鄰兩幀擠進同一格就 DTS 撞號，整條推流直接斷掉。
          這個坑在平順推流時完全測不出來，只有速度抖動的那一瞬間才炸。

        `-tune zerolatency` 關掉 B-frame 與前瞻緩衝：監看畫面延遲比畫質重要。
        `-rtsp_transport tcp`：UDP 稍有壅塞就破格，串流影像不像檔案能重傳補救。
        """
        return [
            ffmpeg_path(), "-hide_banner", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "bgr24",
            "-s", f"{w}x{h}", "-r", f"{self.fps:g}",
            "-use_wallclock_as_timestamps", "1",
            "-i", "-",
            "-an",
            "-fps_mode", "cfr",
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
            "-pix_fmt", "yuv420p", "-g", str(max(1, int(self.fps * 2))),
            "-f", "rtsp", "-rtsp_transport", "tcp", self.rtsp_url,
        ]

    def _spawn(self, w: int, h: int):
        proc = subprocess.Popen(self._build_cmd(w, h), stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        # stderr 要有人一直讀：不讀的話 pipe 滿了 ffmpeg 會卡住寫不動而假死。
        # 只留最後幾行，推流失敗時當診斷用（比「就是不動」好查太多）。
        self._err_tail.clear()

        def _drain(pipe, sink):
            try:
                for line in iter(pipe.readline, b""):
                    text = line.decode("utf-8", "replace").strip()
                    if text:
                        sink.append(text)
            except Exception:
                pass

        self._err_thread = threading.Thread(target=_drain, args=(proc.stderr, self._err_tail),
                                            daemon=True)
        self._err_thread.start()
        return proc

    def _why(self) -> str:
        """ffmpeg 最後吐的錯誤，給重連訊息當理由。"""
        return "；".join(self._err_tail) or "沒有 ffmpeg 錯誤輸出"

    def _note(self, ok: bool, msg: str):
        """只在狀態翻轉時印。MediaMTX 沒開時會一直重試，每次都印就把 log 洗掉了。"""
        if self._last_state_ok != ok:
            print(msg)
            self._last_state_ok = ok

    def _run(self):
        delay = 1.0
        while not self._stop.is_set():
            try:
                frame = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if self._size is None:
                h, w = frame.shape[:2]
                self._size = (w, h)
            w, h = self._size
            if frame.shape[1] != w or frame.shape[0] != h:
                # 尺寸已鎖定，來源換了大小就配合縮回去，不能直接送進 ffmpeg。
                frame = cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA)

            if self._proc is None or self._proc.poll() is not None:
                if self._proc is not None:
                    self._note(False, f"🔁 [{self.camera_id}] 偵測推流中斷（{self._why()}），"
                                      f"{delay:.0f}s 後重連：{self.rtsp_url}")
                    _kill(self._proc)
                    self._proc = None
                    self._stop.wait(delay)
                    delay = min(delay * 2, _MAX_BACKOFF)
                    continue
                if not ffmpeg_path():
                    self._note(False, f"⚠️ [{self.camera_id}] 找不到 ffmpeg，偵測推流停用"
                                      f"（裝好 ffmpeg 或設 DETECT_STREAM_FFMPEG 指定路徑後重啟）")
                    self._stop.set()
                    break
                try:
                    self._proc = self._spawn(w, h)
                    self._note(True, f"📤 [{self.camera_id}] 偵測畫面開始推流 → {self.rtsp_url}")
                    delay = 1.0
                except Exception as e:
                    self._note(False, f"🔁 [{self.camera_id}] 偵測推流啟動失敗（{e}），"
                                      f"{delay:.0f}s 後重試：{self.rtsp_url}")
                    self._stop.wait(delay)
                    delay = min(delay * 2, _MAX_BACKOFF)
                    continue

            try:
                self._proc.stdin.write(frame.tobytes())
                self._sent += 1
            except (BrokenPipeError, ValueError, OSError):
                # ffmpeg 掛了（MediaMTX 沒開、被踢掉、網路斷）。下一圈會走上面的重連分支。
                _kill(self._proc)
                self._proc = None

        _kill(self._proc)
        self._proc = None


def _kill(proc):
    if proc is None:
        return
    try:
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.close()      # 先關 stdin 讓 ffmpeg 自己收尾，別直接砍
    except Exception:
        pass
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def make_publisher(camera_id: str, detect_url: str, fps: float = None):
    """建立推流器；沒開關、沒網址、沒 ffmpeg 一律回 None（呼叫端只要判斷 None）。"""
    if not DETECT_STREAM_ENABLED or not detect_url:
        return None
    if not ffmpeg_path():
        print(f"⚠️ [{camera_id}] DETECT_STREAM=1 但找不到 ffmpeg（{DETECT_STREAM_FFMPEG}），"
              f"偵測推流略過；其餘功能不受影響。"
              f"安裝：sudo apt install ffmpeg，或設 DETECT_STREAM_FFMPEG 指定完整路徑")
        return None
    try:
        return DetectStreamPublisher(camera_id, detect_url, fps=fps)
    except Exception as e:
        print(f"⚠️ [{camera_id}] 偵測推流建立失敗（{e}），略過推流，其餘功能不受影響")
        return None
