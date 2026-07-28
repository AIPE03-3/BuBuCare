"""把 AI 畫好框的畫面推回 MediaMTX 的偵測頻道（cam_out / phone_a_out …）。

為什麼需要這支：前端的「即時／偵測」切換鈕、後端的 stream_channel_detect 欄位、
MediaMTX 的 cam_out 頻道，這三層 kelly 都已經做好了，但 cam_out 在 MediaMTX 裡是
`source: publisher` —— 意思是「頻道開著門等人推進來」，MediaMTX 自己不產生任何畫面。
在這支之前沒有任何程式在推，所以切到「偵測」永遠是空的。

推的是 inference_test.py 已經畫好的 annotated_frame（yolo_pose 的骨架與框 + YOLO-Seg
的物件輪廓 + 狀態列），本來就只送到本機 cv2.imshow，這支只是多開一條出口。
**事件片段與快照刻意維持無框的原始畫面**（組長決策：彈窗當下有框會干擾人工確認），
所以這支完全不碰 write_event_clip / snapshot 那條路。

為什麼用 PyAV 而不是叫 ffmpeg 子程序：
  · PyAV 已經是本專案的相依（av_reader.py 拉流就是用它），拉流推流用同一套比較好維護；
  · 它自帶 libav 與 libx264，不需要機器上另外裝 ffmpeg 執行檔、也不吃 PATH
    （開發機實測：這台 5060 Ti 上沒有 ffmpeg，走子程序方案整個功能等於不能用）；
  · 少一層 stdin pipe，不用處理管線塞住與 BrokenPipe。

設計上的三個取捨：

1. **滿了就丟幀，絕不阻塞推論迴圈。** 推流是「看畫面」的附加功能，跌倒偵測才是主線。
   編碼跟不上時，讓即時畫面掉幀，也不能讓偵測慢一拍 —— 所以用有界佇列，滿了丟最舊的。
   即時串流本來就該丟舊幀，而不是排隊播放過期畫面。

2. **連線死了自動重連，但不重試到洗版。** MediaMTX 沒開、網路斷掉都會讓推流失敗，
   指數退避到 30 秒封頂，而且只在「狀態翻轉」時印訊息，不是每次重試都印。

3. **任何失敗都不得往上拋。** 推流壞掉最多就是前端看不到偵測畫面，不該讓一路相機的
   worker 掛掉、更不該影響已經發出去的警報。
"""

import queue
import threading
import time
from fractions import Fraction

import cv2

from backend_devices import cfg

# 未設＝不推流，行為與加這支之前位元級相同。要開就設 DETECT_STREAM=1。
DETECT_STREAM_ENABLED = cfg("DETECT_STREAM", "").strip().lower() in ("1", "true", "yes", "on")

# 推流用的畫面寬度。理由同片段緩衝的 CLIP_WIDTH：1080p 全解析度即時編碼很吃 CPU，
# 而「看得出人在哪、姿勢如何」640 寬綽綽有餘。設 0＝不縮放。
DETECT_STREAM_WIDTH = int(cfg("DETECT_STREAM_WIDTH", "640"))
DETECT_STREAM_WIDTH -= DETECT_STREAM_WIDTH % 2  # H.264 要求偶數邊長

# 名目張數，給編碼器當參考。實際到達速率由推論迴圈決定（通常更低且會變動），
# 時間戳走真實時鐘，所以這個值不會讓畫面變成慢動作。
DETECT_STREAM_FPS = float(cfg("DETECT_STREAM_FPS", "15"))

# 佇列深度。刻意設小：這是即時畫面，堆越多只是讓延遲越大。
DETECT_STREAM_QUEUE = int(cfg("DETECT_STREAM_QUEUE", "2"))

_MAX_BACKOFF = float(cfg("DETECT_STREAM_MAX_BACKOFF", "30"))

# 時間戳解析度。90kHz 是 RTP/視訊的慣例值。
_TIME_BASE = Fraction(1, 90000)


def av_available() -> bool:
    """PyAV 與 libx264 在不在。缺了就不推流，但不該讓整支 AI 起不來。"""
    try:
        import av
        return "libx264" in av.codecs_available
    except Exception:
        return False


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
        self._container = None
        self._stream = None
        # 尺寸在第一幀鎖定：H.264 串流中途換解析度會讓播放端解不開，
        # 之後的幀一律 resize 到同一個尺寸。
        self._size = None
        self._t0 = None
        self._last_pts = None
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
        self._teardown()
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

    def _open(self, w: int, h: int):
        """開一條 RTSP 推流連線到 MediaMTX。

        rtsp_transport=tcp：UDP 在區網外或稍有壅塞就破格，串流影像不像檔案可以重傳補救。
        kelly 的 mediamtx 說明也是走 tcp。
        """
        import av
        container = av.open(
            self.rtsp_url, mode="w", format="rtsp",
            options={"rtsp_transport": "tcp"},
        )
        stream = container.add_stream("libx264", rate=int(round(self.fps)))
        stream.width, stream.height = w, h
        stream.pix_fmt = "yuv420p"
        stream.time_base = _TIME_BASE
        # zerolatency：關掉 B-frame 與前瞻緩衝。監看畫面延遲比畫質重要。
        stream.options = {"preset": "ultrafast", "tune": "zerolatency"}
        return container, stream

    def _teardown(self):
        container, self._container = self._container, None
        stream, self._stream = self._stream, None
        if container is None:
            return
        try:
            if stream is not None:
                for pkt in stream.encode():      # 沖掉編碼器裡還沒吐出來的幀
                    container.mux(pkt)
        except Exception:
            pass
        try:
            container.close()
        except Exception:
            pass

    def _next_pts(self) -> int:
        """時間戳：以真實時鐘為準，但強制每幀至少隔一個「編碼器格子」。

        為什麼不能直接用真實時鐘（實測踩過）：libx264 是用 rate=fps 開的，muxer 會把
        pts 換算回編碼器的時間刻度（1/fps）。推論速度不穩時，相鄰兩幀的真實間隔可能
        小於一格 —— 例如 pts 4986 與 5184 在 24fps 下都會落進第 1 格，DTS 撞號，
        RTSP muxer 直接回 Invalid argument(22) 讓整條推流斷掉。
        平均間隔正常時完全看不出來，只有在速度抖動的那一瞬間才炸，很難查。

        為什麼也不能直接用「幀序號 × 每幀刻度」：推論的實際張數低於名目 fps 且會變動，
        照序號推算的話畫面會變成慢動作，而且延遲一路累積不會回頭。

        取兩者的較大值：慢於名目速率時跟著真實時鐘走（即時性正確），
        快到擠在同一格時則被強制拉開（不會撞號）。
        """
        wall = int((time.monotonic() - self._t0) / _TIME_BASE)
        step = max(1, int(_TIME_BASE.denominator / max(self.fps, 1)))
        pts = wall if self._last_pts is None else max(wall, self._last_pts + step)
        self._last_pts = pts
        return pts

    def _note(self, ok: bool, msg: str):
        """只在狀態翻轉時印。MediaMTX 沒開時會一直重試，每次都印就把 log 洗掉了。"""
        if self._last_state_ok != ok:
            print(msg)
            self._last_state_ok = ok

    def _run(self):
        import av  # 放在執行緒內：沒裝 PyAV 的機器不該在 import 本模組時就炸

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
                # 尺寸已鎖定，來源換了大小就配合縮回去。
                frame = cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA)

            if self._container is None:
                try:
                    self._container, self._stream = self._open(w, h)
                    self._t0 = time.monotonic()
                    self._last_pts = None
                    self._note(True, f"📤 [{self.camera_id}] 偵測畫面開始推流 → {self.rtsp_url}")
                    delay = 1.0
                except Exception as e:
                    self._note(False, f"🔁 [{self.camera_id}] 偵測推流連不上（{e}），"
                                      f"{delay:.0f}s 後重試：{self.rtsp_url}")
                    self._teardown()
                    self._stop.wait(delay)
                    delay = min(delay * 2, _MAX_BACKOFF)
                    continue

            try:
                vf = av.VideoFrame.from_ndarray(frame, format="bgr24")
                vf.pts = self._next_pts()
                vf.time_base = _TIME_BASE
                for pkt in self._stream.encode(vf):
                    self._container.mux(pkt)
                self._sent += 1
            except Exception as e:
                self._note(False, f"🔁 [{self.camera_id}] 偵測推流中斷（{e}），"
                                  f"{delay:.0f}s 後重連：{self.rtsp_url}")
                self._teardown()
                self._stop.wait(delay)
                delay = min(delay * 2, _MAX_BACKOFF)

        self._teardown()


def make_publisher(camera_id: str, detect_url: str, fps: float = None):
    """建立推流器；沒開關、沒網址、沒 PyAV 一律回 None（呼叫端只要判斷 None）。"""
    if not DETECT_STREAM_ENABLED or not detect_url:
        return None
    if not av_available():
        print(f"⚠️ [{camera_id}] DETECT_STREAM=1 但 PyAV/libx264 不可用，偵測推流略過"
              f"（其餘功能不受影響）")
        return None
    try:
        return DetectStreamPublisher(camera_id, detect_url, fps=fps)
    except Exception as e:
        print(f"⚠️ [{camera_id}] 偵測推流建立失敗（{e}），略過推流，其餘功能不受影響")
        return None
